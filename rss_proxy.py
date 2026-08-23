#!/usr/bin/env python3
# rss_proxy.py - 自建 RSS 代理（最终稳定版 v2）
# 启动: HTTP_PROXY=http://your-proxy:port python rss_proxy.py --port 1200
# 环境变量:
#   HTTP_PROXY / HTTPS_PROXY  - 上游代理（解决出口 IP 被封）
#   RSSHUB_URLS               - 逗号分隔的 RSSHub 后端列表（覆盖内置列表）
#   NITTER_URLS               - 逗号分隔的 Nitter 实例列表（覆盖内置列表）

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
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from xml.sax.saxutils import escape as xml_escape
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('rss-proxy')

# ===================== 配置常量 =====================
DEFAULT_TIMEOUT = 25
DEFAULT_MAX_ATTEMPTS = 3
CACHE_TTL = 900          # 缓存 15 分钟
CACHE_MAX_SIZE = 200
TWITTER_RACE_TIMEOUT = 20  # Twitter 竞赛最长等待（crawler 读超时 25s，留缓冲）

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/132.0.0.0 Safari/537.36",
]

# ===================== 上游代理（解决 IP 被封） =====================
PROXY = os.environ.get("HTTP_PROXY") or os.environ.get("HTTPS_PROXY")
PROXIES = {"http": PROXY, "https": PROXY} if PROXY else None
if PROXY:
    logger.info(f"[Proxy] 已配置上游代理: {PROXY}")
else:
    logger.warning(
        "⚠️  未配置上游代理 (HTTP_PROXY)，若出口 IP 被封，抓取将失败"
    )

# ===================== RSSHub 后端（非 Twitter 路由使用） =====================
ENV_RSSHUB_URLS = os.environ.get("RSSHUB_URLS", "").strip()
if ENV_RSSHUB_URLS:
    RSSHUB_BACKENDS = [
        url.strip()
        for url in ENV_RSSHUB_URLS.split(",")
        if url.strip()
    ]
else:
    RSSHUB_BACKENDS = [
        "https://rsshub.ktachibana.party",
        "https://rsshub.rssforever.com",
        "https://rsshub.feedio.net",
    ]

# ===================== Twitter 本地桥接（最优先） =====================
# 自建 Twitter RSS Bridge（使用 X 登录 Token），比 Nitter/RSSHub 都稳定
TWITTER_BRIDGE_URL = os.environ.get(
    "TWITTER_BRIDGE_URL", "http://localhost:3000"
).rstrip("/")

# ===================== Nitter 实例（Twitter 专用，作为备选） =====================
ENV_NITTER_URLS = os.environ.get("NITTER_URLS", "").strip()
if ENV_NITTER_URLS:
    NITTER_POOL = [
        url.strip().rstrip("/")
        for url in ENV_NITTER_URLS.split(",")
        if url.strip()
    ]
else:
    # 按近期可用性排列，社区维护的活跃实例
    NITTER_POOL = [
        "https://nitter.poast.org",
        "https://nitter.privacyredirect.com",
        "https://lightbrd.com",
        "https://nitter.space",
        "https://nitter.tiekoetter.com",
        "https://nitter.catsarch.com",
        "https://xcancel.com",
        "https://nitter.net",
    ]

# ===================== 直接 RSS 源 =====================
RSS_DIRECT = {
    "bbc": "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml",
    "dw": "https://rss.dw.com/rdf/rss-chi-all",
    "rfi": "https://www.rfi.fr/cn/general/rss",
    "nytimes": "https://cn.nytimes.com/rss/news.xml",
    "brookings": "https://www.brookings.edu/feed/?topic=china",
    "freedomhouse": "https://freedomhouse.org/rss.xml",
    "aspistrategist": "https://www.aspistrategist.org.au/feed/",
    "hrw": "https://www.hrw.org/rss/news",
    "amnesty": "https://www.amnesty.org/en/feed/",
    "fdd": "https://www.fdd.org/feed/",
    "chinapower": "https://chinapower.csis.org/feed/",
    "carnegieendowment": "https://carnegieendowment.org/rss",
    "epochtimes": "https://feed.theepochtimes.com/china/feed",
}

# ===================== 线程安全缓存 =====================
_cache = OrderedDict()
_cache_lock = threading.Lock()


def cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[0] < CACHE_TTL:
            _cache_move_to_end(key)
            return entry[1]
    return None


def cache_set(key, content):
    with _cache_lock:
        _cache[key] = (time.time(), content)
        _cache_move_to_end(key)
        if len(_cache) > CACHE_MAX_SIZE:
            _cache.popitem(last=False)


def _cache_move_to_end(key):
    """Python 3.2+ OrderedDict.move_to_end 的兼容封装"""
    try:
        _cache.move_to_end(key)
    except AttributeError:
        # Python < 3.2 fallback
        val = _cache.pop(key)
        _cache[key] = val


# ===================== HTTP 工具 =====================
def fetch(url, timeout=DEFAULT_TIMEOUT, max_attempts=DEFAULT_MAX_ATTEMPTS):
    """统一请求入口，自动走上游代理"""
    headers = {"User-Agent": random.choice(UA_LIST)}
    for attempt in range(max_attempts):
        try:
            resp = requests.get(
                url,
                headers=headers,
                timeout=timeout,
                proxies=PROXIES,
            )
            resp.raise_for_status()
            return resp
        except Exception as e:
            if attempt == max_attempts - 1:
                raise
            time.sleep(2 ** attempt)


def is_valid_rss_content(text: str) -> bool:
    text = text.strip()
    if not text.startswith("<?xml"):
        return False
    return "<rss" in text or "<feed" in text


def build_rss(title, link, desc, items):
    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '<channel>\n'
    )
    xml += f"<title>{xml_escape(title)}</title>\n"
    xml += f"<link>{xml_escape(link)}</link>\n"
    xml += f"<description>{xml_escape(desc)}</description>\n"
    xml += f"<lastBuildDate>{now}</lastBuildDate>\n"
    for item in items:
        pub = item.get("pubDate", now)
        xml += "<item>\n"
        xml += f'<title>{xml_escape(item["title"])}</title>\n'
        xml += f'<link>{xml_escape(item["link"])}</link>\n'
        xml += f'<description>{xml_escape(item.get("description", ""))}</description>\n'
        xml += f"<pubDate>{pub}</pubDate>\n"
        xml += f'<guid>{xml_escape(item.get("link", item["title"]))}</guid>\n'
        xml += "</item>\n"
    xml += "</channel>\n</rss>"
    return xml


# ===================== 直接 RSS 代理 =====================
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
            return "上游返回内容无效", 502
        cache_set(f"rss:{name}", resp.text)
        return resp.text, 200
    except Exception as e:
        logger.error(f"[{name}] 代理失败: {e}")
        return f"上游 RSS 不可用: {e}", 502


# ===================== HTML 抓取（NTD / 早报） =====================
def _extract_articles_from_elements(elements, base_url, max_items=30):
    items = []
    for el in elements[:max_items]:
        if el.name == "a":
            a = el
        else:
            a = (
                el.select_one("h2 a, h3 a, .title a, .headline a")
                or el.find("a")
            )
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
        resp = fetch(
            "https://www.ntdtv.com/gb/instant-news.html",
            timeout=DEFAULT_TIMEOUT,
        )
        soup = BeautifulSoup(resp.text, "html.parser")
        selectors = [
            ".post-list .post-item",
            ".list .item",
            ".news-item",
            "article",
            ".article-list .article",
        ]
        elements = []
        for sel in selectors:
            elements = soup.select(sel)
            if elements:
                break
        if not elements:
            elements = soup.select("h2 a, h3 a, .title a")[:30]
        items = _extract_articles_from_elements(
            elements, "https://www.ntdtv.com"
        )
        if not items:
            logger.warning("[NTDTV] 抓取到 0 条文章")
        else:
            logger.info(f"[NTDTV] 抓取到 {len(items)} 条文章")
        rss = build_rss(
            "NTDTV 即时新闻",
            "https://www.ntdtv.com/gb/instant-news.html",
            "NTDTV 即时 RSS",
            items,
        )
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
    url_map = {
        "realtime": "https://www.zaobao.com/realtime",
        "znews": "https://www.zaobao.com/news/china",
    }
    base_url = url_map.get(path)
    if not base_url:
        return "未知路径", 404
    try:
        resp = fetch(base_url, timeout=DEFAULT_TIMEOUT)
        soup = BeautifulSoup(resp.text, "html.parser")
        selectors = [
            "div[data-article-id]",
            ".article-list article",
            ".list .item",
            "article",
        ]
        elements = []
        for sel in selectors:
            elements = soup.select(sel)
            if elements:
                break
        if not elements:
            elements = soup.select("h2 a, h3 a")[:30]
        items = _extract_articles_from_elements(
            elements, "https://www.zaobao.com"
        )
        if not items:
            logger.warning(f"[Zaobao/{path}] 抓取到 0 条文章")
        else:
            logger.info(f"[Zaobao/{path}] 抓取到 {len(items)} 条文章")
        title_map = {
            "realtime": "联合早报 即时新闻",
            "znews": "联合早报 中国新闻",
        }
        rss = build_rss(
            title_map[path], base_url, f"联合早报{path} RSS", items
        )
        cache_set(cache_key, rss)
        return rss, 200
    except Exception as e:
        logger.error(f"[Zaobao/{path}] 抓取失败: {e}")
        return f"抓取失败: {e}", 502


def _try_local_bridge(username):
    """尝试从本地 Twitter Bridge 获取 RSS"""
    url = f"{TWITTER_BRIDGE_URL}/twitter/user/{username}"
    try:
        resp = requests.get(url, timeout=30, proxies=PROXIES)
        if resp.status_code == 200 and is_valid_rss_content(resp.text):
            return resp.text
    except Exception:
        pass
    return None


# ===================== Twitter 代理（Nitter 多实例竞赛） =====================
# RSSHub 的 Twitter 路由底层依赖 Nitter，公共 Nitter 大面积失效导致 RSSHub
# 的 Twitter 路由普遍 503。因此直接走 Nitter 多实例竞赛，哪个先返回就用哪个。


def _try_nitter_instance(instance_url, username):
    """尝试从单个 Nitter 实例获取 RSS"""
    url = f"{instance_url}/{username}/rss"
    try:
        resp = requests.get(
            url,
            headers={"User-Agent": random.choice(UA_LIST)},
            timeout=12,
            proxies=PROXIES,
        )
        if resp.status_code == 200 and is_valid_rss_content(resp.text):
            return resp.text
    except Exception:
        pass
    return None


def _try_rsshub_instance(backend_url, username):
    """尝试从单个 RSSHub 后端获取 Twitter RSS"""
    url = f"{backend_url}/twitter/user/{username}"
    try:
        resp = fetch(url, timeout=12, max_attempts=2)
        if is_valid_rss_content(resp.text):
            return resp.text
    except Exception:
        pass
    return None


def proxy_twitter(username):
    cache_key = f"twitter:{username}"
    cached = cache_get(cache_key)
    if cached:
        return cached, 200

    # 策略：优先本地桥接（X Token），然后 Nitter + RSSHub 竞赛
    # 第一步：尝试本地 Twitter Bridge（最快、最稳定）
    local_result = _try_local_bridge(username)
    if local_result:
        logger.info(f"[Twitter] @{username} 通过本地桥接获取成功")
        cache_set(cache_key, local_result)
        return local_result, 200

    # 第二步：如果本地桥接不可用，走 Nitter + RSSHub 竞赛
    logger.info(f"[Twitter] @{username} 本地桥接不可用，回退到 Nitter/RSSHub 竞赛")

    all_targets = []

    # Nitter 实例
    for inst in NITTER_POOL:
        all_targets.append(("nitter", inst, username))

    # RSSHub 后端（作为备选）
    for backend in RSSHUB_BACKENDS:
        all_targets.append(("rsshub", backend, username))

    with ThreadPoolExecutor(max_workers=len(all_targets)) as executor:
        futures = {}
        for kind, target, uname in all_targets:
            if kind == "nitter":
                fut = executor.submit(_try_nitter_instance, target, uname)
            else:
                fut = executor.submit(_try_rsshub_instance, target, uname)
            futures[fut] = (kind, target)

        # 持续等待直到出现成功结果或全部完成（最多 TWITTER_RACE_TIMEOUT 秒）
        # 注意：不能用 FIRST_COMPLETED 只等第一个完成——最快的实例往往是
        # 死实例（连接拒绝最快），必须继续等慢但能用的实例
        pending = set(futures)
        deadline = time.time() + TWITTER_RACE_TIMEOUT
        while pending and time.time() < deadline:
            done, pending = wait(
                pending,
                timeout=max(0.1, deadline - time.time()),
                return_when=FIRST_COMPLETED,
            )
            for future in done:
                result = future.result()
                if result:
                    kind, target = futures[future]
                    logger.info(
                        f"[Twitter] @{username} 通过 {kind}:{target} 获取成功"
                    )
                    cache_set(cache_key, result)
                    return result, 200

    logger.error(f"[Twitter] @{username} 所有实例均失败")
    return "Twitter 上游不可用（所有 Nitter/RSSHub 实例均失败）", 502


# ===================== HTTP 服务器 =====================
class RSSProxyHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

    def _send(self, code, body, content_type=None):
        if isinstance(body, bytes):
            body_str = body.decode("utf-8", errors="replace")
        else:
            body_str = str(body)

        if content_type is None:
            if code >= 400 or not body_str.strip().startswith("<?xml"):
                content_type = "text/plain; charset=utf-8"
            else:
                content_type = "application/rss+xml; charset=utf-8"

        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body_str.encode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # ---- 健康检查 ----
        if path == "/health":
            self._send(
                200,
                json.dumps(
                    {
                        "status": "ok",
                        "cache_size": len(_cache),
                        "proxy": PROXY,
                        "nitter_pool": NITTER_POOL,
                        "rsshub_backends": RSSHUB_BACKENDS,
                    }
                ),
                "application/json",
            )
            return

        # ---- 首页 ----
        if path == "" or path == "/":
            routes = (
                list(RSS_DIRECT.keys())
                + ["ntdtv", "zaobao/realtime", "zaobao/znews"]
                + ["twitter/:username"]
            )
            self._send(
                200,
                json.dumps({"service": "自建 RSS 代理", "routes": routes}),
                "application/json",
            )
            return

        # ---- NTD ----
        if path.startswith("/ntdtv/instant-news") or path == "/ntdtv":
            body, code = scrape_ntdtv()
            self._send(code, body)
            return

        # ---- Zaobao ----
        if path.startswith("/zaobao/realtime"):
            body, code = scrape_zaobao("realtime")
            self._send(code, body)
            return
        if path.startswith("/zaobao/znews"):
            body, code = scrape_zaobao("znews")
            self._send(code, body)
            return

        # ---- Twitter ----
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

        # ---- 直接 RSS 代理 ----
        parts = path.lstrip("/").split("/")
        if parts and parts[0] in RSS_DIRECT:
            body, code = proxy_direct_rss(parts[0])
            self._send(code, body)
            return

        # ---- 泛化 RSSHub 转发（兜底） ----
        if parts and RSSHUB_BACKENDS:
            for backend in RSSHUB_BACKENDS:
                proxy_url = backend + path
                cache_key = f"rsshub:{path}"
                cached = cache_get(cache_key)
                if cached:
                    self._send(200, cached)
                    return
                try:
                    resp = requests.get(
                        proxy_url,
                        headers={"User-Agent": random.choice(UA_LIST)},
                        timeout=15,
                        proxies=PROXIES,
                    )
                    if resp.status_code == 200 and is_valid_rss_content(
                        resp.text
                    ):
                        cache_set(cache_key, resp.text)
                        self._send(200, resp.text)
                        return
                except Exception:
                    continue

        # ---- 404 ----
        self._send(
            404,
            json.dumps({"error": "未知路由", "path": path}),
            "application/json",
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=1200)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    # 必须用 ThreadingHTTPServer：单线程 HTTPServer 会让一个慢请求阻塞所有请求
    server = ThreadingHTTPServer((args.host, args.port), RSSProxyHandler)
    logger.info(f"🚀 RSS 代理已启动: http://{args.host}:{args.port}")
    logger.info(f"  直接 RSS: {len(RSS_DIRECT)} 个源")
    logger.info(f"  Twitter 本地桥接: {TWITTER_BRIDGE_URL}")
    logger.info(f"  Nitter 实例: {len(NITTER_POOL)} 个")
    logger.info(f"  RSSHub 后端: {len(RSSHUB_BACKENDS)} 个")
    if PROXY:
        logger.info(f"  🔒 上游代理: {PROXY}")
    else:
        logger.warning("  ⚠️  未配置上游代理，受封 IP 的源将失败")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止")


if __name__ == "__main__":
    main()
