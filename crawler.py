# crawler.py - 优化版（并发批次 + 链接防404 + 超时保护）
import os
import json
import re
import time
import random
import hashlib
import logging
import sys
import threading
import pickle
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError as FuturesTimeoutError
from typing import List, Dict, Any, Tuple, Optional, Union
from logging.handlers import RotatingFileHandler
from urllib.parse import urljoin

import requests
import feedparser
import openai
from bs4 import BeautifulSoup
import difflib

from openai import RateLimitError, AuthenticationError, BadRequestError, APITimeoutError

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

# ================= 配置常量（优化后） =================
API_KEY = os.environ.get("OPENROUTER_API_KEY") or os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    logger.warning("未设置 OPENROUTER_API_KEY 或 OPENAI_API_KEY，AI 功能将不可用")

AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://openrouter.ai/api/v1")
AI_MODEL = os.environ.get("AI_MODEL", "openrouter/free")

AI_JSON_MODE = os.environ.get("AI_JSON_MODE", "false").lower() == "true"
AI_TIMEOUT_SECONDS = int(os.environ.get("AI_TIMEOUT_SECONDS", 600))   # 增加到 10 分钟

REPORT_PASSWORD = os.environ.get("REPORT_PASSWORD", "yangge233")
PROXIES = None
if os.environ.get("HTTP_PROXY"):
    PROXIES = {"http": os.environ["HTTP_PROXY"], "https": os.environ.get("HTTPS_PROXY", os.environ["HTTP_PROXY"])}

KEEP_DAYS = 2
SIMILARITY_THRESHOLD = 0.6
MAX_REPEAT_COUNT = 3
COOLDOWN_DAYS = 7
MAX_WORKERS = 3                     # 降低抓取并发，减少被屏蔽风险
AI_REQUEST_DELAY = 0.5
DISABLE_FAILED_THRESHOLD = 3
DISABLE_COOLDOWN_MINUTES = 60 * 12
DISABLE_AUTO_RECOVER_DAYS = 7
EVENT_EXPIRE_DAYS = 60
CACHE_TTL = 86400 * 7

AI_CONCURRENCY_LIMIT = int(os.environ.get("AI_CONCURRENCY_LIMIT", "2"))   # 允许同时处理 2 批

EVENT_COUNTS_FILE = "event_counts.json"
HEALTHY_NITTER_FILE = "healthy_nitter.json"
HEALTHY_RSSHUB_FILE = "healthy_rsshub.json"
FAILED_SOURCES_LOG = "failed_sources.json"
DISABLED_SOURCES_FILE = "disabled_sources.json"
URL_DEDUP_FILE = "url_dedup.json"
AI_CACHE_FILE = "ai_cache.pkl"

FALLBACK_NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.space",
    "https://nitter.tiekoetter.com",
    "https://nitter.catsarch.com",
    "https://xcancel.com"
]
FALLBACK_RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.ktachibana.party"
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
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
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

def batch_key(blocks: List[str]) -> str:
    sorted_blocks = sorted(blocks)
    combined = "\n".join(sorted_blocks).encode('utf-8')
    return hashlib.sha256(combined).hexdigest()

def convert_to_official_x_link(link: str) -> str:
    """仅将 nitter 链接转换为 x.com 链接，不改变其他链接"""
    if not link:
        return link
    replacements = [
        ("nitter.net", "x.com"),
        ("twitter.net", "x.com"),
        ("nitter.poast.org", "x.com"),
        ("nitter.private.coffee", "x.com"),
        ("nitter.42l.fr", "x.com"),
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

# ================= 信源配置加载 =================
def load_sources_config() -> List[Dict]:
    sources_file = "sources.json"
    default = [
        {"url": "https://www.bbc.com/zhongwen/simp", "time_window_hours": 24},
        {"url": "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058", "time_window_hours": 24},
        {"url": "https://www.rfi.fr/cn/", "time_window_hours": 24},
        {"url": "https://cn.nytimes.com/", "time_window_hours": 24},
        {"url": "https://www.ntdtv.com/gb/instant-news.html", "time_window_hours": 24},
        {"url": "https://www.epochtimes.com/gb/instant-news.htm", "time_window_hours": 24},
        {"url": "https://x.com/whyyoutouzhele", "time_window_hours": 24},
    ]
    if not os.path.exists(sources_file):
        logger.warning(f"{sources_file} 不存在，使用默认信源")
        return default
    try:
        with open(sources_file, 'r', encoding='utf-8') as f:
            raw = json.load(f)
        if not isinstance(raw, list):
            logger.warning(f"{sources_file} 格式错误，应为数组，使用默认信源")
            return default
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
            return default
        return configs
    except Exception as e:
        logger.error(f"加载 {sources_file} 失败: {e}，使用默认信源")
        return default

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

# ================ 信源健康管理 ================
class SourceHealth:
    def __init__(self, max_fails=DISABLE_FAILED_THRESHOLD, cooldown_minutes=DISABLE_COOLDOWN_MINUTES):
        self.max_fails = max_fails
        self.cooldown = cooldown_minutes * 60
        self.fail_counts = {}
        self.disabled_until = {}

    def record_fail(self, source_key):
        self.fail_counts[source_key] = self.fail_counts.get(source_key, 0) + 1
        if self.fail_counts[source_key] >= self.max_fails:
            self.disabled_until[source_key] = time.time() + self.cooldown
            logger.warning(f"信源 {source_key} 连续失败{self.fail_counts[source_key]}次，已暂时禁用 {self.cooldown//60} 分钟")

    def record_success(self, source_key):
        if source_key in self.disabled_until:
            logger.info(f"信源 {source_key} 已恢复可用")
            del self.disabled_until[source_key]
        self.fail_counts[source_key] = 0

    def is_disabled(self, source_key):
        if source_key not in self.disabled_until:
            return False
        if time.time() > self.disabled_until[source_key]:
            del self.disabled_until[source_key]
            self.fail_counts[source_key] = 0
            return False
        return True

class MirrorPool:
    def __init__(self, urls):
        self.original = list(urls)
        self.available = list(urls)

    def get_next(self):
        if not self.available:
            logger.warning("所有镜像均已失败，重置池")
            self.available = list(self.original)
        url = self.available.pop(0)
        return url

    def report_failure(self, url):
        if url in self.available:
            self.available.remove(url)

    def report_success(self, url):
        pass

nitter_health = SourceHealth(max_fails=2, cooldown_minutes=30)
rsshub_health = SourceHealth(max_fails=2, cooldown_minutes=30)

def get_nitter_instances() -> List[str]:
    base = load_healthy_instances(HEALTHY_NITTER_FILE, FALLBACK_NITTER_INSTANCES)
    return [inst for inst in base if not nitter_health.is_disabled(inst)]

def update_nitter_health(instance_url: str, success: bool):
    if success:
        nitter_health.record_success(instance_url)
    else:
        nitter_health.record_fail(instance_url)

def get_rsshub_instances() -> List[str]:
    base = load_healthy_instances(HEALTHY_RSSHUB_FILE, FALLBACK_RSSHUB_INSTANCES)
    return [inst for inst in base if not rsshub_health.is_disabled(inst)]

def update_rsshub_health(instance_url: str, success: bool):
    if success:
        rsshub_health.record_success(instance_url)
    else:
        rsshub_health.record_fail(instance_url)

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

# ================ URL去重缓存 ================
class URLDedupCache:
    def __init__(self, cache_file=URL_DEDUP_FILE):
        self.cache_file = cache_file
        self.url_set = set()
        self.bloom = None
        try:
            from bloom_filter import BloomFilter
            self.bloom = BloomFilter(max_elements=1_000_000, error_rate=0.001)
            if os.path.exists(cache_file):
                with open(cache_file, 'r') as f:
                    self.bloom = BloomFilter.from_base64(f.read())
            logger.info("URL去重使用布隆过滤器")
        except ImportError:
            logger.info("bloom-filter未安装，URL去重使用内存集合（重启后失效）")
        if not self.bloom and os.path.exists(cache_file):
            try:
                with open(cache_file, 'r') as f:
                    self.url_set = set(json.load(f))
            except:
                pass

    def seen(self, url: str) -> bool:
        if self.bloom:
            return url in self.bloom
        return url in self.url_set

    def add(self, url: str):
        if self.bloom:
            self.bloom.add(url)
        else:
            self.url_set.add(url)

    def save(self):
        if self.bloom:
            with open(self.cache_file, 'w') as f:
                f.write(self.bloom.to_base64())
        else:
            with open(self.cache_file, 'w') as f:
                json.dump(list(self.url_set), f)

# ================ 失败信源管理 ================
def load_disabled_sources() -> Dict[str, dict]:
    if os.path.exists(DISABLED_SOURCES_FILE):
        try:
            with open(DISABLED_SOURCES_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict):
                    new_data = {}
                    for k, v in data.items():
                        if isinstance(v, int):
                            new_data[k] = {"fail_count": v, "disabled_at": None}
                        else:
                            new_data[k] = v
                    return new_data
        except:
            pass
    return {}

def save_disabled_sources(disabled: Dict[str, dict]):
    with open(DISABLED_SOURCES_FILE, 'w', encoding='utf-8') as f:
        json.dump(disabled, f, indent=2, ensure_ascii=False)

def update_disabled_sources(failed_sources: List[Tuple[str, str]]):
    disabled = load_disabled_sources()
    today = datetime.utcnow().date().isoformat()
    for url, _ in failed_sources:
        if url not in disabled:
            disabled[url] = {"fail_count": 0, "disabled_at": None}
        disabled[url]["fail_count"] += 1
        if disabled[url]["fail_count"] >= DISABLE_FAILED_THRESHOLD and disabled[url]["disabled_at"] is None:
            disabled[url]["disabled_at"] = today
            logger.warning(f"信源 {url} 已连续失败 {disabled[url]['fail_count']} 次，禁用（禁用时间 {today}）")
    success_urls = set(RAW_SOURCES) - {u for u, _ in failed_sources}
    for url in success_urls:
        if url in disabled:
            del disabled[url]
    recover_cutoff = (datetime.utcnow().date() - timedelta(days=DISABLE_AUTO_RECOVER_DAYS)).isoformat()
    to_remove = []
    for url, info in disabled.items():
        if info.get("disabled_at") and info["disabled_at"] < recover_cutoff:
            to_remove.append(url)
    for url in to_remove:
        logger.info(f"信源 {url} 已禁用超过 {DISABLE_AUTO_RECOVER_DAYS} 天，自动恢复")
        del disabled[url]
    save_disabled_sources(disabled)

def is_source_disabled(url: str) -> bool:
    disabled = load_disabled_sources()
    return url in disabled

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

# ================= 抓取核心（★ 链接404修复） =================
def url_to_rss(url: str, rsshub_instances: List[str]) -> Union[str, List[str], None]:
    rsshub = random.choice(rsshub_instances)
    if "voachinese.com" in url:
        return [f"{rsshub}/voachinese/china", "http://feeds.feedburner.com/voacn"]
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
    if "x.com/" in url:
        return None
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
    if "hrw.org" in url:
        return "https://www.hrw.org/rss/news"
    if "freedomhouse.org" in url:
        return "https://freedomhouse.org/rss.xml"
    if "aspistrategist.org.au" in url:
        return "https://www.aspistrategist.org.au/feed/"
    if "amnesty.org" in url:
        return "https://www.amnesty.org/en/feed/"
    if "chinapower.csis.org" in url:
        return "https://chinapower.csis.org/feed/"
    if "carnegieendowment.org" in url:
        return "https://carnegieendowment.org/rss"
    if "chathamhouse.org" in url:
        return "https://www.chathamhouse.org/rss-feeds"
    return url

def fetch_single_rss(rss_url: str, original_url: str, processed_hashes: set, url_cache: URLDedupCache, time_window_hours: int) -> List[Dict]:
    try:
        resp = fetch_url(rss_url, timeout=25)
        feed = feedparser.parse(resp.content)
        cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
        items = []
        feed_base = feed.feed.get('link', '')
        for entry in feed.entries:
            published_str = entry.get("published", entry.get("updated", ""))
            pub_dt = parse_published_strict(published_str)
            if pub_dt is not None and pub_dt < cutoff:
                continue

            raw_link = entry.get("link", "")
            if not raw_link:
                continue

            # 补全相对链接
            if not raw_link.startswith(("http://", "https://")):
                base = feed_base if feed_base else original_url
                link = urljoin(base, raw_link)
            else:
                link = raw_link

            if "x.com/" in original_url:
                link = convert_to_official_x_link(link)

            if url_cache.seen(link):
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

            if "x.com/" in original_url:
                parts = original_url.split("/")
                raw_name = parts[3] if len(parts) > 3 else original_url
                source_name = "@" + raw_name
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
            url_cache.add(link)
        return items
    except Exception as e:
        logger.error(f"抓取异常 {original_url} (RSS: {rss_url}): {e}")
        return []

def fetch_with_retry(original_url: str, processed_hashes: set, url_cache: URLDedupCache, time_window_hours: int) -> List[Dict]:
    if is_source_disabled(original_url):
        logger.debug(f"信源 {original_url} 已被禁用，跳过")
        return []

    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        nitter_pool = MirrorPool(get_nitter_instances())
        while True:
            try:
                instance = nitter_pool.get_next() if nitter_pool.available else None
                if not instance:
                    break
                test_url = f"{instance}/{username}/rss"
                logger.debug(f"尝试 X {username} 使用 {instance}")
                items = fetch_single_rss(test_url, original_url, processed_hashes, url_cache, time_window_hours)
                if items:
                    logger.debug(f"X {username} 成功 via {instance} (条数: {len(items)})")
                    update_nitter_health(instance, True)
                    return items
                else:
                    logger.debug(f"X {username} 失败 via {instance}")
                    update_nitter_health(instance, False)
                    nitter_pool.report_failure(instance)
            except Exception:
                break
            time.sleep(0.5)
        logger.debug(f"X {username} 所有实例均失败")
        return []

    rsshub_instances = get_rsshub_instances()
    rss_candidates = url_to_rss(original_url, rsshub_instances)
    if not rss_candidates:
        logger.debug(f"无法生成 RSS 地址: {original_url}")
        return []
    if isinstance(rss_candidates, str):
        rss_candidates = [rss_candidates]

    for rss_url in rss_candidates:
        instance_used = None
        for inst in rsshub_instances:
            if inst in rss_url:
                instance_used = inst
                break
        try:
            items = fetch_single_rss(rss_url, original_url, processed_hashes, url_cache, time_window_hours)
            if items:
                logger.debug(f"{original_url} 成功 (条数: {len(items)}) via {rss_url}")
                if instance_used:
                    update_rsshub_health(instance_used, True)
                return items
            else:
                logger.debug(f"{original_url} 失败 via {rss_url}")
                if instance_used:
                    update_rsshub_health(instance_used, False)
        except Exception as e:
            logger.debug(f"{original_url} 异常 via {rss_url}: {e}")
            if instance_used:
                update_rsshub_health(instance_used, False)
        time.sleep(0.5)
    logger.debug(f"{original_url} 所有 RSS 地址均失败")
    return []

def fetch_all_sources() -> Tuple[List[Dict], List[Tuple[str, str]]]:
    logger.info(f"开始抓取 {len(RAW_SOURCES)} 个信源（时间窗口各异）")
    all_items = []
    processed_hashes = set()
    url_cache = URLDedupCache()
    failed_sources = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_with_retry, url, processed_hashes, url_cache, TIME_WINDOW_MAP.get(url, 24)): url
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
                    logger.debug(f"✗ {url} -> 0 条")
            except Exception as e:
                failed_sources.append((url, str(e)))
                logger.error(f"✗ {url} 异常: {e}")

    url_cache.save()
    logger.info(f"去重后共 {len(all_items)} 条（已通过内容哈希+URL去重）")
    return all_items, failed_sources

# ================= 失败记录 =================
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

# ================= 历史事件管理 =================
def load_previous_events() -> List[str]:
    events = []
    if not os.path.exists("report.md"):
        return events
    try:
        with open("report.md", "r", encoding='utf-8') as f:
            content = f.read()
        lines = content.split("\n")
        in_table = False
        for line in lines:
            if line.startswith("|") and "|" in line:
                if not in_table:
                    in_table = True
                if re.match(r'^\|[\s\-:]+\|$', line):
                    continue
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if len(cells) >= 1:
                    event = cells[0].replace("🆕", "").strip()
                    event = re.sub(r'（\d+个信源）', '', event).strip()
                    events.append(event)
        logger.info(f"从上次报告加载了 {len(events)} 个事件简述")
    except Exception as e:
        logger.error(f"加载上次报告失败: {e}")
    return events

def load_event_counts() -> Dict:
    if os.path.exists(EVENT_COUNTS_FILE):
        try:
            with open(EVENT_COUNTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                if isinstance(data, dict) and all(isinstance(v, int) for v in data.values()):
                    new_data = {}
                    for k, v in data.items():
                        new_data[k] = {"count": v, "last_seen": datetime.utcnow().strftime("%Y-%m-%d")}
                    return new_data
                return data
        except:
            pass
    return {}

def save_event_counts(counts: Dict):
    with open(EVENT_COUNTS_FILE, 'w', encoding='utf-8') as f:
        json.dump(counts, f, ensure_ascii=False, indent=2)

def cleanup_old_events(event_counts: Dict) -> Dict:
    cutoff = datetime.utcnow().date() - timedelta(days=EVENT_EXPIRE_DAYS)
    to_delete = []
    for event, record in event_counts.items():
        last_seen = record.get("last_seen")
        if last_seen:
            try:
                last_date = datetime.strptime(last_seen, "%Y-%m-%d").date()
                if last_date < cutoff:
                    to_delete.append(event)
            except:
                pass
    for event in to_delete:
        del event_counts[event]
        logger.info(f"删除过期事件: {event[:50]}")
    return event_counts

# ================= AI 分析（并发优化） =================
_ai_client = None
_client_lock = threading.Lock()
AI_SEMAPHORE = threading.Semaphore(AI_CONCURRENCY_LIMIT)

_AI_KWARGS_CACHE = None

def build_ai_request_kwargs():
    kwargs = {
        "model": AI_MODEL,
        "temperature": 0.3,
        "max_tokens": 1200,
    }
    if AI_JSON_MODE:
        kwargs["response_format"] = {"type": "json_object"}
    if "openrouter" in AI_BASE_URL:
        kwargs["extra_headers"] = {
            "HTTP-Referer": os.environ.get("APP_REFERER", "https://github.com/zhetian592/my-crawler-monitor"),
            "X-Title": "Crawler Monitor",
        }
    return kwargs

def get_ai_kwargs():
    global _AI_KWARGS_CACHE
    if _AI_KWARGS_CACHE is None:
        _AI_KWARGS_CACHE = build_ai_request_kwargs()
    return _AI_KWARGS_CACHE

def get_ai_client():
    global _ai_client
    if _ai_client is None:
        with _client_lock:
            if _ai_client is None:
                if not API_KEY:
                    logger.error("API_KEY 未配置，无法创建客户端")
                    return None
                _ai_client = openai.OpenAI(
                    base_url=AI_BASE_URL,
                    api_key=API_KEY,
                    timeout=90.0,
                    max_retries=0,
                )
    return _ai_client

def estimate_tokens(text: str) -> int:
    if TIKTOKEN_AVAILABLE:
        try:
            enc = tiktoken.encoding_for_model("gpt-4o-mini")
            return len(enc.encode(text))
        except Exception:
            pass
    cn_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - cn_chars
    return int(cn_chars * 1.2 + other_chars * 0.25)

def call_ai_with_retry(prompt: str, max_retries: int = 3) -> Optional[str]:
    if not API_KEY:
        return None
    client = get_ai_client()
    if client is None:
        return None
    kwargs = get_ai_kwargs()
    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are a sentiment analyst. Output ONLY a valid JSON array. Do not include any other text, explanation, or markdown."},
                    {"role": "user", "content": prompt}
                ],
                **kwargs
            )
            content = response.choices[0].message.content
            if content is not None:
                return content
        except RateLimitError as e:
            wait_time = 30 * (attempt + 1)
            logger.warning(f"限流，等待 {wait_time}s 重试: {e}")
            time.sleep(wait_time)
        except AuthenticationError as e:
            logger.error(f"认证失败: {e}")
            return None
        except BadRequestError as e:
            logger.error(f"请求格式错误: {e}")
            return None
        except APITimeoutError as e:
            logger.warning(f"超时，尝试 {attempt+1}/{max_retries}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
        except Exception as e:
            logger.warning(f"AI调用失败 (尝试 {attempt+1}): {type(e).__name__}: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return None

def extract_json(text: str) -> Optional[str]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r'```(?:json)?\s*', '', text)
        text = re.sub(r'```$', '', text)
    start = text.find('[')
    end = text.rfind(']')
    if start != -1 and end != -1 and start <= end:
        return text[start:end+1]
    return None

def should_skip(article: Dict) -> bool:
    title = article.get("title", "")
    if title.startswith("RT ") or len(title) < 5:
        return True
    skip_kw = ["彩票", "娱乐八卦", "体育赛事", "天气预报", "星座", "综艺", "搞笑"]
    if any(k in title for k in skip_kw):
        return True
    return False

# ---------- 后备规则过滤 ----------
NEGATIVE_KEYWORDS = [
    "打压", "镇压", "抗议", "维权", "人权", "审查", "监控", "失踪", "迫害",
    "拘留", "逮捕", "打压", "言论自由", "封锁", "屏蔽", "防火墙", "维稳",
    "强拆", "信访", "上访", "黑监狱", "劳教", "精神病院", "活摘", "种族灭绝",
    "集中营", "再教育营", "新疆", "西藏", "台湾", "香港", "天安门", "法轮功",
    "中共", "独裁", "专制", "独裁者", "一党专政", "新闻自由", "互联网审查",
    "言论管控", "舆论控制", "洗脑", "宣传", "低人权优势", "血汗工厂",
    "环境污染", "毒奶粉", "疫苗丑闻", "食品安全", "城管", "暴力执法",
    "群体事件", "社会不公", "贫富差距", "996", "内卷", "躺平"
]

def rule_based_filter(articles: List[Dict]) -> List[Dict]:
    rows = []
    seen_hashes = set()
    for art in articles:
        text = art["title"] + " " + art["summary"]
        if any(kw in text for kw in NEGATIVE_KEYWORDS):
            h = content_hash(art["title"], art["summary"])
            if h in seen_hashes:
                continue
            seen_hashes.add(h)
            source_name = get_display_source(art.get("source_name", "未知"))
            time_ago = art.get("time_ago", "未知")
            link = art.get("link", "")
            risk = "检测到敏感关键词"
            level = "中"
            safe_title = art['title'][:80].replace("|", "｜")
            row = f"| {safe_title} | [查看]({link}) | {risk} | {source_name} | {time_ago} | {level} |"
            rows.append(row)
    return rows

def load_ai_cache() -> Dict:
    if os.path.exists(AI_CACHE_FILE):
        try:
            with open(AI_CACHE_FILE, 'rb') as f:
                cache = pickle.load(f)
                if isinstance(cache, dict):
                    for key, value in cache.items():
                        if isinstance(value, list):
                            cache[key] = {"items": value, "created_at": time.time()}
                    return cache
        except Exception as e:
            logger.warning(f"加载AI缓存失败: {e}")
    return {}

def save_ai_cache(cache: Dict):
    try:
        with open(AI_CACHE_FILE, 'wb') as f:
            pickle.dump(cache, f)
    except Exception as e:
        logger.warning(f"保存AI缓存失败: {e}")

def call_ai_unified(articles: List[Dict], old_events: List[str]) -> Tuple[str, List[str]]:
    if not articles:
        return "无相关内容。\n", []

    articles = [a for a in articles if not should_skip(a)]
    logger.info(f"预过滤后剩余 {len(articles)} 条待分析")

    ai_cache = load_ai_cache()
    all_rows = []

    blocks_with_meta = []
    for art in articles:
        meta = f"发布时间：{art.get('time_ago', '未知')} | 来源：{get_display_source(art.get('source_name', '未知'))}"
        block = f"{meta}\n标题：{art.get('title', '')[:150]}\n摘要：{art.get('summary', '')[:300]}\n链接：{art.get('link', '')}\n"
        blocks_with_meta.append(block)

    # 减小每批大小，加快单批速度
    max_content_tokens = int(os.environ.get("MAX_CONTENT_TOKENS", 6000))
    batches = []
    current_blocks = []
    current_tokens = 0

    prompt_prefix = """根据以下内容，筛选出涉华负面舆情条目，以 JSON 数组输出。
每个对象必须包含字段：event(简述), link(原文链接), risk(风险点，格式"1. xx 2. xx 3. xx"，每条≤20字), source(来源), time(时间), level(高/中/低)。
严格要求：只输出一个 JSON 数组，不要任何解释、代码块标记或额外文字。没有符合内容时输出 []。

抓取内容：
"""
    prompt_tokens = estimate_tokens(prompt_prefix)

    for block in blocks_with_meta:
        block_tokens = estimate_tokens(block)
        if current_tokens + block_tokens + prompt_tokens > max_content_tokens and current_blocks:
            batches.append(current_blocks)
            current_blocks = []
            current_tokens = 0
        current_blocks.append(block)
        current_tokens += block_tokens
    if current_blocks:
        batches.append(current_blocks)

    logger.info(f"内容分为 {len(batches)} 批（单批上限 {max_content_tokens} tokens）")

    # 处理批次
    def process_single_batch(batch_blocks):
        key = batch_key(batch_blocks)
        now = time.time()

        if key in ai_cache:
            cached_entry = ai_cache[key]
            if isinstance(cached_entry, dict) and "created_at" in cached_entry:
                if now - cached_entry["created_at"] < CACHE_TTL:
                    cached_items = cached_entry["items"]
                    rows = []
                    for item in cached_items:
                        if all(k in item for k in ("event","link","risk","source","time","level")):
                            safe_event = item['event'].replace("|", "｜")
                            row = f"| {safe_event} | [查看]({item['link']}) | {item['risk']} | {item['source']} | {item['time']} | {item['level']} |"
                            rows.append(row)
                    return rows
                else:
                    logger.debug("缓存已过期，将重新调用 AI")
            else:
                ai_cache[key] = {"items": cached_entry, "created_at": now}
                rows = []
                for item in cached_entry:
                    if all(k in item for k in ("event","link","risk","source","time","level")):
                        safe_event = item['event'].replace("|", "｜")
                        row = f"| {safe_event} | [查看]({item['link']}) | {item['risk']} | {item['source']} | {item['time']} | {item['level']} |"
                        rows.append(row)
                return rows

        prompt = prompt_prefix + "\n".join(batch_blocks)
        with AI_SEMAPHORE:
            raw_response = call_ai_with_retry(prompt)
        if raw_response is None:
            return None

        json_str = extract_json(raw_response)
        if json_str is None:
            logger.warning(f"批次未提取到 JSON，原始开头: {raw_response[:150]}")
            return None

        try:
            parsed = json.loads(json_str)
            if not isinstance(parsed, list):
                raise ValueError("JSON 不是数组")
            ai_cache[key] = {"items": parsed, "created_at": time.time()}
            rows = []
            for item in parsed:
                if all(k in item for k in ("event","link","risk","source","time","level")):
                    safe_event = item['event'].replace("|", "｜")
                    row = f"| {safe_event} | [查看]({item['link']}) | {item['risk']} | {item['source']} | {item['time']} | {item['level']} |"
                    rows.append(row)
            return rows
        except Exception as e:
            logger.warning(f"批次 JSON 解析失败: {e}, 原始片段: {json_str[:200]}")
            return None

    cached_rows = []
    uncached_batches = []
    for batch_blocks in batches:
        key = batch_key(batch_blocks)
        if key in ai_cache and isinstance(ai_cache[key], dict) and "created_at" in ai_cache[key] and time.time() - ai_cache[key]["created_at"] < CACHE_TTL:
            rows = process_single_batch(batch_blocks)
            if rows:
                cached_rows.extend(rows)
        else:
            uncached_batches.append(batch_blocks)

    ai_start_time = time.time()
    completed_rows = list(cached_rows)
    ai_failed = False

    if uncached_batches:
        with ThreadPoolExecutor(max_workers=AI_CONCURRENCY_LIMIT) as executor:
            future_to_batch = {executor.submit(process_single_batch, b): b for b in uncached_batches}
            try:
                for future in as_completed(future_to_batch, timeout=AI_TIMEOUT_SECONDS - (time.time() - ai_start_time)):
                    try:
                        rows = future.result(timeout=30)
                        if rows is not None:
                            completed_rows.extend(rows)
                        else:
                            ai_failed = True
                            logger.warning("某个批次 AI 调用返回 None")
                    except Exception as e:
                        ai_failed = True
                        logger.error(f"处理批次异常: {e}")
            except FuturesTimeoutError:
                ai_failed = True
                logger.error(f"AI 分析整体超时（{AI_TIMEOUT_SECONDS}s），未完成的批次将使用后备过滤方案")
                for future in future_to_batch:
                    future.cancel()

    if ai_failed or len(completed_rows) == 0:
        logger.warning("AI 分析不完整或为空，启用内置规则过滤后备")
        rule_rows = rule_based_filter(articles)
        completed_rows.extend(rule_rows)
        logger.info(f"后备规则过滤补充了 {len(rule_rows)} 行")

    if not completed_rows:
        return "无相关内容。\n", []

    unique_rows, events_in_report = deduplicate_and_mark_new(completed_rows, old_events)

    if unique_rows:
        table_header = "| 事件简述 | 原文链接 | 潜在风险点 | 信息来源 | 发布多久前 | 风险等级 |"
        table_sep = "|----------|----------|------------|----------|------------|------------|"
        final_table = "\n".join([table_header, table_sep] + unique_rows)
    else:
        final_table = "无相关内容。\n"

    save_ai_cache(ai_cache)
    return final_table, events_in_report

def deduplicate_and_mark_new(rows: List[str], old_events: List[str]) -> Tuple[List[str], List[str]]:
    events_data = []
    for row in rows:
        cells = [c.strip() for c in row.split("|")[1:-1]]
        if len(cells) != 6:
            continue
        event, link, risk, source, time_ago, risk_level = cells
        pub_dt = None
        if "小时前" in time_ago:
            try:
                hours = int(time_ago.replace("小时前", "").strip())
                pub_dt = datetime.utcnow() - timedelta(hours=hours)
            except:
                pass
        elif "分钟前" in time_ago:
            try:
                minutes = int(time_ago.replace("分钟前", "").strip())
                pub_dt = datetime.utcnow() - timedelta(minutes=minutes)
            except:
                pass
        elif "天前" in time_ago:
            try:
                days = int(time_ago.replace("天前", "").strip())
                pub_dt = datetime.utcnow() - timedelta(days=days)
            except:
                pass
        events_data.append((event, source, link, risk, time_ago, risk_level, pub_dt, row))

    merged = []
    used = [False] * len(events_data)
    for i in range(len(events_data)):
        if used[i]:
            continue
        event_i = events_data[i][0]
        group = [events_data[i]]
        for j in range(len(events_data)):
            if i == j or used[j]:
                continue
            if is_similar(event_i, events_data[j][0]):
                group.append(events_data[j])
                used[j] = True
        used[i] = True
        merged.append(group)

    unique_rows = []
    events_in_report = []
    for group in merged:
        best = None
        best_pub = None
        best_prio = 999
        for item in group:
            _, src, _, _, _, _, pub_dt, _ = item
            prio = get_source_priority(src)
            if best is None:
                best = item
                best_pub = pub_dt
                best_prio = prio
            else:
                if pub_dt and best_pub:
                    if pub_dt > best_pub:
                        best = item
                        best_pub = pub_dt
                        best_prio = prio
                    elif pub_dt == best_pub and prio < best_prio:
                        best = item
                        best_pub = pub_dt
                        best_prio = prio
                elif pub_dt and not best_pub:
                    best = item
                    best_pub = pub_dt
                    best_prio = prio
                elif not pub_dt and best_pub:
                    pass
                else:
                    if prio < best_prio:
                        best = item
                        best_pub = pub_dt
                        best_prio = prio
        first_event, first_src, first_link, first_risk, first_time, first_level, _, _ = best
        sources = sorted(set([item[1] for item in group]))
        source_display = "、".join(sources) if len(sources) <= 3 else f"{len(sources)}个信源"
        safe_event = first_event.replace("|", "｜")
        if len(sources) > 1:
            safe_event += f"（{len(sources)}个信源）"
        new_row = f"| {safe_event} | [查看]({first_link}) | {first_risk} | {source_display} | {first_time} | {first_level} |"
        is_new = True
        for old in old_events:
            if is_similar(first_event, old):
                is_new = False
                break
        if is_new:
            new_row = "| 🆕 " + new_row[2:]
        unique_rows.append(new_row)
        events_in_report.append(first_event)
    return unique_rows, events_in_report

def filter_by_repeat_count(rows: List[str], event_counts: Dict) -> Tuple[List[str], Dict]:
    today = datetime.utcnow().date()
    new_counts = {}
    new_rows = []
    for row in rows:
        cells = [c.strip() for c in row.split("|")[1:-1]]
        if len(cells) != 6:
            continue
        event = cells[0].replace("🆕", "").strip()
        event = re.sub(r'（\d+个信源）', '', event).strip()
        record = event_counts.get(event, {"count": 0, "last_seen": None})
        count = record.get("count", 0)
        last_seen_str = record.get("last_seen")
        last_seen = datetime.strptime(last_seen_str, "%Y-%m-%d").date() if last_seen_str else None

        if count >= MAX_REPEAT_COUNT:
            if last_seen and (today - last_seen).days < COOLDOWN_DAYS:
                logger.info(f"隐藏重复事件（冷却期）: {event[:50]}")
                new_counts[event] = {"count": count, "last_seen": today.isoformat()}
                continue
            else:
                count = 1
        else:
            count += 1
        new_rows.append(row)
        new_counts[event] = {"count": count, "last_seen": today.isoformat()}
    for event, record in event_counts.items():
        if event not in new_counts:
            new_counts[event] = record
    return new_rows, new_counts

# ================= HTML 报告生成 =================
def generate_html_report(report_text: str, all_articles: List[Dict]) -> str:
    lines = report_text.split("\n")
    html_table = ""
    in_table = False
    for line in lines:
        if line.startswith("|") and "|" in line:
            if not in_table:
                html_table += '<table>\n<thead>\n<tr>\n'
                header_cells = [c.strip() for c in line.split("|")[1:-1]]
                for h in header_cells:
                    html_table += f"<th>{h}</th>\n"
                html_table += "</tr>\n</thead>\n<tbody>\n"
                in_table = True
                continue
            if re.match(r'^\|[\s\-:]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) != 6:
                continue
            html_table += "<tr>\n"
            for cell in cells:
                cell = re.sub(
                    r'\[([^\]]*)\]\(([^\)]+)\)',
                    r'<a href="\2" target="_blank" rel="noopener noreferrer">\1</a>',
                    cell
                )
                html_table += f"<td>{cell}</td>\n"
            html_table += "</tr>\n"
        else:
            if in_table:
                html_table += "</tbody></table>\n"
                in_table = False
    if in_table:
        html_table += "</tbody></table>\n"

    login_script = f'''
<script>
(function() {{
    const PASSWORD = '{REPORT_PASSWORD}';
    const SESSION_KEY = 'logged_in';
    if (sessionStorage.getItem(SESSION_KEY) === 'true') return;
    let pwd = prompt('请输入访问密码：');
    if (pwd === PASSWORD) {{
        sessionStorage.setItem(SESSION_KEY, 'true');
    }} else {{
        document.body.innerHTML = '<div style="text-align:center; margin-top:50px;"><h2>密码错误，无法访问</h2></div>';
        throw new Error('登录失败');
    }}
}})();
</script>
'''

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>内容安全行业舆情报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 20px; line-height: 1.5; }}
        h1 {{ font-size: 1.8rem; border-bottom: 1px solid #eaecef; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #dfe2e5; padding: 8px 10px; text-align: left; vertical-align: top; }}
        th {{ background-color: #f6f8fa; }}
        a {{ color: #0366d6; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #6a737d; }}
    </style>
    {login_script}
</head>
<body>
<h1>📊 内容安全行业舆情报告</h1>
<p>生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
<div id="report">
{html_table}
</div>
<div class="footer">
    <p>注：本报告由 AI 基于过去24小时抓取的内容自动生成，仅供参考。</p>
</div>
</body>
</html>"""

def save_reports_with_history(report_text: str, all_articles: List[Dict], failed_sources: List[Tuple[str, str]]):
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    raw_count = len(all_articles)

    timestamp_str = f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    fetch_info = f"抓取数据：{raw_count}条\n\n"
    final_content = timestamp_str + fetch_info + report_text

    with open("report.md", "w", encoding="utf-8") as f:
        f.write(final_content)
    html_content = generate_html_report(report_text, all_articles)
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    os.makedirs("reports", exist_ok=True)
    history_path = f"reports/report_{timestamp}.html"
    with open(history_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    generate_index_page()
    os.makedirs("data", exist_ok=True)
    with open(f"data/raw_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)
    logger.info(f"报告已保存: report.html, report.md, 历史归档 {history_path}")

def generate_index_page():
    reports_dir = "reports"
    if not os.path.exists(reports_dir):
        return
    files = [f for f in os.listdir(reports_dir) if f.startswith("report_") and f.endswith(".html")]
    files.sort(reverse=True)
    index_html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>历史舆情报告</title>
<style>body { font-family: sans-serif; margin: 20px; } a { text-decoration: none; }</style>
</head>
<body><h1>历史舆情报告列表</h1><ul>"""
    for f in files:
        timestamp = f.replace("report_", "").replace(".html", "")
        if len(timestamp) == 15:
            display = f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]} {timestamp[9:11]}:{timestamp[11:13]}:{timestamp[13:15]} UTC"
        else:
            display = timestamp
        index_html += f'<li><a href="{f}" target="_blank">{display}</a></li>'
    index_html += "</ul><p><a href='../report.html'>查看最新报告</a></p></body></html>"
    with open(os.path.join(reports_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

def cleanup_old_files(days: int = KEEP_DAYS):
    cutoff = datetime.utcnow() - timedelta(days=days)
    data_dir = "data"
    if os.path.exists(data_dir):
        for f in os.listdir(data_dir):
            if f.startswith("raw_") and f.endswith(".json"):
                ts_part = f.replace("raw_", "").replace(".json", "")
                try:
                    file_time = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
                    if file_time < cutoff:
                        os.remove(os.path.join(data_dir, f))
                        logger.info(f"已删除旧数据文件: {f}")
                except ValueError:
                    continue
    reports_dir = "reports"
    if os.path.exists(reports_dir):
        for f in os.listdir(reports_dir):
            if f.startswith("report_") and f.endswith(".html"):
                ts_part = f.replace("report_", "").replace(".html", "")
                try:
                    file_time = datetime.strptime(ts_part, "%Y%m%d_%H%M%S")
                    if file_time < cutoff:
                        os.remove(os.path.join(reports_dir, f))
                        logger.info(f"已删除旧报告: {f}")
                except ValueError:
                    continue

# ================= 主流程 =================
def main():
    start = time.time()
    logger.info("=== 开始抓取信源（过去24小时） ===")
    all_articles, failed_sources = fetch_all_sources()
    logger.info(f"抓取完成，共 {len(all_articles)} 条有效文章，耗时 {time.time()-start:.1f} 秒")

    if not all_articles:
        logger.warning("未抓到任何文章")
        with open("report.md", "w") as f:
            f.write("# 抓取失败\n\n未抓到任何文章，请检查日志。")
        with open("report.html", "w") as f:
            f.write("<h1>抓取失败</h1><p>未抓到任何文章，请检查日志。</p>")
        log_failed_sources(failed_sources)
        return

    log_failed_sources(failed_sources)
    old_events = load_previous_events()
    event_counts = load_event_counts()
    event_counts = cleanup_old_events(event_counts)
    save_event_counts(event_counts)

    logger.info("=== 调用 AI 分析（并发优化） ===")
    report_table, events_in_report = call_ai_unified(all_articles, old_events)

    if report_table != "无相关内容。\n":
        lines = report_table.split("\n")
        header = lines[0] if lines else ""
        sep = lines[1] if len(lines) > 1 else ""
        table_rows = lines[2:] if len(lines) > 2 else []
        filtered_rows, new_counts = filter_by_repeat_count(table_rows, event_counts)
        save_event_counts(new_counts)
        if filtered_rows:
            final_table = "\n".join([header, sep] + filtered_rows)
        else:
            final_table = "无相关内容（所有事件已进入冷却期）。\n"
    else:
        final_table = report_table
        save_event_counts(event_counts)

    full_report = final_table
    save_reports_with_history(full_report, all_articles, failed_sources)
    logger.info(f"=== 清理超过 {KEEP_DAYS} 天的旧文件 ===")
    cleanup_old_files()
    logger.info(f"全部完成，总耗时 {time.time()-start:.1f} 秒")

if __name__ == "__main__":
    main()
