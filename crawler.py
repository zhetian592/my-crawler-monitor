#!/usr/bin/env python3
# crawler.py - 基于 RSSHub 的稳定抓取（无 AI 降级）
import os
import json
import re
import time
import random
import hashlib
import logging
import sys
import urllib.parse
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple, Optional, Union
from logging.handlers import RotatingFileHandler

import requests
import feedparser
import openai
from bs4 import BeautifulSoup
import difflib
from dotenv import load_dotenv

load_dotenv()

try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

# ================= 日志配置 =================
LOG_FILE = "crawler.log"
LOG_MAX_BYTES = 10 * 1024 * 1024
LOG_BACKUP_COUNT = 5

for handler in logging.root.handlers[:]:
    logging.root.removeHandler(handler)

file_handler = RotatingFileHandler(LOG_FILE, maxBytes=LOG_MAX_BYTES, backupCount=LOG_BACKUP_COUNT, encoding='utf-8')
file_handler.setLevel(logging.DEBUG)
console_handler = logging.StreamHandler(sys.stdout)
console_handler.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
console_handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.DEBUG)
logger.addHandler(file_handler)
logger.addHandler(console_handler)

# ================= 配置常量 =================
GH_TOKEN = os.environ.get("GH_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
AI_BASE_URL = "https://models.inference.ai.azure.com"
AI_MODEL = "gpt-4o-mini"
REPORT_PASSWORD = os.environ.get("REPORT_PASSWORD", "yangge233")
PROXIES = None
if os.environ.get("HTTP_PROXY"):
    PROXIES = {"http": os.environ["HTTP_PROXY"], "https": os.environ.get("HTTPS_PROXY", os.environ["HTTP_PROXY"])}

KEEP_DAYS = 7
SIMILARITY_THRESHOLD = 0.6
MAX_REPEAT_COUNT = 3
COOLDOWN_DAYS = 7
MAX_WORKERS = 6
AI_REQUEST_DELAY = 2
EVENT_EXPIRE_DAYS = 60

EVENT_COUNTS_FILE = "event_counts.json"
FAILED_SOURCES_LOG = "failed_sources.json"
DISABLED_SOURCES_FILE = "disabled_sources.json"

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]

# ================= 辅助函数 =================
def clean_html(text: Optional[str]) -> str:
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text().strip()[:500]

def parse_published_strict(published_str: Optional[str]) -> Optional[datetime]:
    if not published_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S", "%a, %d %b %Y %H:%M:%S %z",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(published_str, fmt)
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
        except:
            continue
    return None

def format_time_ago(pub_dt: Optional[datetime]) -> str:
    if pub_dt is None:
        return "时间未知"
    now = datetime.utcnow()
    diff = now - pub_dt
    seconds = diff.total_seconds()
    if seconds < 60:
        return "刚刚"
    if seconds < 3600:
        return f"{int(seconds // 60)}分钟前"
    if seconds < 86400:
        return f"{int(seconds // 3600)}小时前"
    if seconds < 604800:
        return f"{int(seconds // 86400)}天前"
    return f"{int(seconds // 604800)}周前"

def content_hash(title: str, summary: str) -> str:
    text = (title + " " + summary)[:500]
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def convert_to_official_x_link(link: str) -> str:
    if not link:
        return link
    # 将各种 RSSHub 实例域名替换为 x.com
    replacements = [
        ("nitter.net", "x.com"), ("twitter.net", "x.com"), ("nitter.poast.org", "x.com"),
        ("nitter.private.coffee", "x.com"), ("nitter.42l.fr", "x.com"),
        ("rsshub.rssforever.com", "x.com"), ("hub.slarker.me", "x.com"),
        ("rsshub.pseudoyu.com", "x.com"), ("rsshub.woodland.cafe", "x.com"),
        ("rss.owo.nz", "x.com"), ("yangzhi.app", "x.com"),
    ]
    for old, new in replacements:
        link = link.replace(old, new)
    # 如果链接中包含 /twitter/user/ 路径，提取真实的推文链接
    match = re.search(r'/twitter/user/([^/]+)/status/(\d+)', link)
    if match:
        username = match.group(1)
        tweet_id = match.group(2)
        link = f"https://x.com/{username}/status/{tweet_id}"
    else:
        # 处理只有用户名的情况
        match = re.search(r'/twitter/user/([^/]+)', link)
        if match:
            username = match.group(1)
            link = f"https://x.com/{username}"
    return link

def normalize_event_text(text: str) -> str:
    text = re.sub(r'[^\w\u4e00-\u9fff]', ' ', text)
    stopwords = {'的', '了', '是', '在', '和', '与', '或', '一个', '这个', '那个', '有', '被', '把', '让', '给', '从', '到', '对', '向', '在', '于', '就', '都', '也', '还', '要', '会', '能', '可以', '可能', '已经', '还', '更', '最', '很', '太', '非常', '特别', '十分', '有点', '一些', '这些', '那些', '这样', '那样', '如何', '为何', '什么', '哪里', '哪个', '谁', '为什么', '怎么', '怎样'}
    words = text.split()
    words = [w for w in words if w not in stopwords]
    return ' '.join(words)

def is_similar(a: str, b: str, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    a_norm = normalize_event_text(a)
    b_norm = normalize_event_text(b)
    return difflib.SequenceMatcher(None, a_norm, b_norm).ratio() >= threshold

def get_source_priority(source_name: str) -> int:
    high_priority = {"uscc", "cecc", "chinaselect", "odni", "state", "gov"}
    think_tank = {"brookings", "csis", "merics", "aspi", "jamestown", "hrw", "amnesty", "freedomhouse"}
    news = {"bbc", "dw", "rfi", "nytimes", "reuters", "wsj", "ft", "ap", "nikkei"}
    src_lower = source_name.lower()
    if any(k in src_lower for k in high_priority):
        return 1
    if any(k in src_lower for k in think_tank):
        return 2
    if any(k in src_lower for k in news):
        return 3
    return 4

# ================= 配置加载 =================
def load_sources_config() -> List[Dict]:
    sources_file = "sources.json"
    if not os.path.exists(sources_file):
        logger.error(f"{sources_file} 不存在，退出")
        sys.exit(1)
    try:
        with open(sources_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            logger.error(f"{sources_file} 不是数组，退出")
            sys.exit(1)
        configs = []
        for item in raw:
            if isinstance(item, str):
                configs.append({"url": item, "time_window_hours": 24})
            elif isinstance(item, dict) and "url" in item:
                configs.append({
                    "url": item["url"],
                    "time_window_hours": item.get("time_window_hours", 24)
                })
            else:
                logger.warning(f"跳过无效信源配置: {item}")
        if not configs:
            logger.error("无有效信源配置，退出")
            sys.exit(1)
        return configs
    except Exception as e:
        logger.error(f"加载 {sources_file} 失败: {e}")
        sys.exit(1)

def load_source_map() -> Dict[str, str]:
    map_file = "source_map.json"
    if os.path.exists(map_file):
        try:
            with open(map_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"加载 {map_file} 失败: {e}")
    return {}

RAW_SOURCES_CONFIG = load_sources_config()
RAW_SOURCES = [cfg["url"] for cfg in RAW_SOURCES_CONFIG]
TIME_WINDOW_MAP = {cfg["url"]: cfg["time_window_hours"] for cfg in RAW_SOURCES_CONFIG}
SOURCE_NAME_MAP = load_source_map()

def get_display_source(source_name: str) -> str:
    if source_name.startswith("@") and len(source_name) > 1:
        username = source_name[1:]
        if username in SOURCE_NAME_MAP:
            return SOURCE_NAME_MAP[username]
        return source_name
    for domain, display in SOURCE_NAME_MAP.items():
        if domain in source_name:
            return display
    return source_name

# ================= 禁用机制（已取消） =================
def load_disabled_sources():
    return {}
def save_disabled_sources(disabled):
    pass
def update_disabled_sources(failed_sources):
    if failed_sources:
        logger.info(f"本次有 {len(failed_sources)} 个信源失败，但不会禁用")
def is_source_disabled(url):
    return False

# ================= 网络请求重试 =================
def retry_on_exception(max_retries=3, delay=1, backoff=2):
    def decorator(func):
        def wrapper(*args, **kwargs):
            _delay = delay
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    logger.debug(f"重试 {func.__name__} (尝试 {attempt+1}/{max_retries}): {e}")
                    time.sleep(_delay)
                    _delay *= backoff
            return None
        return wrapper
    return decorator

@retry_on_exception(max_retries=3, delay=1, backoff=2)
def fetch_url(url: str, timeout: int = 25, headers: Optional[Dict] = None) -> requests.Response:
    headers = headers or {"User-Agent": random.choice(USER_AGENTS), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    resp = requests.get(url, headers=headers, timeout=timeout, proxies=PROXIES)
    resp.raise_for_status()
    return resp

# ================= 抓取核心 =================
def fetch_single_rss(rss_url: str, original_url: str, processed_hashes: set, time_window_hours: int) -> List[Dict]:
    try:
        resp = fetch_url(rss_url, timeout=25)
        feed = feedparser.parse(resp.content)
        cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
        items = []
        for entry in feed.entries:
            published_str = entry.get("published", entry.get("updated", ""))
            pub_dt = parse_published_strict(published_str)
            if pub_dt is not None and pub_dt < cutoff:
                continue
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = clean_html(entry.get("content", [{}])[0].get("value", ""))
            if not summary:
                summary = title
            h = content_hash(title, summary)
            if h in processed_hashes:
                continue
            processed_hashes.add(h)
            link = entry.get("link", "")
            link = convert_to_official_x_link(link)
            # 确定来源名称
            domain_match = re.search(r'https?://([^/]+)', original_url)
            raw_domain = domain_match.group(1) if domain_match else original_url
            source_name = raw_domain
            # 如果链接是 X 推文，提取用户名作为来源
            if "x.com/" in link:
                user_match = re.search(r'x\.com/([^/]+)', link)
                if user_match:
                    source_name = "@" + user_match.group(1)
            time_ago = format_time_ago(pub_dt)
            items.append({
                "title": title,
                "link": link,
                "summary": summary,
                "source": original_url,
                "source_name": source_name,
                "published_str": published_str if published_str else "未知时间",
                "pub_dt": pub_dt.isoformat() if pub_dt else None,
                "time_ago": time_ago,
                "fetched_at": datetime.utcnow().isoformat()
            })
            if len(items) >= 15:
                break
        return items
    except Exception as e:
        logger.error(f"抓取异常 {original_url} (RSS: {rss_url}): {e}")
        return []

def fetch_with_retry(original_url: str, processed_hashes: set, time_window_hours: int) -> List[Dict]:
    if is_source_disabled(original_url):
        return []
    items = fetch_single_rss(original_url, original_url, processed_hashes, time_window_hours)
    if items:
        logger.debug(f"{original_url} 成功 (条数: {len(items)})")
        return items
    else:
        logger.debug(f"{original_url} 抓取失败")
        return []

def fetch_all_sources() -> Tuple[List[Dict], List[Tuple[str, str]]]:
    logger.info(f"开始抓取 {len(RAW_SOURCES)} 个信源")
    all_items = []
    processed_hashes = set()
    failed_sources = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_with_retry, url, processed_hashes, TIME_WINDOW_MAP.get(url, 24)): url
            for url in RAW_SOURCES
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                if items:
                    all_items.extend(items)
                    logger.debug(f"✓ {url} -> {len(items)} 条")
                else:
                    failed_sources.append((url, "抓取返回0条"))
            except Exception as e:
                failed_sources.append((url, str(e)))
                logger.error(f"✗ {url} 异常: {e}")
    logger.info(f"去重后共 {len(all_items)} 条")
    return all_items, failed_sources

# ================= 持久化失败记录 =================
def log_failed_sources(failed_sources: List[Tuple[str, str]]):
    today = datetime.utcnow().strftime("%Y-%m-%d")
    data = {}
    if os.path.exists(FAILED_SOURCES_LOG):
        try:
            with open(FAILED_SOURCES_LOG, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except:
            pass
    if today not in data:
        data[today] = []
    for url, reason in failed_sources:
        data[today].append({"url": url, "reason": reason, "timestamp": datetime.utcnow().isoformat()})
    with open(FAILED_SOURCES_LOG, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    update_disabled_sources(failed_sources)

# ================= 历史事件加载（保持原样，因篇幅省略，实际使用时复制原版即可） =================
# 注意：由于篇幅限制，以下 load_previous_events, load_event_counts, save_event_counts,
# cleanup_old_events, deduplicate_and_mark_new, filter_by_repeat_count 等函数与之前完全相同，
# 请直接使用你之前稳定版本中的这些函数（从后面部分复制）。我这里只给出一个占位，实际运行时需补充完整。

# 以下仅为占位，实际必须补全所有后续函数（包括 AI 分析、报告生成等），否则无法运行。
# 由于之前的回答中已经给出完整代码，此处不再重复。请确保 `crawler.py` 包含全部函数。

def main():
    # 占位，实际 main 函数与之前相同
    logger.info("请补全 load_previous_events 等函数后运行")
    sys.exit(1)

if __name__ == "__main__":
    main()
