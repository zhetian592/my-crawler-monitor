#!/usr/bin/env python3
# crawler.py - 最终稳定调试版（只用最可靠实例）
import os
import json
import feedparser
import random
import time
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 配置 =================
GROK_API_KEY = os.environ.get("GROK_API_KEY")
GROK_MODEL = "grok-3-mini"
GROK_BASE_URL = "https://api.x.ai/v1"

# 只保留最稳定的实例（解决 DNS 解析失败）
RSSHUB_INSTANCES = ["https://rsshub.app"]          # 官方实例最稳定
NITTER_INSTANCES = ["https://nitter.net"]          # 最常用的 Nitter

RAW_SOURCES = [
    "https://www.voachinese.com/China",
    "https://www.voachinese.com/p/6197.html",
    "https://www.bbc.com/zhongwen/simp",
    "https://www.rfa.org/mandarin",
    "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
    "https://www.rfi.fr/cn/",
    "https://cn.nytimes.com/",
    "https://www.zaobao.com/realtime/china",
    "https://x.com/whyyoutouzhele",
    "https://x.com/Chai20230817",
    "https://x.com/realcaixia",
    "https://x.com/wangzhian8848",
    "https://x.com/wangdan1989",
    "https://x.com/wuerkaixi",
    "https://x.com/newszg_official",
    "https://x.com/june4thmuseum",
    "https://x.com/hrw_chinese",
    "https://x.com/torontobigface",
]

def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text().strip()[:500]

def parse_published(published_str):
    if not published_str:
        return None
    formats = ["%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"]
    for fmt in formats:
        try:
            dt = datetime.strptime(published_str, fmt)
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
        except:
            continue
    return None

def url_to_rss(url):
    rsshub = RSSHUB_INSTANCES[0]
    nitter = NITTER_INSTANCES[0]
    if "voachinese.com/China" in url: return f"{rsshub}/voachinese/china"
    if "voachinese.com/p/6197.html" in url: return f"{rsshub}/voachinese/6197"
    if "bbc.com/zhongwen/simp" in url: return f"{rsshub}/bbc/zhongwen/simp"
    if "rfa.org/mandarin" in url: return f"{rsshub}/rfa/mandarin"
    if "dw.com/zh" in url: return f"{rsshub}/dw/rss/zh/s-9058"
    if "rfi.fr/cn" in url: return f"{rsshub}/rfi/cn"
    if "cn.nytimes.com" in url: return f"{rsshub}/nytimes/zh"
    if "zaobao.com/realtime/china" in url: return f"{rsshub}/zaobao/realtime/china"
    if "x.com/" in url:
        username = url.split("/")[-1]
        return f"{nitter}/{username}/rss"
    return url

def fetch_single_rss(rss_url, original_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; RSS-Crawler/1.0)"}
        resp = requests.get(rss_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code} {original_url}")
            return []
        feed = feedparser.parse(resp.content)
        cutoff = datetime.utcnow() - timedelta(hours=24)
        items = []
        for entry in feed.entries:
            published = entry.get("published", entry.get("updated", ""))
            pub_dt = parse_published(published)
            if pub_dt and pub_dt < cutoff:
                continue
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = title
            items.append({
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary,
                "source": original_url
            })
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        print(f"  抓取失败 {original_url}: {e}")
        return []

def fetch_all_sources():
    print(f"开始抓取 {len(RAW_SOURCES)} 个信源...")
    all_items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_single_rss, url_to_rss(url), url): url for url in RAW_SOURCES}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"✓ {url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {url} 异常: {e}")
    return all_items

def call_grok_analysis(all_articles):
    if not GROK_API_KEY:
        return "# Grok 分析失败\nGROK_API_KEY 未设置"
    if not all_articles:
        return "# 无数据\n未抓取到任何文章"

    content_list = [f"{idx}. 标题：{art['title']}\n   摘要：{art['summary'][:300]}\n   链接：{art['link']}" 
                    for idx, art in enumerate(all_articles, 1)]
    combined = "\n".join(content_list)

    prompt = f"""你是一名专业的舆情分析师。以下是过去24小时抓取的内容（共 {len(all_articles)} 条）。

请严格按以下格式生成报告：

# 内容安全行业舆情报告
生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

| 事件简述 | 原文链接 | 潜在风险点 |
|----------|----------|------------|
| ... | [查看](链接) | ... |

只输出涉华内容，每条风险点≤30字。没有涉华内容时只输出“过去24小时无涉华内容”。

内容：
{combined}"""

    try:
        response = requests.post(
            f"{GROK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={"model": GROK_MODEL, "messages": [{"role": "user", "content": prompt}], "temperature": 0.3, "max_tokens": 4000},
            timeout=60
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"# Grok 分析失败\nHTTP {response.status_code}"
    except Exception as e:
        return f"# Grok 分析失败\n异常: {str(e)}"

def main():
    start = time.time()
    print("=== 开始抓取信源 ===")
    all_articles = fetch_all_sources()
    print(f"共抓取 {len(all_articles)} 条")

    if not all_articles:
        print("⚠️ 未抓到任何文章，请查看上方日志")
        with open("report.md", "w", encoding="utf-8") as f:
            f.write("# 抓取失败\n\n未抓到任何文章，请检查 Actions 日志。")
        return

    print("=== 调用 Grok 分析 ===")
    report = call_grok_analysis(all_articles)

    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report)

    print(f"报告生成完成！总耗时 {time.time()-start:.1f} 秒")

if __name__ == "__main__":
    main()
