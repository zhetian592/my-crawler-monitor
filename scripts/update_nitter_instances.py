#!/usr/bin/env python3
"""
自动发现并测试可用的 Nitter 公共实例。
从多个数据源收集候选实例，并发测试健康度，输出 JSON 文件。
"""
import json
import re
import time
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Set

import requests
from bs4 import BeautifulSoup

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ================= 配置 =================
TEST_USERNAME = "elonmusk"          # 测试使用的用户名
TEST_TIMEOUT = 10                   # 每个实例测试超时（秒）
MAX_WORKERS = 15                    # 并发测试线程数
RETRY_COUNT = 2                     # 请求重试次数

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


def fetch_with_retry(url: str, timeout: int = 15) -> requests.Response:
    """带重试的 GET 请求"""
    for attempt in range(RETRY_COUNT):
        try:
            resp = requests.get(url, timeout=timeout)
            if resp.status_code == 200:
                return resp
        except Exception as e:
            logger.debug(f"请求 {url} 失败 (尝试 {attempt+1}/{RETRY_COUNT}): {e}")
        time.sleep(1)
    return None


def extract_nitter_links_from_html(html: str) -> Set[str]:
    """从 HTML 页面中提取真正的 Nitter 实例链接"""
    soup = BeautifulSoup(html, 'html.parser')
    links = set()
    for a in soup.find_all('a', href=True):
        href = a['href']
        # 只保留 http/https 开头的链接
        if not (href.startswith('http://') or href.startswith('https://')):
            continue
        # 过滤掉明显不是 Nitter 实例的域名
        if 'ssllabs.com' in href or 'github.com' in href:
            continue
        # 域名中应包含 nitter 或 xcancel
        if 'nitter' in href or 'xcancel' in href:
            # 去掉可能的尾部斜杠
            links.add(href.rstrip('/'))
    return links


def extract_nitter_links_from_markdown(markdown: str) -> Set[str]:
    """从 Markdown 文本中提取真正的 Nitter 实例链接"""
    # 匹配 http/https 链接，但排除 ssllabs、github 等无关域名
    # 同时排除 Markdown 中的图片、引用等
    raw_urls = re.findall(r'https?://[^\s\)]+', markdown)
    links = set()
    for url in raw_urls:
        # 去除尾部标点
        url = url.rstrip('.,;:)!?')
        if not (url.startswith('http://') or url.startswith('https://')):
            continue
        if 'ssllabs.com' in url or 'github.com' in url:
            continue
        if 'nitter' in url or 'xcancel' in url:
            links.add(url.rstrip('/'))
    return links


def test_instance(instance: str) -> bool:
    """测试单个 Nitter 实例是否可用"""
    try:
        url = f"{instance}/{TEST_USERNAME}/rss"
        resp = requests.get(url, timeout=TEST_TIMEOUT)
        if resp.status_code == 200 and ("rss" in resp.text.lower() or "channel" in resp.text.lower()):
            logger.debug(f"实例可用: {instance}")
            return True
    except Exception as e:
        logger.debug(f"实例测试失败 {instance}: {e}")
    return False


def collect_candidates() -> Set[str]:
    """从所有数据源收集候选实例"""
    candidates = set()
    for source_url in SOURCES:
        logger.info(f"从 {source_url} 收集候选实例...")
        resp = fetch_with_retry(source_url, timeout=15)
        if not resp:
            logger.warning(f"无法获取 {source_url}")
            continue
        if source_url.endswith('.md') or 'wiki' in source_url:
            links = extract_nitter_links_from_markdown(resp.text)
        else:
            links = extract_nitter_links_from_html(resp.text)
        candidates.update(links)
        logger.info(f"从 {source_url} 获得 {len(links)} 个链接")
    # 添加备用实例
    candidates.update(FALLBACK_INSTANCES)
    # 清理：去掉可能残留的 # 锚点
    cleaned = set()
    for c in candidates:
        c = c.split('#')[0]
        if c.startswith('http'):
            cleaned.add(c)
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

    healthy = sorted(set(healthy))   # 去重并排序
    if not healthy:
        logger.warning("未发现任何健康实例，使用 xcancel.com 作为最终兜底")
        healthy = ["https://xcancel.com"]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(healthy, f, indent=2)
    logger.info(f"已更新 {OUTPUT_FILE}，共 {len(healthy)} 个健康实例: {healthy}")

    if healthy == ["https://xcancel.com"] and len(candidates) > 0:
        logger.warning("仅兜底实例可用，请检查网络或实例源")


if __name__ == "__main__":
    main()
