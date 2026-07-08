#!/usr/bin/env python3
# rss_proxy.py - 自建 RSS 代理，替换不稳定的公共 RSSHub/Nitter
# 启动: python rss_proxy.py --port 1200
# crawler.py 中把 rsshub.app 替换为 http://localhost:1200 即可

import argparse
import json
import re
import time
import random
import hashlib
import logging
import sys
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
CACHE_TTL = 900  # 15 分钟
UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36",
]

# Nitter 实例池（按优先级排序）
NITTER_POOL = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nitter.tiekoetter.com",
    "https://xcancel.com",
]

# ============ 缓存 ============
_cache = {}

def cache_get(key):
    entry = _cache.get(key)
    if entry and time.time() - entry[0] < CACHE_TTL:
        return entry[1]
    return None

def cache_set(key, content):
    _cache[key] = (time.time(), content)
    # 限制缓存大小
    if len(_cache) > 200:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]

# ============ HTTP 工具 ============
def fetch(url, timeout=25, retries=3):
    """带重试的 HTTP GET"""
    headers = {"User-Agent": random.choice(UA_LIST)}
    for i in range(retries):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if i == retries - 1:
                raise
            time.sleep(1 * (i + 1))

def build_rss(title, link, desc, items):
    """构建 RSS 2.0 XML"""
    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    xml = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml += '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
    xml += '<channel>\n'
    xml += f'<title>{xml_escape(title)}</title>\n'
    xml += f'<link>{xml_escape(link)}</link>\n'
    xml += f'<description>{xml_escape(desc)}</description>\n'
    xml += f'<lastBuildDate>{now}</lastBuildDate>\n'
    for item in items:
        pub = item.get("pubDate", now)
        xml += '<item>\n'
        xml += f'<title>{xml_escape(item["title"])}</title>\n'
        xml += f'<link>{xml_escape(item["link"])}</link>\n'
        xml += f'<description>{xml_escape(item.get("description", ""))}</description>\n'
        xml += f'<pubDate>{pub}</pubDate>\n'
        xml += f'<guid>{xml_escape(item.get("link", item["title"]))}</guid>\n'
        xml += '</item>\n'
    xml += '</channel>\n</rss>'
    return xml

# ============ 直接 RSS 代理 ============
RSS_DIRECT = {
    "bbc":        "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
    "dw":         "https://rss.dw.com/rdf/rss-chi-all",
    "rfi":        "https://www.rfi.fr/cn/general/rss",
    "nytimes":    "https://cn.nytimes.com/rss/news.xml",
    "uscc":       "https://www.uscc.gov/rss.xml",
    "brookings":  "https://www.brookings.edu/feed/?topic=china",
    "freedomhouse": "https://freedomhouse.org/rss.xml",
    "aspi":       "https://www.aspistrategist.org.au/feed/",
    "hrw":        "https://www.hrw.org/rss/news",
    "amnesty":    "https://www.amnesty.org/en/feed/",
    "fdd":        "https://www.fdd.org/feed/",
    "chinapower": "https://chinapower.csis.org/feed/",
    "carnegie":   "https://carnegieendowment.org/rss",
    "chathamhouse": "https://www.chathamhouse.org/rss",   # 修复：移除 -feeds
    "epochtimes": "https://feed.theepochtimes.com/china/feed",
}

def proxy_direct_rss(name):
    """代理直接 RSS 源"""
    url = RSS_DIRECT.get(name)
    if not url:
        return None, 404
    cached = cache_get(f"rss:{name}")
    if cached:
        return cached, 200
    try:
        resp = fetch(url)
        cache_set(f"rss:{name}", resp.text)
        return resp.text, 200
    except Exception as e:
        logger.error(f"[{name}] 代理失败: {e}")
        return f"上游 RSS 不可用: {e}", 502

# ============ HTML 抓取 -> RSS ============
def scrape_ntdtv():
    """抓取 NTD 即时新闻"""
    cached = cache_get("scrape:ntdtv")
    if cached:
        return cached, 200
    try:
        resp = fetch("https://www.ntdtv.com/gb/instant-news.html")
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for el in soup.select(".post-list .post-item, .list .item, article, .news-item")[:30]:
            a = el.select_one("h2 a, h3 a, .title a")
            if not a:
                a = el.find("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a.get("href", "")
            if link and not link.startswith("http"):
                link = "https://www.ntdtv.com" + link
            desc_el = el.select_one(".excerpt, .summary, p")
            desc = desc_el.get_text(strip=True) if desc_el else title
            if title and link:
                items.append({"title": title, "link": link, "description": desc})
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
    url_map = {
        "realtime": "https://www.zaobao.com/realtime",
        "znews": "https://www.zaobao.com/news/china",
    }
    url = url_map.get(path)
    if not url:
        return "未知路径", 404
    try:
        resp = fetch(url)
        soup = BeautifulSoup(resp.text, "html.parser")
        items = []
        for el in soup.select("div[data-article-id], .article-list article, article")[:30]:
            a = el.select_one("h2 a, h3 a, .headline a")
            if not a:
                a = el.find("a")
            if not a:
                continue
            title = a.get_text(strip=True)
            link = a.get("href", "")
            if link and not link.startswith("http"):
                link = "https://www.zaobao.com" + link
            desc_el = el.select_one(".excerpt, .summary, p")
            desc = desc_el.get_text(strip=True) if desc_el else title
            if title and link:
                items.append({"title": title, "link": link, "description": desc})
        title_map = {"realtime": "联合早报 即时新闻", "znews": "联合早报 中国新闻"}
        rss = build_rss(title_map[path], url, f"联合早报{path} RSS", items)
        cache_set(cache_key, rss)
        return rss, 200
    except Exception as e:
        logger.error(f"[Zaobao/{path}] 抓取失败: {e}")
        return f"抓取失败: {e}", 502

# ============ Twitter 代理（Nitter） ============
def proxy_twitter(username):
    """通过 Nitter 代理 Twitter RSS"""
    cache_key = f"twitter:{username}"
    cached = cache_get(cache_key)
    if cached:
        return cached, 200

    for instance in NITTER_POOL:
        try:
            url = f"{instance}/{username}/rss"
            logger.info(f"[Twitter] 尝试 {url}")
            resp = fetch(url, timeout=15, retries=2)
            if resp.text and "<rss" in resp.text and "<item>" in resp.text:
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
        path = self.path.rstrip("/")

        # 健康检查
        if path == "/health":
            self._send(200, json.dumps({"status": "ok", "cache_size": len(_cache)}), "application/json")
            return

        # 首页
        if path == "" or path == "/":
            routes = list(RSS_DIRECT.keys()) + ["ntdtv", "zaobao/realtime", "zaobao/znews", "twitter/:username"]
            self._send(200, json.dumps({"service": "自建 RSS 代理", "routes": routes}), "application/json")
            return

        # 直接 RSS 代理: /bbc, /dw, /rfi, ...
        name = path.lstrip("/")
        if name in RSS_DIRECT:
            body, code = proxy_direct_rss(name)
            self._send(code, body)
            return

        # NTD 即时新闻
        if name == "ntdtv":
            body, code = scrape_ntdtv()
            self._send(code, body)
            return

        # 联合早报
        if name == "zaobao/realtime":
            body, code = scrape_zaobao("realtime")
            self._send(code, body)
            return
        if name == "zaobao/znews":
            body, code = scrape_zaobao("znews")
            self._send(code, body)
            return

        # Twitter 代理: /twitter/username
        if name.startswith("twitter/"):
            username = name.split("/", 1)[1]
            body, code = proxy_twitter(username)
            self._send(code, body)
            return

        # 404
        self._send(404, json.dumps({"error": "未知路由", "path": path}), "application/json")

def main():
    parser = argparse.ArgumentParser(description="自建 RSS 代理")
    parser.add_argument("--port", type=int, default=1200, help="监听端口 (默认 1200)")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    args = parser.parse_args()

    server = HTTPServer((args.host, args.port), RSSProxyHandler)
    logger.info(f"🚀 自建 RSS 代理已启动: http://{args.host}:{args.port}")
    logger.info(f"   直接 RSS: {len(RSS_DIRECT)} 个源")
    logger.info(f"   HTML 抓取: NTD, Zaobao")
    logger.info(f"   Twitter: {len(NITTER_POOL)} 个 Nitter 实例")
    logger.info(f"   缓存 TTL: {CACHE_TTL}s")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止")

if __name__ == "__main__":
    main()
