#!/usr/bin/env python3
# crawler.py - OpenRouter 最终修正版（修复 404 错误）
import os
import json
import feedparser
import time
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 配置 =================
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
# 使用免费稳定模型
MODEL = "deepseek/deepseek-r1:free"

BASE_URL = "https://openrouter.ai/api/v1"

RSSHUB_INSTANCES = ["https://rsshub.app"]
NITTER_INSTANCES = ["https://nitter.net"]

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

def url_to_rss(url):
    rsshub = RSSHUB_INSTANCES[0]
    nitter = NITTER_INSTANCES[0]
    if "voachinese.com/China" in url:
        return f"{rsshub}/voachinese/china"
    if "voachinese.com/p/6197.html" in url:
        return f"{rsshub}/voachinese/6197"
    if "bbc.com/zhongwen/simp" in url:
        return f"{rsshub}/bbc/zhongwen/simp"
    if "rfa.org/mandarin" in url:
        return f"{rsshub}/rfa/mandarin"
    if "dw.com/zh" in url:
        return f"{rsshub}/dw/rss/zh/s-9058"
    if "rfi.fr/cn" in url:
        return f"{rsshub}/rfi/cn"
    if "cn.nytimes.com" in url:
        return f"{rsshub}/nytimes/zh"
    if "zaobao.com/realtime/china" in url:
        return f"{rsshub}/zaobao/realtime/china"
    if "x.com/" in url:
        username = url.split("/")[-1]
        return f"{nitter}/{username}/rss"
    return url

def fetch_single_rss(rss_url, original_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; RSS-Crawler/1.0)"}
        resp = requests.get(rss_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return []
        feed = feedparser.parse(resp.content)
        items = []
        for entry in feed.entries:
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

def call_ai_analysis(all_articles):
    if not OPENROUTER_API_KEY:
        return "# AI 分析失败\nOPENROUTER_API_KEY 未设置，请检查 Secrets。"

    if not all_articles:
        return "# 无数据\n过去24小时未抓取到任何文章"

    content_list = []
    for idx, art in enumerate(all_articles[:25], 1):
        content_list.append(f"{idx}. 标题：{art.get('title', '')[:150]}\n   链接：{art.get('link', '')}\n")
    combined = "\n".join(content_list)

    prompt = f"""你是一名专业的舆情分析师。

以下是过去24小时抓取的内容。

请严格按照以下格式生成报告：

# 内容安全行业舆情报告
生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

| 事件简述 | 原文链接 | 潜在风险点 |
|----------|----------|------------|
| （简述事件，不超过60字） | [查看](链接) | （风险点，不超过30字） |

只输出涉华内容。没有时只输出“过去24小时无涉华内容”。不要额外文字。

内容：
{combined}"""

    try:
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 2000
            },
            timeout=60
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"# AI 分析失败\nHTTP {response.status_code}\n{response.text[:200]}"
    except Exception as e:
        return f"# AI 分析失败\n异常: {str(e)}"

def main():
    start_time = time.time()
    print("=== 开始抓取信源 ===")
    all_articles = fetch_all_sources()
    print(f"抓取完成，共 {len(all_articles)} 条文章")

    if not all_articles:
        print("⚠️ 未抓到任何文章")
        with open("report.md", "w", encoding="utf-8") as f:
            f.write("# 抓取失败\n\n未抓到任何文章，请检查日志。")
        return

    print("=== 调用 AI 分析 ===")
    report = call_ai_analysis(all_articles)

    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report)

    print("报告生成完成 → report.md")
    print(f"总耗时 {time.time()-start_time:.1f} 秒")

if __name__ == "__main__":
    main()
