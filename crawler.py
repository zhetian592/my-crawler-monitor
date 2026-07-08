#!/usr/bin/env python3
# rss_proxy.py - 自建 RSS 代理（线程安全、健壮路由、内容校验）
# 启动: python rss_proxy.py --port 1200

import argparse
import json
import re
import time
import random
import logging
import sys
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from xml.sax.saxutils import escape as xml_escape

import requests
from bs4 import BeautifulSoup

# ============ 日志 ============
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('rss-proxy')

# ============ 配置 ============
CACHE_TTL = 900                     # 15 分钟
CACHE_MAX_SIZE = 200                # 最大缓存条目数
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36",
]

# Nitter 实例池（目前大多数已不可用，保留作为备用）
NITTER_POOL = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nitter.tiekoetter.com",
    "https://xcancel.com",
]

# ============ 线程安全缓存（修复 1） ============
_cache = OrderedDict()
_cache_lock = threading.Lock()

def cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[0] < CACHE_TTL:
            # 更新访问顺序（LRU）
            _cache.move_to_end(key)
            return entry[1]
        return None

def cache_set(key, content):
    with _cache_lock:
        _cache[key] = (time.time(), content)
        _cache.move_to_end(key)
        if len(_cache) > CACHE_MAX_SIZE:
            # 弹出最旧的条目（LRU）
            _cache.popitem(last=False)

# ============ HTTP 工具 ============
def fetch(url, timeout=25, max_attempts=3):
    """
    带重试的 HTTP GET
    修复 7：参数名改为 max_attempts，重试间隔为 2^(attempt) 秒
    """
    headers = {"User-Agent": random.choice(UA_LIST)}
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            wait = 2 ** attempt  # 1, 2, 4
            time.sleep(wait)

def is_valid_rss_content(text: str) -> bool:
    """简单校验是否为 RSS 内容（修复 5）"""
    text = text.strip()
    return text.startswith('<?xml') and '<rss' in text and '<channel>' in text

def build_rss(title, link, desc, items):
    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n<channel>\n'
    xml += f'<title>{xml_escape(title)}</title>\n<link>{xml_escape(link)}</link>\n<description>{xml_escape(desc)}</description>\n<lastBuildDate>{now}</lastBuildDate>\n'
    for item in items:
        pub = item.get("pubDate", now)
        xml += '<item>\n'
        xml += f'<title>{xml_escape(item["title"])}</title>\n<link>{xml_escape(item["link"])}</link>\n<description>{xml_escape(item.get("description", ""))}</description>\n<pubDate>{pub}</pubDate>\n<guid>{xml_escape(item.get("link", item["title"]))}</guid>\n</item>\n'
    xml += '</channel>\n</rss>'
    return xml

# ============ 直接 RSS 代理（移除已知失效的源，修复 4） ============
RSS_DIRECT = {
    "bbc":        "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
    "dw":         "https://rss.dw.com/rdf/rss-chi-all",
    "rfi":        "https://www.rfi.fr/cn/general/rss",
    "nytimes":    "https://cn.nytimes.com/rss/news.xml",
    # "uscc":       "https://www.uscc.gov/rss.xml",   # 已证实 404，移除
    "brookings":  "https://www.brookings.edu/feed/?topic=china",
    "freedomhouse": "https://freedomhouse.org/rss.xml",
    "aspi":       "https://www.aspistrategist.org.au/feed/",
    "hrw":        "https://www.hrw.org/rss/news",
    "amnesty":    "https://www.amnesty.org/en/feed/",
    "fdd":        "https://www.fdd.org/feed/",
    "chinapower": "https://chinapower.csis.org/feed/",
    "carnegie":   "https://carnegieendowment.org/rss",
    # "chathamhouse": "https://www.chathamhouse.org/rss", # 已证实 403，移除
    "epochtimes": "https://feed.theepochtimes.com/china/feed",
}

def proxy_direct_rss(name):
    """代理直接 RSS 源，并校验内容是否为有效 RSS（修复 5）"""
    url = RSS_DIRECT.get(name)
    if not url:
        return None, 404
    cached = cache_get(f"rss:{name}")
    if cached:
        return cached, 200
    try:
        resp = fetch(url, timeout=20)
        if not is_valid_rss_content(resp.text):
            logger.warning(f"[{name}] 返回内容不是有效 RSS，URL: {url}")
            return f"上游返回内容无效", 502
        cache_set(f"rss:{name}", resp.text)
        return resp.text, 200
    except Exception as e:
        logger.error(f"[{name}] 代理失败: {e}")
        return f"上游 RSS 不可用: {e}", 502

# ============ HTML 抓取 -> RSS（精确选择器 + 日志，修复 6） ============
def scrape_ntdtv():
    """抓取 NTD 即时新闻"""
    cached = cache_get("scrape:ntdtv")
    if cached:
        return cached, 200
    try:
        resp = fetch("https://www.ntdtv.com/gb/instant-news.html", timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        # 更精确的选择器：只取文章列表
        for el in soup.select(".post-list .post-item")[:30]:
            a = el.select_one("h2 a, h3 a, .title a")
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a.get("href", "")
            if link and not link.startswith("http"):
                link = "https://www.ntdtv.com" + link
            desc_el = el.select_one(".excerpt, .summary")
            desc = desc_el.get_text(strip=True) if desc_el else title
            if title and link:
                items.append({"title": title, "link": link, "description": desc})
        logger.info(f"[NTDTV] 抓取到 {len(items)} 条文章")
        rss = build_rss("NTDTV 即时新闻", "https://www.ntdtv.com/gb/instant-news.html", "NTDTV 即时 RSS", items)
        cache_set("scrape:ntdtv", rss)
        return rss, 200
    except Exception as e:
        logger.error(f"[NTDTV] 抓取失败: {e}")
        return f"抓取失败: {e}", 502

def scrape_zaobao(path):
    """抓取联合早报"""
    cache_key = f"scrape:zaobao:{path}"
    cached = cache_get(cache_key)
    if cached:
        return cached, 200
    url_map = {"realtime": "https://www.zaobao.com/realtime", "znews": "https://www.zaobao.com/news/china"}
    url = url_map.get(path)
    if not url:
        return "未知路径", 404
    try:
        resp = fetch(url, timeout=20)
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        # 使用更精确的选择器：文章列表
        for el in soup.select("div[data-article-id], .article-list article")[:30]:
            a = el.select_one("h2 a, h3 a, .headline a")
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a.get("href", "")
            if link and not link.startswith("http"):
                link = "https://www.zaobao.com" + link
            desc_el = el.select_one(".excerpt, .summary")
            desc = desc_el.get_text(strip=True) if desc_el else title
            if title and link:
                items.append({"title": title, "link": link, "description": desc})
        logger.info(f"[Zaobao/{path}] 抓取到 {len(items)} 条文章")
        title_map = {"realtime": "联合早报 即时新闻", "znews": "联合早报 中国新闻"}
        rss = build_rss(title_map[path], url, f"联合早报{path} RSS", items)
        cache_set(cache_key, rss)
        return rss, 200
    except Exception as e:
        logger.error(f"[Zaobao/{path}] 抓取失败: {e}")
        return f"抓取失败: {e}", 502

# ============ Twitter 代理（Nitter 池） ============
def proxy_twitter(username):
    """通过 Nitter 代理 Twitter RSS（Nitter 实例目前大多不可用）"""
    cache_key = f"twitter:{username}"
    cached = cache_get(cache_key)
    if cached:
        return cached, 200
    for instance in NITTER_POOL:
        try:
            url = f"{instance}/{username}/rss"
            logger.info(f"[Twitter] 尝试 {url}")
            resp = fetch(url, timeout=15, max_attempts=2)
            if is_valid_rss_content(resp.text):
                cache_set(cache_key, resp.text)
                return resp.text, 200
        except Exception as e:
            logger.warning(f"[Twitter] {instance}/{username} 失败: {e}")
            continue
    return "所有 Nitter 实例均不可用", 502

# ============ HTTP 服务器 ============
class RSSProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

    def _send(self, code, body, content_type="application/rss+xml; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body.encode() if isinstance(body, str) else body)

    def do_GET(self):
        # 修复 2：解析 path 和 query string
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = parsed.query  # 暂未使用，但可保留

        # 健康检查
        if path == "/health":
            self._send(200, json.dumps({"status": "ok", "cache_size": len(_cache)}), "application/json")
            return

        # 修复 9：新增上游探测端点
        if path == "/health/upstream":
            results = {}
            for name, url in RSS_DIRECT.items():
                try:
                    resp = requests.head(url, timeout=5, allow_redirects=True)
                    results[name] = {"status": resp.status_code, "ok": resp.status_code < 400}
                except Exception as e:
                    results[name] = {"status": "error", "ok": False, "error": str(e)}
            # 也探测 Nitter
            nitter_status = []
            for inst in NITTER_POOL:
                try:
                    resp = requests.get(inst, timeout=5)
                    nitter_status.append({"instance": inst, "status": resp.status_code, "ok": resp.status_code < 400})
                except Exception as e:
                    nitter_status.append({"instance": inst, "status": "error", "ok": False, "error": str(e)})
            self._send(200, json.dumps({"direct_rss": results, "nitter": nitter_status}), "application/json")
            return

        if path == "" or path == "/":
            routes = list(RSS_DIRECT.keys()) + ["ntdtv", "zaobao/realtime", "zaobao/znews", "twitter/:username"]
            self._send(200, json.dumps({"service": "自建 RSS 代理", "routes": routes}), "application/json")
            return

        # 路由匹配
        if path.startswith("/ntdtv/instant-news") or path == "/ntdtv":
            body, code = scrape_ntdtv()
            self._send(code, body)
            return

        # epochtimes 不再单独处理，走直接 RSS 代理（已在 RSS_DIRECT 中）
        # 如果直接访问 /epochtimes 或 /epochtimes/gb，我们重定向到原始 RSS
        if path.startswith("/epochtimes/gb") or path == "/epochtimes":
            # 返回 301 重定向到原始 RSS，让客户端直接访问
            self.send_response(302)
            self.send_header("Location", "https://feed.theepochtimes.com/china/feed")
            self.end_headers()
            return

        if path.startswith("/zaobao/realtime"):
            body, code = scrape_zaobao("realtime")
            self._send(code, body)
            return
        if path.startswith("/zaobao/znews"):
            body, code = scrape_zaobao("znews")
            self._send(code, body)
            return

        # Twitter: 兼容 /twitter/user/username 和 /twitter/username
        if path.startswith("/twitter/user/"):
            username = path.split("/")[-1]
            body, code = proxy_twitter(username)
            self._send(code, body)
            return
        if path.startswith("/twitter/"):
            username = path.split("/")[-1]
            body, code = proxy_twitter(username)
            self._send(code, body)
            return

        # 直接 RSS 代理（如 /bbc, /dw...）
        name = path.lstrip("/")
        if name in RSS_DIRECT:
            body, code = proxy_direct_rss(name)
            self._send(code, body)
            return

        self._send(404, json.dumps({"error": "未知路由", "path": path}), "application/json")

def main():
    parser = argparse.ArgumentParser(description="自建 RSS 代理")
    parser.add_argument("--port", type=int, default=1200, help="监听端口")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), RSSProxyHandler)
    logger.info(f"🚀 自建 RSS 代理已启动: http://{args.host}:{args.port}")
    logger.info(f"   直接 RSS: {len(RSS_DIRECT)} 个源")
    logger.info(f"   HTML 抓取: NTD, Zaobao")
    logger.info(f"   Twitter: {len(NITTER_POOL)} 个 Nitter 实例")
    logger.info(f"   缓存 TTL: {CACHE_TTL}s, 最大条目: {CACHE_MAX_SIZE}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止")

if __name__ == "__main__":
    main()
