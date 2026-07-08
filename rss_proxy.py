#!/usr/bin/env python3
# rss_proxy.py - 自建 RSS 代理（最终稳定版，已全部修复）
# 启动: python rss_proxy.py --port 1200
# 可选: RSSHUB_URL=http://localhost:1201 指定本地 RSSHub 后端

import argparse
import json
import time
import random
import logging
import sys
import threading
import os
from collections import OrderedDict
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger('rss-proxy')

DEFAULT_TIMEOUT = 20
DEFAULT_MAX_ATTEMPTS = 3
CACHE_TTL = 900
CACHE_MAX_SIZE = 200

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132.0.0.0 Safari/537.36",
]

# RSSHub 后端（支持环境变量指定本地）
LOCAL_RSSHUB = os.environ.get("RSSHUB_URL", "").strip()
RSSHUB_BACKENDS = [
    "https://rsshub.ktachibana.party",
    "https://rsshub.slarker.net",
    "https://rsshub.liumingye.cn",
]
if LOCAL_RSSHUB:
    RSSHUB_BACKENDS.insert(0, LOCAL_RSSHUB)
    logger.info(f"[Twitter] 已添加本地 RSSHub: {LOCAL_RSSHUB}")

NITTER_POOL_FAST = ["https://nitter.net", "https://xcancel.com"]

# ============ 线程安全缓存 ============
_cache = OrderedDict()
_cache_lock = threading.Lock()

def cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[0] < CACHE_TTL:
            _cache.move_to_end(key)
            return entry[1]
        return None

def cache_set(key, content):
    with _cache_lock:
        _cache[key] = (time.time(), content)
        _cache.move_to_end(key)
        if len(_cache) > CACHE_MAX_SIZE:
            _cache.popitem(last=False)

# ============ HTTP 工具 ============
def fetch(url, timeout=DEFAULT_TIMEOUT, max_attempts=DEFAULT_MAX_ATTEMPTS):
    headers = {"User-Agent": random.choice(UA_LIST)}
    for attempt in range(max_attempts):
        try:
            resp = requests.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            time.sleep(2 ** attempt)

def is_valid_rss_content(text: str) -> bool:
    text = text.strip()
    if not text.startswith('<?xml'):
        return False
    return '<rss' in text or '<feed' in text

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

# ============ 直接 RSS 代理 ============
RSS_DIRECT = {
    "bbc":        "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
    "dw":         "https://rss.dw.com/rdf/rss-chi-all",
    "rfi":        "https://www.rfi.fr/cn/general/rss",
    "nytimes":    "https://cn.nytimes.com/rss/news.xml",
    "brookings":  "https://www.brookings.edu/feed/?topic=china",
    "freedomhouse": "https://freedomhouse.org/rss.xml",
    "aspi":       "https://www.aspistrategist.org.au/feed/",
    "hrw":        "https://www.hrw.org/rss/news",
    "amnesty":    "https://www.amnesty.org/en/feed/",
    "fdd":        "https://www.fdd.org/feed/",
    "chinapower": "https://chinapower.csis.org/feed/",
    "carnegie":   "https://carnegieendowment.org/rss",
    "epochtimes": "https://feed.theepochtimes.com/china/feed",
}

def proxy_direct_rss(name):
    url = RSS_DIRECT.get(name)
    if not url:
        return None, 404
    cached = cache_get(f"rss:{name}")
    if cached:
        return cached, 200
    try:
        resp = fetch(url, timeout=DEFAULT_TIMEOUT)
        if not is_valid_rss_content(resp.text):
            logger.warning(f"[{name}] 返回内容无效，URL: {url}")
            return f"上游返回内容无效", 502
        cache_set(f"rss:{name}", resp.text)
        return resp.text, 200
    except Exception as e:
        logger.error(f"[{name}] 代理失败: {e}")
        return f"上游 RSS 不可用: {e}", 502

# ============ HTML 抓取 ============
def _extract_articles_from_elements(elements, base_url, max_items=30):
    items = []
    for el in elements[:max_items]:
        if el.name == 'a':
            a = el
        else:
            a = el.select_one("h2 a, h3 a, .title a, .headline a") or el.find("a")
        if not a:
            continue
        title = a.get_text(strip=True)
        if not title or len(title) < 5:
            continue
        link = a.get("href", "")
        if link and not link.startswith("http"):
            link = base_url.rstrip("/") + link
        desc_el = el.select_one(".excerpt, .summary")
        desc = desc_el.get_text(strip=True) if desc_el else title
        items.append({"title": title, "link": link, "description": desc})
    return items

def scrape_ntdtv():
    cached = cache_get("scrape:ntdtv")
    if cached:
        return cached, 200
    try:
        resp = fetch("https://www.ntdtv.com/gb/instant-news.html", timeout=DEFAULT_TIMEOUT)
        soup = BeautifulSoup(resp.text, "html.parser")
        selectors = [".post-list .post-item", ".list .item", ".news-item", "article", ".article-list .article"]
        elements = []
        for sel in selectors:
            elements = soup.select(sel)
            if elements:
                break
        if not elements:
            elements = soup.select("h2 a, h3 a, .title a")[:30]
        items = _extract_articles_from_elements(elements, "https://www.ntdtv.com")
        if not items:
            logger.warning("[NTDTV] 抓取到 0 条文章")
        else:
            logger.info(f"[NTDTV] 抓取到 {len(items)} 条文章")
        rss = build_rss("NTDTV 即时新闻", "https://www.ntdtv.com/gb/instant-news.html", "NTDTV 即时 RSS", items)
        cache_set("scrape:ntdtv", rss)
        return rss, 200
    except Exception as e:
        logger.error(f"[NTDTV] 抓取失败: {e}")
        return f"抓取失败: {e}", 502

def scrape_zaobao(path):
    cache_key = f"scrape:zaobao:{path}"
    cached = cache_get(cache_key)
    if cached:
        return cached, 200
    url_map = {"realtime": "https://www.zaobao.com/realtime", "znews": "https://www.zaobao.com/news/china"}
    base_url = url_map.get(path)
    if not base_url:
        return "未知路径", 404
    try:
        resp = fetch(base_url, timeout=DEFAULT_TIMEOUT)
        soup = BeautifulSoup(resp.text, "html.parser")
        selectors = ["div[data-article-id]", ".article-list article", ".list .item", "article"]
        elements = []
        for sel in selectors:
            elements = soup.select(sel)
            if elements:
                break
        if not elements:
            elements = soup.select("h2 a, h3 a")[:30]
        items = _extract_articles_from_elements(elements, "https://www.zaobao.com")
        if not items:
            logger.warning(f"[Zaobao/{path}] 抓取到 0 条文章")
        else:
            logger.info(f"[Zaobao/{path}] 抓取到 {len(items)} 条文章")
        title_map = {"realtime": "联合早报 即时新闻", "znews": "联合早报 中国新闻"}
        rss = build_rss(title_map[path], base_url, f"联合早报{path} RSS", items)
        cache_set(cache_key, rss)
        return rss, 200
    except Exception as e:
        logger.error(f"[Zaobao/{path}] 抓取失败: {e}")
        return f"抓取失败: {e}", 502

# ============ Twitter 代理 ============
def _try_fetch_twitter_from_backend(backend, username):
    url = f"{backend}/twitter/user/{username}"
    try:
        # 调整为 12 秒超时，给 RSSHub 调用 Twitter API 留足时间
        resp = fetch(url, timeout=12, max_attempts=2)
        if is_valid_rss_content(resp.text):
            return resp.text
    except Exception as e:
        logger.debug(f"[Twitter] {backend} 失败: {e}")
    return None

def proxy_twitter(username):
    cache_key = f"twitter:{username}"
    cached = cache_get(cache_key)
    if cached:
        return cached, 200

    backends = RSSHUB_BACKENDS
    with ThreadPoolExecutor(max_workers=len(backends)) as executor:
        futures = {executor.submit(_try_fetch_twitter_from_backend, backend, username): backend for backend in backends}
        done, _ = wait(futures, timeout=5, return_when=FIRST_COMPLETED)
        for future in done:
            result = future.result()
            if result:
                cache_set(cache_key, result)
                return result, 200

    try:
        inst = NITTER_POOL_FAST[0]
        url = f"{inst}/{username}/rss"
        resp = requests.get(url, headers={"User-Agent": random.choice(UA_LIST)}, timeout=4)
        if resp.status_code == 200 and is_valid_rss_content(resp.text):
            cache_set(cache_key, resp.text)
            return resp.text, 200
    except Exception:
        pass

    return "Twitter 上游不可用", 502

# ============ HTTP 服务器 ============
class RSSProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

    def _send(self, code, body, content_type=None):
        if isinstance(body, bytes):
            body_str = body.decode('utf-8', errors='replace')
        else:
            body_str = str(body)

        if content_type is None:
            if code >= 400 or not body_str.strip().startswith('<?xml'):
                content_type = "text/plain; charset=utf-8"
            else:
                content_type = "application/rss+xml; charset=utf-8"

        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body_str.encode('utf-8'))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path == "/health":
            self._send(200, json.dumps({"status": "ok", "cache_size": len(_cache)}), "application/json")
            return

        if path == "/health/upstream":
            results = {"direct_rss": {}, "nitter": []}
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {executor.submit(requests.head, url, timeout=3, allow_redirects=True): name for name, url in RSS_DIRECT.items()}
                done, _ = wait(futures, timeout=4)
                for future in done:
                    name = futures[future]
                    try:
                        resp = future.result()
                        results["direct_rss"][name] = {"status": resp.status_code, "ok": resp.status_code < 400}
                    except Exception as e:
                        results["direct_rss"][name] = {"status": "error", "ok": False, "error": str(e)}
                for future in [f for f in futures if f not in done]:
                    name = futures[future]
                    results["direct_rss"][name] = {"status": "timeout", "ok": False}

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {executor.submit(requests.get, inst, timeout=3): inst for inst in NITTER_POOL_FAST}
                done, _ = wait(futures, timeout=4)
                for future in done:
                    inst = futures[future]
                    try:
                        resp = future.result()
                        results["nitter"].append({"instance": inst, "status": resp.status_code, "ok": resp.status_code < 400})
                    except Exception as e:
                        results["nitter"].append({"instance": inst, "status": "error", "ok": False, "error": str(e)})
                for future in [f for f in futures if f not in done]:
                    inst = futures[future]
                    results["nitter"].append({"instance": inst, "status": "timeout", "ok": False})

            self._send(200, json.dumps(results), "application/json")
            return

        if path == "" or path == "/":
            routes = list(RSS_DIRECT.keys()) + ["ntdtv", "zaobao/realtime", "zaobao/znews", "twitter/:username"]
            self._send(200, json.dumps({"service": "自建 RSS 代理", "routes": routes}), "application/json")
            return

        if path.startswith("/ntdtv/instant-news") or path == "/ntdtv":
            body, code = scrape_ntdtv()
            self._send(code, body)
            return

        if path.startswith("/epochtimes/gb") or path == "/epochtimes":
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

        name = path.lstrip("/")
        if name in RSS_DIRECT:
            body, code = proxy_direct_rss(name)
            self._send(code, body)
            return

        self._send(404, json.dumps({"error": "未知路由", "path": path}), "application/json")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=1200)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    server = HTTPServer((args.host, args.port), RSSProxyHandler)
    logger.info(f"🚀 RSS 代理已启动: http://{args.host}:{args.port}")
    logger.info(f"   直接 RSS: {len(RSS_DIRECT)} 个源")
    logger.info(f"   Twitter RSSHub 后端: {len(RSSHUB_BACKENDS)} 个 (本地: {LOCAL_RSSHUB or '无'})")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止")

if __name__ == "__main__":
    main()
