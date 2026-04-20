#!/usr/bin/env python3
# crawler.py - 舆情监控爬虫（优化版）
# 依赖：requests, feedparser, beautifulsoup4, openai, tiktoken (可选)
import os
import json
import re
import time
import random
import hashlib
import logging
import sys
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Tuple, Optional

import requests
import feedparser
import openai
from bs4 import BeautifulSoup
import difflib

# 尝试导入 tiktoken（用于精确 token 估算）
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False

# ================= 日志配置 =================
LOG_FILE = "crawler.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# ================= 配置常量 =================
# GitHub Models API
GH_TOKEN = os.environ.get("GH_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
AI_BASE_URL = "https://models.inference.ai.azure.com"
AI_MODEL = "gpt-4o-mini"

# 报告密码（可从环境变量覆盖）
REPORT_PASSWORD = os.environ.get("REPORT_PASSWORD", "yangge233")

# 代理（可选）
PROXIES = None
if os.environ.get("HTTP_PROXY"):
    PROXIES = {
        "http": os.environ["HTTP_PROXY"],
        "https": os.environ.get("HTTPS_PROXY", os.environ["HTTP_PROXY"])
    }

# 数据保留天数
KEEP_DAYS = 7
# 相似度去重阈值
SIMILARITY_THRESHOLD = 0.5
# 跨天重复隐藏参数
MAX_REPEAT_COUNT = 3
COOLDOWN_DAYS = 7

# 文件路径
EVENT_COUNTS_FILE = "event_counts.json"
HEALTHY_NITTER_FILE = "healthy_nitter.json"
FAILED_SOURCES_LOG = "failed_sources.json"

# 默认 RSSHub 实例列表（当无法获取健康实例时使用）
DEFAULT_RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.ktachibana.party"
]

# 备用 Nitter 实例（当 healthy_nitter.json 不存在或为空时使用）
FALLBACK_NITTER_INSTANCES = [
    "https://xcancel.com",
    "https://nitter.tiekoetter.com",
    "https://nitter.catsarch.com"
]

# 并发抓取线程数
MAX_WORKERS = 6

# ================= 外部化配置加载 =================
def load_sources() -> List[str]:
    """加载信源列表（支持 JSON 外部文件，否则使用硬编码）"""
    sources_file = "sources.json"
    if os.path.exists(sources_file):
        with open(sources_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 默认硬编码信源（已移除 RFA 等不稳定源）
    return [
        "https://www.bbc.com/zhongwen/simp",
        "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
        "https://www.rfi.fr/cn/",
        "https://cn.nytimes.com/",
        "https://www.ntdtv.com/gb/instant-news.html",
        "https://www.epochtimes.com/gb/instant-news.htm",
        "https://x.com/whyyoutouzhele",
        "https://x.com/wangzhian8848",
        "https://x.com/newszg_official",
        "https://x.com/wangdan1989",
        "https://x.com/torontobigface",
        "https://x.com/hrw_chinese",
        "https://x.com/dayangelcp",
        "https://x.com/xinwendiaocha",
        "https://x.com/xiaojingcanxue",
        "https://x.com/ZhouFengSuo",
        "https://x.com/lidangzzz",
        "https://x.com/fangshimin",
        "https://x.com/UHRP_Chinese",
        "https://x.com/jhf8964",
        "https://x.com/liangziyueqian1",
        "https://x.com/badiucao",
        "https://x.com/wurenhua",
        "https://x.com/zaobaosg",
        "https://x.com/dajiyuan",
        "https://x.com/NTDChinese",
        "https://x.com/VOAChinese",
        "https://x.com/USCC_GOV",
        "https://x.com/ODNIgov",
        "https://x.com/ChinaSelect",
        "https://x.com/CNASdc",
        "https://x.com/hrw",
        "https://x.com/amnesty",
        "https://x.com/FreedomHouse",
        "https://x.com/ASPI_org",
        "https://x.com/CECCgov",
    ]

def load_source_map() -> Dict[str, str]:
    """加载信源名称映射（支持 JSON 外部文件）"""
    map_file = "source_map.json"
    if os.path.exists(map_file):
        with open(map_file, 'r', encoding='utf-8') as f:
            return json.load(f)
    # 默认映射（部分示例）
    return {
        "whyyoutouzhele": "李老师不是你老师啊",
        "wangzhian8848": "王局志安",
        "newszg_official": "新闻调查",
        "wangdan1989": "王丹",
        "torontobigface": "大脸撑在小胸上",
        "hrw_chinese": "人权观察中文",
        "dayangelcp": "大天使",
        "xinwendiaocha": "新闻调查",
        "xiaojingcanxue": "小警犬",
        "ZhouFengSuo": "周锋锁",
        "lidangzzz": "李老师不是你老师啊",
        "fangshimin": "方世民",
        "UHRP_Chinese": "UHRP中文",
        "jhf8964": "静好",
        "liangziyueqian1": "量子跃迁",
        "badiucao": "巴丢草",
        "wurenhua": "吴仁华",
        "zaobaosg": "联合早报",
        "dajiyuan": "大纪元",
        "NTDChinese": "新唐人",
        "VOAChinese": "美国之音中文",
        "USCC_GOV": "美中经济安全审查委员会",
        "ODNIgov": "国家情报总监办公室",
        "ChinaSelect": "众院中国问题特设委员会",
        "CNASdc": "新美国安全中心",
        "hrw": "人权观察",
        "amnesty": "国际特赦组织",
        "FreedomHouse": "自由之家",
        "ASPI_org": "澳大利亚战略政策研究所",
        "CECCgov": "国会-行政部门中国委员会",
        "bbc.com": "BBC中文",
        "dw.com": "德国之声",
        "rfi.fr": "法国国际广播电台",
        "cn.nytimes.com": "纽约时报中文网",
        "ntdtv.com": "新唐人",
        "epochtimes.com": "大纪元",
    }

RAW_SOURCES = load_sources()
SOURCE_NAME_MAP = load_source_map()

def get_display_source(source_name: str) -> str:
    """将原始来源名转换为友好显示名"""
    if source_name.startswith("@") and len(source_name) > 1:
        username = source_name[1:]
        if username in SOURCE_NAME_MAP:
            return SOURCE_NAME_MAP[username]
        return source_name
    for domain, display in SOURCE_NAME_MAP.items():
        if domain in source_name:
            return display
    return source_name

# ================= 工具函数 =================
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
    """将 Nitter 链接转换为官方 X 链接"""
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

def url_to_rss(url: str, rsshub_instance: str) -> Any:
    """根据原始 URL 返回 RSS 地址（支持单个或列表）"""
    if "voachinese.com" in url:
        return [f"{rsshub_instance}/voachinese/china", "http://feeds.feedburner.com/voacn"]
    if "bbc.com/zhongwen/simp" in url:
        return "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"
    if "dw.com/zh" in url:
        return "https://rss.dw.com/rdf/rss-chi-all"
    if "rfi.fr/cn" in url:
        return "https://www.rfi.fr/cn/general/rss"
    if "cn.nytimes.com" in url:
        return "https://cn.nytimes.com/rss/news.xml"
    if "ntdtv.com" in url:
        return [f"{rsshub_instance}/ntdtv/instant-news", "https://www.ntdtv.com/gb/feed"]
    if "epochtimes.com" in url:
        return [f"{rsshub_instance}/epochtimes/gb", "https://www.epochtimes.com/gb/feed"]
    if "x.com/" in url:
        return None
    if "uscc.gov" in url:
        return f"{rsshub_instance}/uscc/reports"
    return url

# ================= Nitter 实例获取 =================
def get_nitter_instances() -> List[str]:
    """获取可用的 Nitter 实例（优先从 healthy_nitter.json 读取，否则使用备用）"""
    if os.path.exists(HEALTHY_NITTER_FILE):
        try:
            with open(HEALTHY_NITTER_FILE, 'r', encoding='utf-8') as f:
                instances = json.load(f)
                if isinstance(instances, list) and instances:
                    logger.info(f"从 {HEALTHY_NITTER_FILE} 加载 {len(instances)} 个实例")
                    return instances
        except Exception as e:
            logger.warning(f"读取 {HEALTHY_NITTER_FILE} 失败: {e}")
    logger.warning(f"未找到健康实例文件，使用备用实例: {FALLBACK_NITTER_INSTANCES}")
    return FALLBACK_NITTER_INSTANCES

# ================= 抓取核心 =================
def fetch_single_rss(rss_url: str, original_url: str, processed_hashes: set) -> List[Dict]:
    """抓取单个 RSS 源，返回条目列表"""
    try:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        time.sleep(random.uniform(0.5, 1.8))
        resp = requests.get(rss_url, headers=headers, timeout=25, proxies=PROXIES)
        if resp.status_code != 200:
            logger.debug(f"HTTP {resp.status_code} - {original_url}")
            return []
        feed = feedparser.parse(resp.content)
        cutoff = datetime.utcnow() - timedelta(hours=24)
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
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        logger.error(f"抓取异常 {original_url}: {e}")
        return []

def fetch_with_retry(original_url: str, processed_hashes: set, nitter_instances: List[str], rsshub_instance: str) -> List[Dict]:
    """带重试的抓取，支持 X 账号多实例"""
    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        for nitter in nitter_instances:
            test_url = f"{nitter}/{username}/rss"
            logger.debug(f"尝试 X {username} 使用 {nitter}")
            items = fetch_single_rss(test_url, original_url, processed_hashes)
            if items:
                logger.info(f"X {username} 成功 via {nitter} (条数: {len(items)})")
                return items
            logger.debug(f"X {username} 失败 via {nitter}")
            time.sleep(0.5)
        logger.warning(f"X {username} 所有实例均失败")
        return []
    # 普通网站
    rss_candidates = url_to_rss(original_url, rsshub_instance)
    if not rss_candidates:
        logger.warning(f"无法生成 RSS 地址: {original_url}")
        return []
    if isinstance(rss_candidates, str):
        rss_candidates = [rss_candidates]
    for rss_url in rss_candidates:
        items = fetch_single_rss(rss_url, original_url, processed_hashes)
        if items:
            logger.info(f"{original_url} 成功 (条数: {len(items)}) via {rss_url}")
            return items
        logger.debug(f"{original_url} 失败 via {rss_url}")
        time.sleep(0.5)
    logger.warning(f"{original_url} 所有 RSS 地址均失败")
    return []

def fetch_all_sources() -> Tuple[List[Dict], List[Tuple[str, str]]]:
    """并发抓取所有信源，返回 (文章列表, 失败信源列表)"""
    logger.info(f"开始抓取 {len(RAW_SOURCES)} 个信源（过去24小时）")
    all_items = []
    processed_hashes = set()
    failed_sources = []
    nitter_instances = get_nitter_instances()
    # 随机选择一个 RSSHub 实例（简单轮换）
    rsshub_instances = DEFAULT_RSSHUB_INSTANCES
    rsshub_instance = random.choice(rsshub_instances)
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_url = {
            executor.submit(fetch_with_retry, url, processed_hashes, nitter_instances, rsshub_instance): url
            for url in RAW_SOURCES
        }
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                if items:
                    all_items.extend(items)
                    logger.info(f"✓ {url} -> {len(items)} 条")
                else:
                    failed_sources.append((url, "抓取返回0条"))
                    logger.warning(f"✗ {url} -> 0 条")
            except Exception as e:
                failed_sources.append((url, str(e)))
                logger.error(f"✗ {url} 异常: {e}")
    logger.info(f"去重后共 {len(all_items)} 条（已通过内容哈希去重）")
    return all_items, failed_sources

# ================= 持久化失败记录 =================
def log_failed_sources(failed_sources: List[Tuple[str, str]]):
    """将失败信源记录到 JSON 文件，按日期分组"""
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

# ================= 历史事件加载 =================
def load_previous_events() -> List[str]:
    """从上次生成的 report.md 中提取事件简述（用于新增标记）"""
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

# ================= 跨天重复隐藏 =================
def load_event_counts() -> Dict:
    if os.path.exists(EVENT_COUNTS_FILE):
        try:
            with open(EVENT_COUNTS_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 兼容旧格式（纯数字）
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

def cleanup_old_events(event_counts: Dict, days: int = 30) -> Dict:
    """删除 last_seen 超过 days 天的事件"""
    cutoff = datetime.utcnow().date() - timedelta(days=days)
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

def is_similar(a: str, b: str, threshold: float = SIMILARITY_THRESHOLD) -> bool:
    return difflib.SequenceMatcher(None, a, b).ratio() >= threshold

def deduplicate_and_mark_new(rows: List[str], old_events: List[str]) -> Tuple[List[str], List[str]]:
    """相似度去重，合并信源，标记新增"""
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
        events_data.append((event, source, link, risk, time_ago, row))

    merged = []
    used = [False] * len(events_data)
    for i, (event_i, src_i, link_i, risk_i, time_ago_i, row_i) in enumerate(events_data):
        if used[i]:
            continue
        group = [(event_i, src_i, link_i, risk_i, time_ago_i, row_i)]
        for j, (event_j, src_j, link_j, risk_j, time_ago_j, row_j) in enumerate(events_data):
            if i == j or used[j]:
                continue
            if is_similar(event_i, event_j):
                group.append((event_j, src_j, link_j, risk_j, time_ago_j, row_j))
                used[j] = True
        used[i] = True
        merged.append(group)

    unique_rows = []
    events_in_report = []
    for group in merged:
        first_event, first_src, first_link, first_risk, first_time_ago, _ = group[0]
        sources = sorted(set([s for _, s, _, _, _, _ in group]))
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
    """跨天重复隐藏（冷却期）"""
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
    """分批调用 AI，返回 Markdown 表格和事件列表"""
    if not articles:
        return "无相关内容。\n", []

    # 构建内容块
    blocks = []
    for art in articles:
        meta = f"发布时间：{art.get('time_ago', '未知')} | 来源：{get_display_source(art.get('source_name', '未知'))}"
        block = f"{meta}\n标题：{art.get('title', '')[:150]}\n摘要：{art.get('summary', '')[:300]}\n链接：{art.get('link', '')}\n"
        blocks.append(block)

    # 分批
    batches = []
    current_batch = []
    current_tokens = 0
    prompt_prefix = """你是一名专业的网络安全和舆情分析师。你的任务是：从以下内容中筛选出**涉及中国的负面舆情**。

**重要说明**：
- 请优先输出来自官方机构、智库、政府部门的报告类内容（如 USCC、HRW、Amnesty、ASPI 等），这类内容放在表格的前面。
- 对于普通新闻和普通 X 账号的内容，放在报告类内容之后。
- 输出使用 Markdown 表格格式，表格头为：| 事件简述 | 原文链接 | 潜在风险点 | 信息来源 | 发布多久前 |
- 每一条负面内容单独占一行。
- 原文链接列使用 `[查看](URL)` 格式。
- “信息来源”列请直接使用输入中提供的“来源”名称（已经转换为中文）。
- “发布多久前”列请直接使用输入中提供的“发布时间”字段（已经是易读格式，如“2小时前”）。
- 如果没有任何负面涉华内容，只输出一行“无”。
- 不要添加任何额外解释。

每条内容前已附带“发布时间”和“来源”，请利用这些信息判断时效性和可信度。

以下是抓取到的部分内容：\n\n"""
    prompt_tokens = estimate_tokens(prompt_prefix)
    max_content_tokens = 10000  # 每批最大 token 数
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

    if not all_table_rows:
        return "无相关内容。\n", []

    unique_rows, events_in_report = deduplicate_and_mark_new(all_table_rows, old_events)
    final_table = "\n".join([table_header, table_sep] + unique_rows)
    return final_table, events_in_report

# ================= 报告生成 =================
def generate_html_report(report_text: str, all_articles: List[Dict], failed_sources: List[Tuple[str, str]]) -> str:
    """生成 HTML 报告，包含运行状态和登录保护"""
    # 转换表格部分
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
                html_table += "</thead><tbody></tbody></table>\n"
                in_table = False
    if in_table:
        html_table += "</thead><tbody></tbody></table>\n"

    total_sources = len(RAW_SOURCES)
    success_count = total_sources - len(failed_sources)
    status_html = f"""
    <div style="background-color: #f0f0f0; padding: 12px; border-radius: 8px; margin-bottom: 20px;">
        <h2>📊 本次运行状态</h2>
        <ul>
            <li>✅ 成功抓取信源: {success_count}/{total_sources}</li>
            <li>⚠️ 失败信源数: {len(failed_sources)}</li>
            {''.join([f'<li style="color: #d9534f;">❌ 失败信源: {url} - {reason}</li>' for url, reason in failed_sources]) if failed_sources else '<li>🎉 所有信源抓取成功！</li>'}
            <li>📄 总抓取条目: {len(all_articles)} 条（去重后）</li>
            <li>🤖 AI 分析完成，报告生成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</li>
        </ul>
    </div>
    """

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
{status_html}
<div id="report">
{html_table}
</div>
<div class="footer">
    <p>注：本报告由 AI 基于过去24小时抓取的内容自动生成，仅供参考。</p>
</div>
</body>
</html>"""

def save_reports_with_history(report_text: str, all_articles: List[Dict], failed_sources: List[Tuple[str, str]]):
    """保存 Markdown 和 HTML 报告，同时归档历史版本"""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    total_sources = len(RAW_SOURCES)
    success_count = total_sources - len(failed_sources)
    status_md = f"""## 📊 本次运行状态

- ✅ 成功抓取信源: {success_count}/{total_sources}
- ⚠️ 失败信源数: {len(failed_sources)}
"""
    if failed_sources:
        status_md += "**失败信源列表：**\n"
        for url, reason in failed_sources:
            status_md += f"  - ❌ `{url}` : {reason}\n"
    else:
        status_md += "- 🎉 所有信源抓取成功！\n"
    status_md += f"- 📄 总抓取条目: {len(all_articles)} 条（去重后）\n"
    status_md += f"- 🤖 AI 分析完成，报告生成时间: {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n---\n\n"
    full_report = status_md + report_text

    with open("report.md", "w", encoding="utf-8") as f:
        f.write(full_report)
    html_content = generate_html_report(report_text, all_articles, failed_sources)
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
    """生成历史报告索引页"""
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
    """删除超过指定天数的旧报告和原始数据"""
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
    event_counts = cleanup_old_events(event_counts, days=30)
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
