#!/usr/bin/env python3
# crawler.py - 多 RSSHub 实例故障转移 + 完整 AI 分析/报告生成
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
MAX_WORKERS = 4          # 降低并发
AI_REQUEST_DELAY = 2
EVENT_EXPIRE_DAYS = 60

EVENT_COUNTS_FILE = "event_counts.json"
FAILED_SOURCES_LOG = "failed_sources.json"
DISABLED_SOURCES_FILE = "disabled_sources.json"

# 稳定的 RSSHub 实例列表（按优先级排序）
RSSHUB_INSTANCES = [
    "https://hub.slarker.me",
    "https://rsshub.pseudoyu.com",
    "https://rsshub.rssforever.com",
    "https://rsshub.woodland.cafe",
    "https://rss.owo.nz",
    "https://yangzhi.app"
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
    # 替换各种 RSSHub 实例域名为 x.com
    for inst in RSSHUB_INSTANCES:
        domain = inst.replace("https://", "")
        link = link.replace(domain, "x.com")
    # 替换 Nitter 等
    replacements = [
        ("nitter.net", "x.com"), ("twitter.net", "x.com"), ("nitter.poast.org", "x.com"),
        ("nitter.private.coffee", "x.com"), ("nitter.42l.fr", "x.com"),
        ("nitter.space", "x.com"), ("xcancel.com", "x.com"),
    ]
    for old, new in replacements:
        link = link.replace(old, new)
    # 提取推文真实链接
    match = re.search(r'/twitter/user/([^/]+)/status/(\d+)', link)
    if match:
        username = match.group(1)
        tweet_id = match.group(2)
        link = f"https://x.com/{username}/status/{tweet_id}"
    else:
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

# ================= 禁用机制（永不禁用） =================
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
def fetch_url(url: str, timeout: int = 30, headers: Optional[Dict] = None) -> requests.Response:
    headers = headers or {"User-Agent": random.choice(USER_AGENTS), "Accept": "*/*"}
    resp = requests.get(url, headers=headers, timeout=timeout, proxies=PROXIES)
    resp.raise_for_status()
    return resp

# ================= 抓取核心（多实例降级）=================
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
            domain_match = re.search(r'https?://([^/]+)', original_url)
            raw_domain = domain_match.group(1) if domain_match else original_url
            source_name = raw_domain
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
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        logger.error(f"抓取异常 {original_url} (RSS: {rss_url}): {e}")
        return []

def fetch_with_failover(original_url: str, processed_hashes: set, time_window_hours: int) -> List[Dict]:
    if is_source_disabled(original_url):
        return []
    # 如果是 RSSHub 的 Twitter 路由，尝试多实例
    if "/twitter/user/" in original_url:
        match = re.search(r'/twitter/user/([^/?]+)', original_url)
        if not match:
            return fetch_single_rss(original_url, original_url, processed_hashes, time_window_hours)
        username = match.group(1)
        # 提取查询参数
        query = ""
        if "?" in original_url:
            query = "?" + original_url.split("?", 1)[1]
        for inst in RSSHUB_INSTANCES:
            test_url = f"{inst}/twitter/user/{username}{query}"
            logger.debug(f"尝试 RSSHub 实例: {test_url}")
            items = fetch_single_rss(test_url, original_url, processed_hashes, time_window_hours)
            if items:
                logger.info(f"实例 {inst} 成功抓取 @{username}")
                return items
            time.sleep(1)  # 避免过快重试
        logger.warning(f"所有 RSSHub 实例均无法抓取 @{username}")
        return []
    else:
        return fetch_single_rss(original_url, original_url, processed_hashes, time_window_hours)

def fetch_all_sources() -> Tuple[List[Dict], List[Tuple[str, str]]]:
    logger.info(f"开始抓取 {len(RAW_SOURCES)} 个信源")
    all_items = []
    processed_hashes = set()
    failed_sources = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_with_failover, url, processed_hashes, TIME_WINDOW_MAP.get(url, 24)): url
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

# ================= 历史事件加载 =================
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

def deduplicate_and_mark_new(rows: List[str], old_events: List[str]) -> Tuple[List[str], List[str]]:
    events_data = []
    for row in rows:
        cells = [c.strip() for c in row.split("|")[1:-1]]
        if len(cells) != 5:
            continue
        event = cells[0]
        link = cells[1]
        risk = cells[2]
        source = cells[3]
        time_ago = cells[4]
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
        events_data.append((event, source, link, risk, time_ago, pub_dt, row))

    merged = []
    used = [False] * len(events_data)
    for i, (event_i, src_i, link_i, risk_i, time_ago_i, pub_dt_i, row_i) in enumerate(events_data):
        if used[i]:
            continue
        group = [(event_i, src_i, link_i, risk_i, time_ago_i, pub_dt_i, row_i)]
        for j, (event_j, src_j, link_j, risk_j, time_ago_j, pub_dt_j, row_j) in enumerate(events_data):
            if i == j or used[j]:
                continue
            if is_similar(event_i, event_j):
                group.append((event_j, src_j, link_j, risk_j, time_ago_j, pub_dt_j, row_j))
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
            event, src, link, risk, time_ago, pub_dt, row = item
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
        first_event, first_src, first_link, first_risk, first_time_ago, _, _ = best_item
        sources = sorted(set([s for _, s, _, _, _, _, _ in group]))
        source_count = len(sources)
        source_display = "、".join(sources) if source_count <= 3 else f"{source_count}个信源"
        event_text = first_event
        if source_count > 1:
            event_text = f"{event_text}（{source_count}个信源）"
        new_cells = [event_text, first_link, first_risk, source_display, first_time_ago]
        new_row = "| " + " | ".join(new_cells) + " |"
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
        if len(cells) != 5:
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
            client = openai.OpenAI(base_url=AI_BASE_URL, api_key=GH_TOKEN)
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
    prompt_prefix = """你是一名专业的网络安全和舆情分析师。你的任务是：从以下内容中筛选出**涉及中国的负面舆情**，并按重要性输出报告。

**一、请严格遵守以下过滤规则（忽略极低价值内容）**：
- 纯转发（RT/转发）且无新增实质性评论。
- 仅包含链接，无任何文字说明或文字少于10个字符。
- 仅含表情符号、无意义的感叹或口号（如"太可怕了""支持"等）。
- 明显重复的内容（同一事件在不同批次中出现，只保留一次）。
- 与涉华负面舆情无关的个人生活、娱乐、广告等。

**二、必须保留的内容（不得忽略）**：
- 任何涉及中国境内的社会事件、政策批评、执法争议、文化冲突、教育问题、言论管控、隐私侵犯等，只要带有负面或批评倾向，都应视为涉华负面舆情。
- 即使内容没有直接提及"中国"或"中共"，但事件发生在中国境内或涉及中国公民，也应保留。
- 对于不确定是否涉华的内容，请优先保留，不要轻易过滤。

**三、输出格式要求**：
- 使用 Markdown 表格，表头为：`| 事件简述 | 原文链接 | 潜在风险点 | 信息来源 | 发布多久前 |`
- 每行一条负面内容，按以下优先级排序：
  1. 来自官方机构、智库、政府部门的报告类内容。
  2. 其他有实质分析的负面新闻或推文。
- 原文链接列使用 `[查看](URL)` 格式。
- "信息来源"列使用输入中提供的"来源"名称（已转换为中文）。
- "发布多久前"列直接使用输入中的"发布时间"。
- 如果没有任何符合要求的涉华负面内容，只输出一行"无"。
- 不要添加任何额外解释、标题或总结。

**四、风险点要求**：
- 每条风险点应包含类别（如"社会维稳""教育管控""文化冲突""执法争议"等）和简要说明，总字数不超过30字。

以下是抓取到的部分内容：\n\n"""
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
    table_header = "| 事件简述 | 原文链接 | 潜在风险点 | 信息来源 | 发布多久前 |"
    table_sep = "|----------|----------|------------|----------|------------|"
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
                if len(cells) == 5:
                    all_table_rows.append(line)
        time.sleep(AI_REQUEST_DELAY)

    if not all_table_rows:
        return "无相关内容。\n", []

    unique_rows, events_in_report = deduplicate_and_mark_new(all_table_rows, old_events)
    final_table = "\n".join([table_header, table_sep] + unique_rows)
    return final_table, events_in_report

# ================= 报告生成 =================
def generate_html_report(report_text: str, all_articles: List[Dict]) -> str:
    lines = report_text.split("\n")
    html_table = ""
    in_table = False
    for line in lines:
        if line.startswith("|") and "|" in line:
            if not in_table:
                html_table += '<tr>\n<thead>\n'
                in_table = True
            if re.match(r'^\|[\s\-:]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if len(cells) != 5:
                continue
            html_table += "<tr>\n"
            for cell in cells:
                link_match = re.search(r'\[(.*?)\]\((.*?)\)', cell)
                if link_match:
                    text, url = link_match.group(1), link_match.group(2)
                    cell = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{text}</a>'
                html_table += f"<td>{cell}</td>\n"
            html_table += "<tr>\n"
        else:
            if in_table:
                html_table += "</thead><tbody></tbody></tr>\n"
                in_table = False
    if in_table:
        html_table += "</thead><tbody></tbody></table>\n"

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
    timestamp_str = f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
    final_content = timestamp_str + report_text

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
    for dir_name in ["reports", "data"]:
        if not os.path.exists(dir_name):
            continue
        for f in os.listdir(dir_name):
            filepath = os.path.join(dir_name, f)
            try:
                mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                if mtime < cutoff:
                    os.remove(filepath)
                    logger.info(f"已删除旧文件: {filepath}")
            except Exception as e:
                logger.warning(f"删除文件 {filepath} 失败: {e}")

# ================= 主函数 =================
def main():
    start = time.time()
    logger.info("=== 开始抓取信源 ===")
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

    logger.info("=== 调用 AI 分析 ===")
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
