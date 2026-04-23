#!/usr/bin/env python3
"""
自动发现并测试可用的 RSSHub 公共实例。
从官方实例列表获取候选，并发测试健康度，输出 JSON 文件。
"""
import json
import time
import logging
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Set

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)   # 修正：getLogger 首字母大写

TEST_TIMEOUT = 10
MAX_WORKERS = 20
RETRY_COUNT = 2

INSTANCES_PAGE = "https://rsshub.netlify.app/instances"
FALLBACK_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.ktachibana.party",
    "https://rsshub.bili.xyz",
    "https://rsshub.feeded.xyz",
]

OUTPUT_FILE = "healthy_rsshub.json"

def fetch_with_retry(url: str, timeout: int = 15):
    for attempt in range(RETRY_COUNT):
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            resp = requests.get(url, timeout=timeout, headers=headers)
            if resp.status_code == 200:
                return resp
        except:
            pass
        time.sleep(1)
    return None

def extract_instances_from_markdown(markdown: str) -> Set[str]:
    """从 Markdown 表格中提取 RSSHub 实例 URL"""
    instances = set()
    for line in markdown.split('\n'):
        if '|' in line and 'https://' in line:
            parts = line.split('|')
            for part in parts:
                if 'https://' in part:
                    url = part.strip()
                    url = url.rstrip('.,;:)!?')
                    if url.startswith('https://') and 'rsshub' in url.lower():
                        instances.add(url.rstrip('/'))
    return instances

def test_instance(instance: str) -> bool:
    """测试 RSSHub 实例是否可用"""
    for attempt in range(RETRY_COUNT):
        try:
            url = f"{instance}/rsshub/status"
            resp = requests.get(url, timeout=TEST_TIMEOUT)
            if resp.status_code == 200:
                return True
        except:
            pass
        time.sleep(0.5)
    return False

def main():
    logger.info("开始发现 RSSHub 实例...")
    candidates = set()
    resp = fetch_with_retry(INSTANCES_PAGE, timeout=15)
    if resp:
        instances = extract_instances_from_markdown(resp.text)
        candidates.update(instances)
        logger.info(f"从官方列表获取 {len(instances)} 个候选实例")
    else:
        logger.warning("无法获取官方实例列表，使用备用实例池")
        candidates.update(FALLBACK_INSTANCES)

    healthy = []
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_inst = {executor.submit(test_instance, inst): inst for inst in candidates}
        for future in as_completed(future_to_inst):
            if future.result():
                healthy.append(future_to_inst[future])

    healthy = sorted(set(healthy))
    if not healthy:
        logger.warning("未发现健康实例，使用备用实例池")
        healthy = FALLBACK_INSTANCES[:3]

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(healthy, f, indent=2)
    logger.info(f"已更新 {OUTPUT_FILE}，共 {len(healthy)} 个健康实例")

if __name__ == "__main__":
    main()
