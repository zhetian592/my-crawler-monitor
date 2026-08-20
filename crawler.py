# crawler.py - 适配本地 RSS 代理版（稳定优化）
import os
import json
import re
import time
import random
import hashlib
import logging
import sys
import threading
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple, Optional, Union
from logging.handlers import RotatingFileHandler

import requests
import feedparser
import openai
from bs4 import BeautifulSoup
import difflib

# 尝试导入 tiktoken
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

# ================= 日志配置（轮转） =================
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
API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("GH_MODELS_TOKEN_NEW") or os.environ.get("OPENAI_API_KEY")
if not API_KEY:
    logger.warning("未设置 OPENAI_API_KEY，AI 功能不可用")

AI_BASE_URL = os.environ.get("OPENAI_BASE_URL", "https://api.chatanywhere.tech/v1")
AI_MODEL = os.environ.get("AI_MODEL", "gpt-4o-mini")

REPORT_PASSWORD = os.environ.get("REPORT_PASSWORD", "yangge233")
PROXIES = None
if os.environ.get("HTTP_PROXY"):
    PROXIES = {"http": os.environ["HTTP_PROXY"], "https": os.environ.get("HTTPS_PROXY", os.environ["HTTP_PROXY"])}

KEEP_DAYS = 2
SIMILARITY_THRESHOLD = 0.6
MAX_REPEAT_COUNT = 3
COOLDOWN_DAYS = 7
MAX_WORKERS = 3                      # 降低并发，避免限流
AI_REQUEST_DELAY = 2
DISABLE_FAILED_THRESHOLD = 5         # 提高阈值
DISABLE_COOLDOWN_MINUTES = 60        # 延长禁用时间
DISABLE_AUTO_RECOVER_DAYS = 7
EVENT_EXPIRE_DAYS = 60

EVENT_COUNTS_FILE = "event_counts.json"
HEALTHY_NITTER_FILE = "healthy_nitter.json"
HEALTHY_RSSHUB_FILE = "healthy_rsshub.json"
FAILED_SOURCES_LOG = "failed_sources.json"
DISABLED_SOURCES_FILE = "disabled_sources.json"
URL_DEDUP_FILE = "url_dedup.json"

# ====== 新增：本地 RSS 代理地址 ======
PROXY_BASE = os.environ.get("RSS_PROXY_BASE", "http://localhost:1200")   # 与 rss_proxy.py 端口一致

# 备用 Nitter 实例（仅当代理不可用时使用）
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

def convert_to_official_x_link(link: str) -> str:
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
        {"url": "https://x.com/zaobaosg", "time_window_hours": 24},
        {"url": "https://x.com/wangzhian8848", "time_window_hours": 24},
        {"url": "https://x.com/wangdan1989", "time_window_hours": 24},
        {"url": "https://x.com/fangshimin", "time_window_hours": 24},
        {"url": "https://x.com/FDD", "time_window_hours": 24},
        {"url": "https://x.com/NTDChinese", "time_window_hours": 24},
        {"url": "https://www.hrw.org/rss/news", "time_window_hours": 24},
        {"url": "https://www.amnesty.org/en/feed/", "time_window_hours": 24},
        {"url": "https://www.fdd.org/feed/", "time_window_hours": 24},
        {"url": "https://www.brookings.edu/feed/?topic=china", "time_window_hours": 24},
        {"url": "https://www.freedomhouse.org/rss.xml", "time_window_hours": 24},
        {"url": "https://www.aspistrategist.org.au/feed/", "time_window_hours": 24},
        {"url": "https://chinapower.csis.org/feed/", "time_window_hours": 24},
        {"url": "https://carnegieendowment.org/rss", "time_window_hours": 24},
        {"url": "https://www.uscc.gov/rss.xml", "time_window_hours": 24},
        {"url": "https://merics.org/en/rss.xml", "time_window_hours": 24},
        {"url": "https://rsf.org/en/rss.xml", "time_window_hours": 24},
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
        self.lock = threading.Lock()

    def record_fail(self, source_key):
        with self.lock:
            self.fail_counts[source_key] = self.fail_counts.get(source_key, 0) + 1
            if self.fail_counts[source_key] >= self.max_fails:
                self.disabled_until[source_key] = time.time() + self.cooldown
                logger.warning(f"信源 {source_key} 连续失败{self.fail_counts[source_key]}次，已暂时禁用 {self.cooldown//60} 分钟")

    def record_success(self, source_key):
        with self.lock:
            if source_key in self.disabled_until:
                logger.info(f"信源 {source_key} 已恢复可用")
                del self.disabled_until[source_key]
            self.fail_counts[source_key] = 0

    def is_disabled(self, source_key):
        with self.lock:
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
        self.lock = threading.Lock()

    def get_next(self):
        with self.lock:
            if not self.available:
                logger.warning("所有镜像均已失败，重置池")
                self.available = list(self.original)
            url = self.available.pop(0)
            return url

    def report_failure(self, url):
        with self.lock:
            if url in self.available:
                self.available.remove(url)

    def report_success(self, url):
        pass

nitter_health = SourceHealth(max_fails=DISABLE_FAILED_THRESHOLD, cooldown_minutes=DISABLE_COOLDOWN_MINUTES)

def get_nitter_instances() -> List[str]:
    # 从健康文件读取，若没有则使用 fallback
    if os.path.exists(HEALTHY_NITTER_FILE):
        try:
            with open(HEALTHY_NITTER_FILE, 'r', encoding='utf-8') as f:
                instances = json.load(f)
                if isinstance(instances, list) and instances:
                    return [inst for inst in instances if not nitter_health.is_disabled(inst)]
        except Exception as e:
            logger.warning(f"读取 {HEALTHY_NITTER_FILE} 失败: {e}")
    return [inst for inst in FALLBACK_NITTER_INSTANCES if not nitter_health.is_disabled(inst)]

def update_nitter_health(instance_url: str, success: bool):
    if success:
        nitter_health.record_success(instance_url)
    else:
        nitter_health.record_fail(instance_url)

# ================ URL去重缓存 ================
class URLDedupCache:
    def __init__(self, cache_file=URL_DEDUP_FILE):
        self.cache_file = cache_file
        self.url_set = set()
        self.bloom = None
        self.lock = threading.Lock()
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
        with self.lock:
            if self.bloom:
                return url in self.bloom
            return url in self.url_set

    def add(self, url: str):
        with self.lock:
            if self.bloom:
                self.bloom.add(url)
            else:
                self.url_set.add(url)

    def save(self):
        with self.lock:
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

# ================= 网络请求重试（增强版） =================
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

@retry_on_exception(max_retries=3, delay=2, backoff=2)
def fetch_url(url: str, timeout: int = 25, headers: Optional[Dict] = None) -> requests.Response:
    headers = headers or {"User-Agent": random.choice(USER_AGENTS)}
    resp = requests.get(url, headers=headers, timeout=timeout, proxies=PROXIES)
    # 特殊处理 429
    if resp.status_code == 429:
        wait = 60 + random.randint(0, 30)
        logger.warning(f"收到 429，等待 {wait}s 后重试")
        time.sleep(wait)
        return fetch_url(url, timeout, headers)   # 递归重试一次
    resp.raise_for_status()
    return resp

# ================= 抓取核心（使用本地代理） =================
def url_to_rss(url: str) -> Union[str, List[str], None]:
    """
    将原始信源 URL 映射到本地 RSS 代理服务的路由。
    如果代理不可用，可以回退到原始 RSS 或 Nitter（但本版本优先代理）。
    """
    # 由于现在主要使用本地代理，我们直接生成代理路径
    # 注意：代理服务已内置直接 RSS、HTML 抓取、Twitter 代理功能
    if "x.com/" in url or "twitter.com/" in url:
        # 提取用户名
        parts = url.split("/")
        username = parts[-1] if parts[-1] else parts[-2]
        return f"{PROXY_BASE}/twitter/user/{username}"

    # 基于域名或路径映射
    if "bbc.com/zhongwen/simp" in url:
        return f"{PROXY_BASE}/bbc"
    if "dw.com/zh" in url:
        return f"{PROXY_BASE}/dw"
    if "rfi.fr/cn" in url:
        return f"{PROXY_BASE}/rfi"
    if "cn.nytimes.com" in url:
        return f"{PROXY_BASE}/nytimes"
    if "ntdtv.com" in url:
        return f"{PROXY_BASE}/ntdtv/instant-news"
    if "epochtimes.com" in url:
        return f"{PROXY_BASE}/epochtimes"         # 代理会 302 到原始 RSS
    if "zaobao.com" in url:
        if "realtime" in url:
            return f"{PROXY_BASE}/zaobao/realtime"
        else:
            return f"{PROXY_BASE}/zaobao/znews"
    # 以下信源在代理中都有直接 RSS 映射（键名与路径一致）
    if "hrw.org" in url:
        return f"{PROXY_BASE}/hrw"
    if "amnesty.org" in url:
        return f"{PROXY_BASE}/amnesty"
    if "fdd.org" in url:
        return f"{PROXY_BASE}/fdd"
    if "brookings.edu" in url:
        return f"{PROXY_BASE}/brookings"
    if "freedomhouse.org" in url:
        return f"{PROXY_BASE}/freedomhouse"
    if "aspistrategist.org.au" in url:
        return f"{PROXY_BASE}/aspistrategist"
    if "chinapower.csis.org" in url:
        return f"{PROXY_BASE}/chinapower"
    if "carnegieendowment.org" in url:
        return f"{PROXY_BASE}/carnegieendowment"
    if "uscc.gov" in url:
        return f"{PROXY_BASE}/uscc"
    if "merics.org" in url:
        return f"{PROXY_BASE}/merics"
    if "rsf.org" in url:
        return f"{PROXY_BASE}/rsf"
    # 对于其他未映射的信源，尝试让代理泛化转发给 RSSHub（如果代理支持 /rsshub/ 路径）
    # 但代理中没有实现泛化转发，我们可以尝试返回原始 URL 或使用 RSSHub 公共实例
    # 更稳妥的是返回 None，由调用方处理
    logger.warning(f"未在代理中映射的信源: {url}，将尝试直接使用原始 RSS 或 RSSHub")
    # 尝试用公共 RSSHub 兜底（但可能不稳定）
    # 这里简单返回 None，让上层尝试其他方式
    return None

def fetch_single_rss(rss_url: str, original_url: str, processed_hashes: set, url_cache: URLDedupCache, time_window_hours: int) -> List[Dict]:
    # 增加随机延迟，避免请求突发
    time.sleep(random.uniform(0.5, 2.5))
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
            link = entry.get("link", "")
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
            if "x.com/" in original_url or "twitter.com/" in original_url:
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

    # 首先尝试通过本地代理获取
    rss_candidate = url_to_rss(original_url)
    if rss_candidate:
        # 若是列表则取第一个，但这里返回的是字符串
        rss_url = rss_candidate
        items = fetch_single_rss(rss_url, original_url, processed_hashes, url_cache, time_window_hours)
        if items:
            logger.debug(f"{original_url} 通过代理成功 (条数: {len(items)})")
            return items
        else:
            logger.debug(f"{original_url} 通过代理失败，尝试其他方式")

    # 若代理失败，尝试原始 Nitter 或 RSSHub 兜底（仅对 Twitter 和部分站点）
    if "x.com/" in original_url or "twitter.com/" in original_url:
        username = original_url.split("/")[-1]
        nitter_pool = MirrorPool(get_nitter_instances())
        while True:
            try:
                instance = nitter_pool.get_next() if nitter_pool.available else None
                if not instance:
                    break
                test_url = f"{instance}/{username}/rss"
                logger.debug(f"尝试 X {username} 使用 Nitter {instance} (兜底)")
                items = fetch_single_rss(test_url, original_url, processed_hashes, url_cache, time_window_hours)
                if items:
                    logger.debug(f"X {username} 成功 via Nitter {instance} (条数: {len(items)})")
                    update_nitter_health(instance, True)
                    return items
                else:
                    logger.debug(f"X {username} 失败 via Nitter {instance}")
                    update_nitter_health(instance, False)
                    nitter_pool.report_failure(instance)
            except Exception:
                break
            time.sleep(0.5)
        logger.debug(f"X {username} 所有备用方式均失败")
        return []

    # 对于其他信源，如果代理返回 None，直接返回空
    logger.debug(f"无法获取 {original_url} 的有效 RSS 地址")
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

# ================= AI 分析 =================
def estimate_tokens(text: str) -> int:
    if TIKTOKEN_AVAILABLE:
        enc = tiktoken.encoding_for_model("gpt-4o-mini")
        return len(enc.encode(text))
    else:
        return int(len(text) / 1.5)

def call_ai_with_retry(prompt: str, max_retries: int = 3) -> Optional[str]:
    for attempt in range(max_retries):
        try:
            client = openai.OpenAI(base_url=AI_BASE_URL, api_key=API_KEY)
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=4000,
            )
            content = response.choices[0].message.content
            if content is not None:
                return content
        except Exception as e:
            logger.warning(f"AI 调用尝试 {attempt+1}/{max_retries} 失败: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)
    return None

def call_ai_unified(articles: List[Dict], old_events: List[str]) -> Tuple[str, List[str]]:
    if not articles:
        return "无相关内容。\n", []

    blocks = []
    for art in articles:
        meta = f"发布时间：{art.get('time_ago', '未知')} | 来源：{get_display_source(art.get('source_name', '未知'))}"
        block = f"{meta}\n标题：{art.get('title', '')[:150]}\n摘要：{art.get('summary', '')[:300]}\n链接：{art.get('link', '')}\n"
        blocks.append(block)

    batches = []
    current_batch = []
    current_tokens = 0
    prompt_prefix = """你是一名专业的舆情风险分析师，专注于涉华负面信息研判。从以下内容中筛选涉华负面舆情，输出 Markdown 表格。

**核心规则**：
- 忽略：纯转发无评论、仅链接无文字、纯表情/口号、无关生活娱乐、明显重复。
- 保留：任何涉及中国境内的社会事件、政策批评、执法争议、文化冲突、教育问题、言论管控等带有负面或批评倾向的内容。不确定的优先保留。

**输出格式**：
| 事件简述 | 原文链接 | 风险点 | 信息来源 | 发布多久前 | 风险等级 |
- 链接格式：`[查看](URL)`
- 风险等级：高/中/低（高=重大政治敏感且传播力强；中=较敏感社会议题；低=一般性批评）
- 无内容时只输出一行"无"
- 不要添加任何额外解释

**事件简述撰写要求（最重要）**：
- 必须完整概括事件的核心要素：**什么人/机构 + 做了什么/发生了什么事 + 在什么地点或背景下**。
- 保留关键细节（如数字、地点、涉事主体等），**长度建议20-40字**，确保读者仅看事件简述就能理解事件全貌。
- 示例（好）："广西桂林暴雨致部分村庄被淹，当地政府启动三级应急响应，灾民已转移至安置点"
- 示例（差）："广西暴雨"（太短，信息不全）

**风险点要求**：
- 从该事件可能引发的舆情风险中，提炼**最重要、最核心的一条风险**，用一句话概括，**不超过15字**。
- 不要分点，只写一条。
- 示例："可能引发公众对执法公正性的质疑"

以下是抓取到的内容：\n\n"""
    prompt_tokens = estimate_tokens(prompt_prefix)
    max_content_tokens = 10000
    for block in blocks:
        block_tokens = estimate_tokens(block)
        if current_tokens + block_tokens + prompt_tokens > max_content_tokens and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        current_batch.append(block)
        current_tokens += block_tokens
    if current_batch:
        batches.append(current_batch)

    logger.info(f"共 {len(articles)} 条内容，分为 {len(batches)} 批进行 AI 分析")

    all_table_rows = []
    table_header = "| 事件简述 | 原文链接 | 风险点 | 信息来源 | 发布多久前 | 风险等级 |"
    table_sep = "|----------|----------|--------|----------|------------|------------|"
    for batch_idx, batch in enumerate(batches, 1):
        combined = "\n".join(batch)
        prompt = prompt_prefix + combined
        content = call_ai_with_retry(prompt)
        if content is None:
            logger.error(f"AI 分析批次 {batch_idx} 重试失败，跳过")
            continue
        lines = content.split("\n")
        in_table = False
        for line in lines:
            if line.startswith("|") and "|" in line:
                if not in_table:
                    in_table = True
                if re.match(r'^\|[\s\-:]+\|$', line):
                    continue
                if line.startswith(table_header):
                    continue
                cells = [c.strip() for c in line.split("|")[1:-1]]
                if len(cells) == 6:
                    all_table_rows.append(line)
        time.sleep(AI_REQUEST_DELAY)

    if not all_table_rows:
        return "无相关内容。\n", []

    unique_rows, events_in_report = deduplicate_and_mark_new(all_table_rows, old_events)
    final_table = "\n".join([table_header, table_sep] + unique_rows)
    return final_table, events_in_report

def deduplicate_and_mark_new(rows: List[str], old_events: List[str]) -> Tuple[List[str], List[str]]:
    events_data = []
    for row in rows:
        cells = [c.strip() for c in row.split("|")[1:-1]]
        if len(cells) != 6:
            continue
        event = cells[0]
        link = cells[1]
        risk = cells[2]
        source = cells[3]
        time_ago = cells[4]
        risk_level = cells[5]
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
    for i, (event_i, src_i, link_i, risk_i, time_ago_i, risk_level_i, pub_dt_i, row_i) in enumerate(events_data):
        if used[i]:
            continue
        group = [(event_i, src_i, link_i, risk_i, time_ago_i, risk_level_i, pub_dt_i, row_i)]
        for j, (event_j, src_j, link_j, risk_j, time_ago_j, risk_level_j, pub_dt_j, row_j) in enumerate(events_data):
            if i == j or used[j]:
                continue
            if is_similar(event_i, event_j):
                group.append((event_j, src_j, link_j, risk_j, time_ago_j, risk_level_j, pub_dt_j, row_j))
                used[j] = True
        used[i] = True
        merged.append(group)

    unique_rows = []
    events_in_report = []
    for group in merged:
        best_item = None
        best_pub = None
        best_priority = 999
        for item in group:
            event, src, link, risk, time_ago, risk_level, pub_dt, row = item
            priority = get_source_priority(src)
            if best_item is None:
                best_item = item
                best_pub = pub_dt
                best_priority = priority
            else:
                if pub_dt and best_pub:
                    if pub_dt > best_pub:
                        best_item = item
                        best_pub = pub_dt
                        best_priority = priority
                    elif pub_dt == best_pub and priority < best_priority:
                        best_item = item
                        best_pub = pub_dt
                        best_priority = priority
                elif pub_dt and not best_pub:
                    best_item = item
                    best_pub = pub_dt
                    best_priority = priority
                elif not pub_dt and best_pub:
                    pass
                else:
                    if priority < best_priority:
                        best_item = item
                        best_pub = pub_dt
                        best_priority = priority
        first_event, first_src, first_link, first_risk, first_time_ago, first_risk_level, _, _ = best_item
        sources = sorted(set([s for _, s, _, _, _, _, _, _ in group]))
        source_count = len(sources)
        source_display = "、".join(sources) if source_count <= 3 else f"{source_count}个信源"
        event_text = first_event
        if source_count > 1:
            event_text = f"{event_text}（{source_count}个信源）"
        new_cells = [event_text, first_link, first_risk, source_display, first_time_ago, first_risk_level]
        is_new = True
        for old in old_events:
            if is_similar(first_event, old):
                is_new = False
                break
        if is_new:
            new_cells[0] = "🆕 " + new_cells[0]
        new_row = "| " + " | ".join(new_cells) + " |"
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
                logger.info(f"隐藏重复事件（冷却期内）: {event[:50]}")
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
                link_match = re.search(r'\[(.*?)\]\((.*?)\)', cell)
                if link_match:
                    text, url = link_match.group(1), link_match.group(2)
                    cell = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{text}</a>'
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

    logger.info("=== 调用 AI 分析（统一分析，AI 自动识别报告并优先展示） ===")
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
