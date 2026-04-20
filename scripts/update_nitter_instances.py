#!/usr/bin/env python3
"""
自动发现并测试可用的 Nitter 公共实例（彻底修复版）
"""
import json
import re
import time
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Set
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

TEST_USERNAME = "elonmusk"
TEST_TIMEOUT = 15
MAX_WORKERS = 10
RETRY_COUNT = 2
REQUEST_DELAY = 0.5

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
]

SOURCES = [
    "https://status.d420.de/",
    "https://raw.githubusercontent.com/wiki/zedeus/nitter/Instances.md",
    "https://github.com/zedeus/nitter/wiki/Instances"
]

FALLBACK_INSTANCES = [
    "https://xcancel.com",
    "https://nitter.tiekoetter.com",
    "https://nitter.catsarch.com",
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.space",
    "https://nitter.privacyredirect.com",
    "https://lightbrd.com",
    "https://nitter.kareem.one"
]

OUTPUT_FILE = "healthy_nitter.json"

def clean_url(url: str) -> str:
    """彻底清洗 URL，去除各种干扰字符"""
    if not url:
        return ""
    url = url.strip()
    # 去除首尾匹配的引号（单引号或双引号）
    if (url.startswith('"') and url.endswith('"')) or (url.startswith("'") and url.endswith("'")):
        url = url[1:-1]
    # 去除尾部可能残留的引号（针对 nitter.privacyredirect.com/" 这种情况）
    while url.endswith('"'):
        url = url[:-1]
    while url.endswith("'"):
        url = url[:-1]
    # 去除尾部斜杠
    url = url.rstrip('/')
    # 去除 # 锚点
    if '#' in url:
        url = url.split('#')[0]
    # 确保以 https:// 开头（如果不是，丢弃）
    if not (url.startswith('http://') or url.startswith('https://')):
        return ""
    return url

def fetch_with_retry(url: str, timeout: int = 15):
    for attempt in range(RETRY_COUNT):
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            resp = requests.get(url, timeout=timeout, headers=headers)
            if resp.status_code == 200:
                return resp
        except:
            pass
        time.sleep(1)
    return None

def extract_links_from_html(html: str) -> Set[str]:
    soup = BeautifulSoup(html, 'html.parser')
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        if not (href.startswith('http://') or href.startswith('https://')):
            continue
        if 'ssllabs.com' in href or 'github.com' in href:
            continue
        if 'nitter' in href or 'xcancel' in href:
            cleaned = clean_url(href)
            if cleaned:
                links.add(cleaned)
    return links

def extract_links_from_markdown(markdown: str) -> Set[str]:
    raw_urls = re.findall(r'https?://[^\s\)]+', markdown)
    links = set()
    for url in raw_urls:
        url = url.rstrip('.,;:)!?')
        if 'ssllabs.com' in url or 'github.com' in url:
            continue
        if 'nitter' in url or 'xcancel' in url:
            cleaned = clean_url(url)
            if cleaned:
                links.add(cleaned)
    return links

def test_instance(instance: str) -> bool:
    for attempt in range(RETRY_COUNT):
        try:
            headers = {"User-Agent": random.choice(USER_AGENTS)}
            url = f"{instance}/{TEST_USERNAME}/rss"
            resp = requests.get(url, timeout=TEST_TIMEOUT, headers=headers)
            if resp.status_code == 200 and ("rss" in resp.text.lower() or "channel" in resp.text.lower()):
                return True
        except:
            pass
        time.sleep(REQUEST_DELAY)
    return False

def collect_candidates() -> Set[str]:
    candidates = set()
    for source in SOURCES:
        logger.info(f"从 {source} 收集候选实例...")
        resp = fetch_with_retry(source)
        if not resp:
            logger.warning(f"无法获取 {source}")
            continue
        if source.endswith('.md') or 'wiki' in source:
            links = extract_links_from_markdown(resp.text)
        else:
            links = extract_links_from_html(resp.text)
        candidates.update(links)
        logger.info(f"从 {source} 获得 {len(links)} 个链接")
    candidates.update(FALLBACK_INSTANCES)
    # 再次清洗所有候选
    cleaned = {clean_url(c) for c in candidates if clean_url(c)}
    logger.info(f"候选实例总数: {len(cleaned)}")
    return cleaned

def main():
    logger.info("开始发现 Nitter 实例...")
    candidates = collect_candidates()
    if not candidates:
        logger.error("未找到任何候选实例，使用备用实例池")
        candidates = set(FALLBACK_INSTANCES)

    healthy = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_inst = {executor.submit(test_instance, inst): inst for inst in candidates}
        for future in as_completed(future_to_inst):
            if future.result():
                healthy.append(future_to_inst[future])

    healthy = sorted(set(healthy))
    if not healthy:
        logger.warning("未发现任何健康实例，使用 xcancel.com 作为最终兜底")
        healthy = ["https://xcancel.com"]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(healthy, f, indent=2)
    logger.info(f"已更新 {OUTPUT_FILE}，共 {len(healthy)} 个健康实例: {healthy}")

if __name__ == "__main__":
    main()
