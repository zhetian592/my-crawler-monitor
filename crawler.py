#!/usr/bin/env python3
# crawler.py - RSS优先 + Nitter降级 + Firecrawl AI降级（修复版）
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

# Firecrawl 导入（修复版）
try:
    from firecrawl.firecrawl import FirecrawlApp
    FIRECRAWL_AVAILABLE = True
except ImportError:
    try:
        from firecrawl import FirecrawlApp
        FIRECRAWL_AVAILABLE = True
    except ImportError:
        FIRECRAWL_AVAILABLE = False
        print("Warning: Firecrawl SDK not installed. AI fallback disabled.")

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
DISABLE_FAILED_THRESHOLD = 3          # 已禁用，但保留变量
DISABLE_AUTO_RECOVER_DAYS = 7
EVENT_EXPIRE_DAYS = 60

EVENT_COUNTS_FILE = "event_counts.json"
HEALTHY_NITTER_FILE = "healthy_nitter.json"
HEALTHY_RSSHUB_FILE = "healthy_rsshub.json"
FAILED_SOURCES_LOG = "failed_sources.json"
DISABLED_SOURCES_FILE = "disabled_sources.json"

# Firecrawl API Key
FIRECRAWL_API_KEY = os.getenv("FIRECRAWL_API_KEY")

# 公共 RSSHub 实例（已大量失效，建议替换为私有实例）
FALLBACK_RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.ktachibana.party"
]

# 如果要使用私有 RSSHub（例如部署在 Railway），请取消注释并填入你的域名
# PRIVATE_RSSHUB = "https://your-project.up.railway.app"
# if PRIVATE_RSSHUB:
#     FALLBACK_RSSHUB_INSTANCES.insert(0, PRIVATE_RSSHUB)

FALLBACK_NITTER_INSTANCES = [
    "https://nitter.net", "https://nitter.poast.org", "https://nitter.privacyredirect.com",
    "https://lightbrd.com", "https://nitter.space", "https://nitter.tiekoetter.com",
    "https://nitter.catsarch.com", "https://xcancel.com"
]

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
    replacements = [
        ("nitter.net", "x.com"), ("twitter.net", "x.com"), ("nitter.poast.org", "x.com"),
        ("nitter.private.coffee", "x.com"), ("nitter.42l.fr", "x.com"),
    ]
    for old, new in replacements:
        link = link.replace(old, new)
    return link

def normalize_event_text(text: str) -> str:
    text = re.sub(r'[^\w\u4e00-\u9fff]', ' ', text)
    stopwords = {'的', '了', '是', '在', '和', '与', '或', '一个', '这个', '那个', '有', '被', '把', '让', '给', '从', '到', '对', '向', '在', '于', '就', '都', '也', '还', '要', '会', '能', '可以', '可能', '已经', '还', '更', '最', '很', '太', '非常', '特别', '十分', '有点', '一些', '这些', '那些', '这样', '那样', '如何', '为何', '什么', '哪里', '哪个', '谁', '为什么', '怎么', '怎样'}
    words = text.split()
    words = [w for w in words if w not in stopwords]
    return ' '.join(words)

def is_similar(a: str, b: str, threshold: float = 0.6) -> bool:
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

def extract_username_from_x_url(url: str) -> Optional[str]:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip('/')
    parts = path.split('/')
    if len(parts) >= 2 and parts[1]:
        return parts[1]
    return None

# ================= 配置加载 =================
def load_sources_config() -> List[Dict]:
    sources_file = "sources.json"
    if not os.path.exists(sources_file):
        logger.warning(f"{sources_file} 不存在，使用内置默认信源")
        return []
    try:
        with open(sources_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            logger.warning(f"{sources_file} 不是数组，使用内置默认")
            return []
        configs = []
        for item in raw:
            if isinstance(item, str):
                configs.append({"url": item, "time_window_hours": 24})
            elif isinstance(item, dict) and "url" in item:
                configs.append({
                    "url": item["url"],
                    "time_window_hours": item.get("time_window_hours", 24)
                })
        return configs
    except Exception as e:
        logger.error(f"加载 {sources_file} 失败: {e}")
        return []

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

# ================= 健康实例获取 =================
def load_healthy_instances(file_path: str, fallback: List[str]) -> List[str]:
    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                instances = json.load(f)
                if isinstance(instances, list) and instances:
                    return instances
        except Exception as e:
            logger.warning(f"读取 {file_path} 失败: {e}")
    return fallback

def get_nitter_instances() -> List[str]:
    return load_healthy_instances(HEALTHY_NITTER_FILE, FALLBACK_NITTER_INSTANCES)

def get_rsshub_instances() -> List[str]:
    return load_healthy_instances(HEALTHY_RSSHUB_FILE, FALLBACK_RSSHUB_INSTANCES)

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
    headers = headers or {"User-Agent": random.choice(USER_AGENTS)}
    resp = requests.get(url, headers=headers, timeout=timeout, proxies=PROXIES)
    resp.raise_for_status()
    return resp

# ================= AI 降级抓取 (Firecrawl) =================
def fetch_ai_fallback(url: str, original_url: str) -> List[Dict]:
    """使用 Firecrawl API 抓取网页并用 AI 提取结构化数据"""
    if not FIRECRAWL_AVAILABLE or not FIRECRAWL_API_KEY:
        logger.debug("Firecrawl 不可用，跳过 AI 降级")
        return []
    try:
        logger.info(f"[AI Fallback] 正在使用 Firecrawl 分析: {url}")
        app = FirecrawlApp(api_key=FIRECRAWL_API_KEY)
        params = {
            "formats": ["extract"],
            "extract": {
                "schema": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "summary": {"type": "string"},
                        "published": {"type": "string"},
                    },
                    "required": ["title", "summary"]
                }
            }
        }
        result = app.scrape_url(url, params=params)
        if result and isinstance(result, dict) and result.get('extract'):
            extracted = result['extract']
            title = extracted.get('title', '无标题')[:200]
            summary = extracted.get('summary', '无摘要')[:500]
            published_str = extracted.get('published', '未知时间')
            items = [{
                "title": title,
                "summary": summary,
                "link": url,
                "source": original_url,
                "source_name": "ai_fallback",
                "published_str": published_str,
                "pub_dt": None,
                "time_ago": f"AI 抓取于 {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')}",
                "fetched_at": datetime.utcnow().isoformat()
            }]
            logger.info(f"[AI Fallback] 成功提取内容: {title[:50]}...")
            return items
        else:
            logger.warning(f"[AI Fallback] 未提取到有效内容: {result}")
            return []
    except Exception as e:
        logger.error(f"[AI Fallback] 调用异常: {e}")
        return []

# ================= 抓取核心 =================
def url_to_rss(url: str, rsshub_instances: List[str]) -> Union[str, List[str], None]:
    rsshub = random.choice(rsshub_instances) if rsshub_instances else "https://rsshub.app"
    # 常规网站的官方RSS
    if "bbc.com/zhongwen/simp" in url:
        return "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"
    if "dw.com/zh" in url:
        return "https://rss.dw.com/rdf/rss-chi-all"
    if "rfi.fr/cn" in url:
        return "https://www.rfi.fr/cn/general/rss"
    if "cn.nytimes.com" in url:
        return "https://cn.nytimes.com/rss/news.xml"
    if "ntdtv.com" in url:
        return [f"{rsshub}/ntdtv/instant-news", "https://www.ntdtv.com/gb/feed"]
    if "epochtimes.com" in url:
        return [f"{rsshub}/epochtimes/gb", "https://www.epochtimes.com/gb/feed"]
    if "voachinese.com" in url:
        return [f"{rsshub}/voachinese/china", "http://feeds.feedburner.com/voacn"]
    if "reuters.com/world/china" in url:
        return f"{rsshub}/reuters/world/china"
    if "wsj.com/news/china" in url:
        return f"{rsshub}/wsj/china"
    if "ft.com/china" in url:
        return f"{rsshub}/ft/china"
    if "apnews.com/hub/china" in url:
        return f"{rsshub}/apnews/topics/china"
    if "asia.nikkei.com" in url:
        return "https://asia.nikkei.com/rss.xml"
    if "brookings.edu/topics/china" in url:
        return "https://www.brookings.edu/feed/?topic=china"
    if "csis.org/regions/asia/china" in url:
        return f"{rsshub}/csis/asia/china"
    if "pewresearch.org/topic/international-affairs/global-image-of-countries/china-global-image" in url:
        return "https://www.pewresearch.org/feed/?post_type=publication&topic=china"
    if "merics.org" in url:
        return "https://merics.org/en/rss.xml"
    if "asiasociety.org/policy-institute/center-china-analysis" in url:
        return f"{rsshub}/asiasociety/center-china-analysis"
    if "rsf.org/en/country/china" in url:
        return "https://rsf.org/en/rss.xml"
    if "uscc.gov" in url:
        return "https://www.uscc.gov/rss.xml"
    # X 平台通过 RSSHub 路由
    if "x.com/" in url or "twitter.com/" in url:
        username = extract_username_from_x_url(url)
        if username:
            return f"{rsshub}/twitter/user/{username}"
        return None
    # 其他网址直接作为 RSS 尝试
    return url

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
            # 来源名称
            if "x.com/" in original_url:
                username = extract_username_from_x_url(original_url) or original_url
                source_name = "@" + username
            else:
                domain_match = re.search(r'https?://([^/]+)', original_url)
                raw_domain = domain_match.group(1) if domain_match else original_url
                source_name = raw_domain
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
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        logger.error(f"抓取异常 {original_url} (RSS: {rss_url}): {e}")
        return []

def fetch_with_retry(original_url: str, processed_hashes: set, nitter_instances: List[str],
                     rsshub_instances: List[str], time_window_hours: int) -> List[Dict]:
    if is_source_disabled(original_url):
        return []
    # 1. RSS 候选
    rss_candidates = url_to_rss(original_url, rsshub_instances)
    if rss_candidates:
        if isinstance(rss_candidates, str):
            rss_candidates = [rss_candidates]
        for rss_url in rss_candidates:
            items = fetch_single_rss(rss_url, original_url, processed_hashes, time_window_hours)
            if items:
                logger.debug(f"{original_url} 成功 via RSS: {rss_url}")
                return items
            time.sleep(0.5)
    # 2. X 信源尝试 Nitter
    if "x.com/" in original_url:
        username = extract_username_from_x_url(original_url)
        if username:
            for nitter in nitter_instances:
                test_url = f"{nitter}/{username}/rss"
                items = fetch_single_rss(test_url, original_url, processed_hashes, time_window_hours)
                if items:
                    logger.debug(f"X {username} 成功 via Nitter: {nitter}")
                    return items
                time.sleep(0.5)
    # 3. AI 降级（仅对 X 或重要域名尝试，避免消耗）
    if "x.com/" in original_url or original_url.endswith(".xml") or "rss" in original_url.lower():
        ai_items = fetch_ai_fallback(original_url, original_url)
        if ai_items:
            logger.info(f"AI 降级成功: {original_url}")
            return ai_items
    logger.debug(f"{original_url} 所有方式均失败")
    return []

def fetch_all_sources() -> Tuple[List[Dict], List[Tuple[str, str]]]:
    logger.info(f"开始抓取 {len(RAW_SOURCES)} 个信源")
    all_items = []
    processed_hashes = set()
    failed_sources = []
    nitter_instances = get_nitter_instances()
    rsshub_instances = get_rsshub_instances()
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_with_retry, url, processed_hashes, nitter_instances,
                            rsshub_instances, TIME_WINDOW_MAP.get(url, 24)): url
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

# 后续的 log_failed_sources, load_previous_events, load_event_counts, ... 等函数与之前保持不变（因篇幅省略）
# 为保持完整性，这里仅示意，实际使用时将之前稳定版本的后半部分（从 log_failed_sources 开始）粘贴过来
