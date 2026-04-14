#!/usr/bin/env python3
# crawler.py - 最终稳定版：抓取完 → Grok 一次性分析 → 清晰表格报告
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
GROK_MODEL = "grok-3-mini"                # 当前最稳定模型
GROK_BASE_URL = "https://api.x.ai/v1"

# RSSHub 和 Nitter 备用实例（随机选择，提高成功率）
RSSHUB_INSTANCES = [
    "https://rsshub.app",
    "https://rsshub.feeded.xyz",
    "https://rsshub.bili.xyz",
]
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.linuxboot.org",
]

# ================= 信源列表 =================
RAW_SOURCES = [
    "https://www.voachinese.com/China",
    "https://www.voachinese.com/p/6197.html",
    "https://www.bbc.com/zhongwen/simp",
    "https://www.rfa.org/mandarin",
    "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
    "https://www.rfi.fr/cn/",
    "https://cn.nytimes.com/",
    "https://www.zaobao.com/realtime/china",
    # X 账号（一级重要信源）
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
    """尝试多种时间格式解析"""
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
            if dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            return dt
        except:
            continue
    return None

def url_to_rss(url):
    """原始 URL 转为 RSS 地址（随机实例）"""
    rsshub = random.choice(RSSHUB_INSTANCES)
    nitter = random.choice(NITTER_INSTANCES)
    
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
    """抓取单个 RSS，返回过去24小时内最多15条"""
    try:
        resp = requests.get(rss_url, timeout=15)
        if resp.status_code != 200:
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
                summary = clean_html(entry.get("content", [{}])[0].get("value", ""))
            if not summary:
                summary = title
            items.append({
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary,
                "published": published,
                "source": original_url
            })
            if len(items) >= 15:
                break
        return items
    except Exception as e:
        print(f"  抓取异常 {original_url}: {e}")
        return []

def fetch_rss_with_retry(original_url):
    """X 账号尝试多个 Nitter 实例，其他直接抓取"""
    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        for nitter in NITTER_INSTANCES:
            test_url = f"{nitter}/{username}/rss"
            items = fetch_single_rss(test_url, original_url)
            if items:
                print(f"  ✓ X账号 {username} 使用 {nitter} 成功")
                return items
            print(f"  ⚠ {nitter} 失败，尝试下一个")
        return []
    else:
        rss_url = url_to_rss(original_url)
        return fetch_single_rss(rss_url, original_url)

def fetch_all_sources():
    """并发抓取所有信源"""
    print(f"开始并发抓取 {len(RAW_SOURCES)} 个信源...")
    all_items = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_rss_with_retry, raw_url): raw_url for raw_url in RAW_SOURCES}
        for future in as_completed(future_to_url):
            raw_url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"✓ {raw_url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {raw_url} 失败: {e}")
    return all_items

def call_grok_analysis(all_articles):
    """一次性交给 Grok 生成报告"""
    if not GROK_API_KEY:
        return "# Grok 分析失败\nGROK_API_KEY 未设置，请检查 GitHub Secrets。"
    if not all_articles:
        return "# 无数据\n未抓取到任何文章。"

    content_list = []
    for idx, art in enumerate(all_articles, 1):
        content_list.append(f"{idx}. 标题：{art['title']}\n   摘要：{art['summary'][:300]}\n   链接：{art['link']}\n")
    combined = "\n".join(content_list)

    prompt = f"""你是一名专业的网络安全和舆情分析师。

以下是过去24小时从多个信源抓取到的所有内容（共 {len(all_articles)} 条）。

请严格按照以下格式生成**内容安全行业舆情报告**：

# 内容安全行业舆情报告
生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

| 事件简述 | 原文链接 | 潜在风险点 |
|----------|----------|------------|
| （简述，不超过60字） | [查看](链接) | （风险点，不超过30字） |
| ... | ... | ... |

要求：
- 只输出涉华内容。
- 没有涉华内容时，只输出“过去24小时无涉华内容”。
- 不要添加任何额外解释。

以下是抓取到的全部内容：

{combined}"""

    try:
        response = requests.post(
            f"{GROK_BASE_URL}/chat/completions",
            headers={"Authorization": f"Bearer {GROK_API_KEY}", "Content-Type": "application/json"},
            json={
                "model": GROK_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 4000
            },
            timeout=90
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"# Grok 分析失败\nHTTP {response.status_code}\n{response.text}"
    except Exception as e:
        return f"# Grok 分析失败\n异常: {str(e)}"

def save_reports(markdown_report, all_articles):
    """保存 Markdown + HTML 报告 + 原始数据"""
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(markdown_report)

    # 生成 HTML（表格可点击）
    html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>内容安全舆情报告</title>
<style>
    body {{ font-family: Arial, sans-serif; margin: 20px; line-height: 1.6; }}
    h1 {{ color: #333; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background-color: #f2f2f2; }}
    a {{ color: #0366d6; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
    .footer {{ margin-top: 30px; font-size: 0.8em; color: #666; }}
</style>
</head>
<body>
<h1>内容安全行业舆情报告</h1>
<p>生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
<hr>
<div id="report">
"""
    lines = markdown_report.split("\n")
    in_table = False
    table_html = ""
    for line in lines:
        if line.startswith("|") and "|" in line:
            if not in_table:
                in_table = True
                table_html = '<table>\n'
            if re.match(r'^\|[\s\-:]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            table_html += "<tr>\n"
            for cell in cells:
                link_match = re.search(r'\[(.*?)\]\((.*?)\)', cell)
                if link_match:
                    text, url = link_match.group(1), link_match.group(2)
                    cell = f'<a href="{url}" target="_blank">{text}</a>'
                table_html += f"<td>{cell}</td>\n"
            table_html += "</tr>\n"
        else:
            if in_table:
                table_html += "</table>\n"
                html_content += table_html
                in_table = False
                table_html = ""
            if line.strip():
                if line.startswith("#"):
                    html_content += f"<h1>{line.lstrip('#').strip()}</h1>\n"
                else:
                    html_content += f"<p>{line}</p>\n"
    if in_table:
        html_content += table_html + "</table>\n"

    html_content += f"""
</div>
<div class="footer">
<p>注：本报告由 Grok AI 自动生成，基于过去24小时抓取的 {len(all_articles)} 条原始内容。</p>
</div>
</body>
</html>"""
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    # 保存原始数据
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    with open(f"data/raw_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"报告已保存: report.md + report.html")
    print(f"原始数据保存: data/raw_{timestamp}.json")

def main():
    start_time = time.time()
    print("=== 开始抓取所有信源（过去24小时） ===")
    all_articles = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_rss_with_retry, raw_url): raw_url for raw_url in RAW_SOURCES}
        for future in as_completed(future_to_url):
            raw_url = future_to_url[future]
            try:
                items = future.result()
                all_articles.extend(items)
                print(f"✓ {raw_url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {raw_url} 失败: {e}")

    print(f"抓取完成，共 {len(all_articles)} 条文章")

    print("=== 提交给 Grok AI 分析 ===")
    report = call_grok_analysis(all_articles)

    save_reports(report, all_articles)
    print(f"全部完成，总耗时 {time.time()-start_time:.1f} 秒")

if __name__ == "__main__":
    main()
