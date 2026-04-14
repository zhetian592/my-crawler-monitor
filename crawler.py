#!/usr/bin/env python3
# crawler.py - 官方 RSS 优先 + 稳定 X 账号抓取 + GitHub Models AI 分析
import os
import json
import feedparser
import time
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import openai

# ================= 配置 =================
GH_TOKEN = os.environ.get("GH_MODELS_TOKEN")
if not GH_TOKEN:
    GH_TOKEN = os.environ.get("GITHUB_TOKEN")

AI_BASE_URL = "https://models.inference.ai.azure.com"
AI_MODEL = "gpt-4o-mini"

# RSSHub 实例（仅作为后备，优先使用官方 RSS）
RSSHUB_INSTANCES = ["https://rsshub.app", "https://rsshub.feeded.xyz"]

# Nitter 实例（用于 X 账号）
NITTER_INSTANCES = [
    "https://nitter.net",
    "https://nitter.poast.org",
    "https://nitter.42l.fr",
    "https://nitter.snopyta.org",
    "https://nitter.private.coffee",
]

# ================= 信源列表（原始 URL）=================
RAW_SOURCES = [
    # 新闻网站（官方 RSS 优先）
    "https://www.voachinese.com/China",
    "https://www.voachinese.com/p/6197.html",
    "https://www.bbc.com/zhongwen/simp",
    "https://www.rfa.org/mandarin",
    "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
    "https://www.rfi.fr/cn/",
    "https://cn.nytimes.com/",
    "https://www.zaobao.com/realtime/china",
    "https://www.ntdtv.com/gb/instant-news.html",
    "https://www.epochtimes.com/gb/instant-news.htm",
    # X 账号（保留稳定可抓取的）
    "https://x.com/whyyoutouzhele",
    "https://x.com/wangzhian8848",
    "https://x.com/newszg_official",
    "https://x.com/wangdan1989",
    "https://x.com/torontobigface",
    "https://x.com/hrw_chinese",
    "https://x.com/dayangelcp",
    "https://x.com/chinatransition",
    "https://x.com/xinwendiaocha",
    "https://x.com/xiaojingcanxue",
    "https://x.com/ZhouFengSuo",
    "https://x.com/lidangzzz",
    "https://x.com/fangshimin",
    "https://x.com/UHRP_Chinese",
    "https://x.com/jhf8964",
    "https://x.com/amnestychinese",
    "https://x.com/liangziyueqian1",
    "https://x.com/badiucao",
    "https://x.com/jielijian",
    "https://x.com/wurenhua",
]

# ================= 辅助函数 =================
def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text().strip()[:500]

def parse_published(published_str):
    if not published_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
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

def url_to_rss(url):
    """根据原始 URL 返回 RSS 地址（官方 RSS 优先，否则使用 RSSHub）"""
    # VOA 中文网（官方 API RSS）
    if "voachinese.com/China" in url:
        return "https://www.voachinese.com/api/zh-hans?format=rss"
    if "voachinese.com/p/6197.html" in url:
        return "https://www.voachinese.com/api/zh-hans?format=rss"
    # BBC 中文（官方 RSS）
    if "bbc.com/zhongwen/simp" in url:
        return "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"
    # RFA（无官方 RSS，使用 RSSHub）
    if "rfa.org/mandarin" in url:
        return f"{RSSHUB_INSTANCES[0]}/rfa/mandarin"
    # 德国之声（官方中文 RSS）
    if "dw.com/zh" in url:
        return "https://rss.dw.com/rdf/rss-chi-all"
    # RFI 法广（官方分类 RSS）
    if "rfi.fr/cn" in url:
        return "https://www.rfi.fr/cn/general/rss"
    # 纽约时报中文网（官方 RSS）
    if "cn.nytimes.com" in url:
        return "https://cn.nytimes.com/rss/news.xml"
    # 联合早报（无官方 RSS，使用 RSSHub）
    if "zaobao.com/realtime/china" in url:
        return f"{RSSHUB_INSTANCES[0]}/zaobao/realtime/china"
    # 新唐人（无官方 RSS，使用 RSSHub）
    if "ntdtv.com/gb/instant-news.html" in url:
        return f"{RSSHUB_INSTANCES[0]}/ntdtv/instant-news"
    # 大纪元（官方 RSS 聚合，使用大陆新闻分类）
    if "epochtimes.com/gb/instant-news.htm" in url:
        return "https://www.epochtimes.com/gb/nsc112.htm?rss=1"
    # X 账号
    if "x.com/" in url:
        return None
    return url

def fetch_single_rss(rss_url, original_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(rss_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            print(f"  ⚠ HTTP {resp.status_code} - {original_url} ({rss_url})")
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
                "source": original_url,
                "fetched_at": datetime.utcnow().isoformat()
            })
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        print(f"  ✗ 抓取异常 {original_url} ({rss_url}): {e}")
        return []

def fetch_with_retry(original_url):
    # X 账号：轮询所有 Nitter 实例
    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        for nitter in NITTER_INSTANCES:
            test_url = f"{nitter}/{username}/rss"
            print(f"  → 尝试 X {username} 使用 {nitter}")
            items = fetch_single_rss(test_url, original_url)
            if items:
                print(f"  ✓ X {username} 成功 via {nitter} (条数: {len(items)})")
                return items
            else:
                print(f"  ⚠ X {username} 失败 via {nitter}")
            time.sleep(0.5)
        print(f"  ✗ X {username} 所有实例均失败")
        return []
    # 普通网站
    rss_url = url_to_rss(original_url)
    if not rss_url:
        print(f"  ✗ 无法生成 RSS 地址: {original_url}")
        return []
    items = fetch_single_rss(rss_url, original_url)
    if items:
        print(f"  ✓ {original_url} 成功 (条数: {len(items)})")
    else:
        print(f"  ✗ {original_url} 失败 (RSS: {rss_url})")
    return items

def fetch_all_sources():
    print(f"开始抓取 {len(RAW_SOURCES)} 个信源（过去24小时）...")
    all_items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_with_retry, url): url for url in RAW_SOURCES}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"✓ {url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {url} 异常: {e}")
    # 去重
    seen = set()
    unique = []
    for item in all_items:
        if item["link"] not in seen:
            seen.add(item["link"])
            unique.append(item)
    print(f"去重后共 {len(unique)} 条（原始 {len(all_items)} 条）")
    return unique

def mark_report_articles(all_articles):
    """强制标记 ntdtv 和 epochtimes 中标题含“报告”的文章为涉华"""
    for art in all_articles:
        source = art.get("source", "")
        title = art.get("title", "")
        if ("ntdtv.com" in source or "epochtimes.com" in source) and "报告" in title:
            art["china_related"] = True
            art["risk_point"] = "反华报告链接，内容可能诋毁中国"
            art["analysis_summary"] = title[:80]
            print(f"  📄 强制标记反华报告: {title[:50]} -> {art['link']}")
    return all_articles

def call_ai_analysis(all_articles):
    if not GH_TOKEN:
        return "# AI 分析失败\nGH_MODELS_TOKEN 未设置"
    if not all_articles:
        return "# 无数据\n未抓取到任何文章"

    max_articles = 80
    articles_for_ai = all_articles[:max_articles]
    content_list = []
    for idx, art in enumerate(articles_for_ai, 1):
        content_list.append(
            f"{idx}. 标题：{art.get('title', '')[:150]}\n"
            f"   摘要：{art.get('summary', '')[:300]}\n"
            f"   链接：{art.get('link', '')}\n"
        )
    combined = "\n".join(content_list)

    prompt = f"""你是一名专业的网络安全和舆情分析师。

以下是从多个信源抓取到的过去24小时内的部分内容（共 {len(articles_for_ai)} 条，实际抓取 {len(all_articles)} 条）。

请仔细阅读这些内容，然后完成以下任务：

1. 筛选出其中**涉华**的内容（涉及中国、中共、习近平、台湾、香港、新疆、西藏、南海、中美关系等）。
2. 基于筛选出的涉华内容，生成一份**内容安全行业舆情报告**，**必须使用 Markdown 表格格式**，表格必须包含表头分隔行（`|---|---|---|`），示例如下：

| 事件简述 | 原文链接 | 潜在风险点 |
|----------|----------|------------|
| 事件1简述（不超过80字） | [查看](URL1) | 风险点1（不超过30字，可略详细） |
| 事件2简述（不超过80字） | [查看](URL2) | 风险点2（不超过30字，可略详细） |

要求：
- 每一条涉华内容单独占一行。
- “原文链接”列必须使用 `[查看](原文URL)` 格式。
- “潜在风险点”列应在 30 字内尽量描述清楚可能的影响（如外交、社会、经济等）。
- 如果没有任何涉华内容，只输出一行“过去24小时无涉华内容”。
- 不要添加任何额外解释、开头语或结尾语。

以下是抓取到的全部内容：

{combined}"""

    try:
        client = openai.OpenAI(
            base_url=AI_BASE_URL,
            api_key=GH_TOKEN,
        )
        response = client.chat.completions.create(
            model=AI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI 调用失败: {e}")
        return f"# AI 分析失败\n异常: {str(e)}"

def save_reports(report_text, all_articles):
    # 保存 Markdown 备用
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report_text)

    # 生成 HTML 报告，优化排版
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>内容安全行业舆情报告</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            margin: 0;
            padding: 20px;
            background-color: #f5f5f5;
            color: #333;
            line-height: 1.5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background-color: #fff;
            border-radius: 12px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            padding: 24px;
        }}
        h1 {{
            font-size: 1.8rem;
            margin-top: 0;
            border-bottom: 2px solid #eaecef;
            padding-bottom: 12px;
        }}
        .meta {{
            color: #586069;
            font-size: 0.9rem;
            margin: 16px 0 24px 0;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            font-size: 14px;
            margin: 20px 0;
        }}
        th, td {{
            border: 1px solid #dfe2e5;
            padding: 10px 12px;
            text-align: left;
            vertical-align: top;
        }}
        th {{
            background-color: #f6f8fa;
            font-weight: 600;
            white-space: nowrap;
        }}
        td:nth-child(1) {{
            width: 45%;
            word-break: break-word;
            white-space: normal;
        }}
        td:nth-child(2) {{
            width: 15%;
            text-align: center;
        }}
        td:nth-child(3) {{
            width: 40%;
            word-break: break-word;
            white-space: normal;
        }}
        a {{
            color: #0366d6;
            text-decoration: none;
        }}
        a:hover {{
            text-decoration: underline;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 16px;
            border-top: 1px solid #eaecef;
            font-size: 12px;
            color: #6a737d;
            text-align: center;
        }}
        @media (max-width: 768px) {{
            .container {{ padding: 16px; }}
            th, td {{ padding: 6px 8px; font-size: 12px; }}
            td:nth-child(1) {{ width: 40%; }}
            td:nth-child(2) {{ width: 20%; }}
            td:nth-child(3) {{ width: 40%; }}
        }}
    </style>
</head>
<body>
<div class="container">
    <h1>📊 内容安全行业舆情报告</h1>
    <div class="meta">生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</div>
    <div id="report">
"""
    lines = report_text.split("\n")
    in_table = False
    for line in lines:
        if line.startswith("|") and "|" in line:
            if not in_table:
                html_content += '<table>\n<thead>\n'
                in_table = True
            if re.match(r'^\|[\s\-:]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            html_content += "<tr>\n"
            for cell in cells:
                link_match = re.search(r'\[(.*?)\]\((.*?)\)', cell)
                if link_match:
                    text, url = link_match.group(1), link_match.group(2)
                    cell = f'<a href="{url}" target="_blank" rel="noopener noreferrer">{text}</a>'
                html_content += f"<td>{cell}</td>\n"
            html_content += "</tr>\n"
        else:
            if in_table:
                html_content += "</thead><tbody></tbody></table>\n"
                in_table = False
            if line.strip():
                if line.startswith("#"):
                    level = len(line) - len(line.lstrip('#'))
                    text = line.lstrip('#').strip()
                    html_content += f"<h{level+1}>{text}</h{level+1}>\n"
                else:
                    html_content += f"<p>{line}</p>\n"
    if in_table:
        html_content += "</thead><tbody></tbody></table>\n"
    html_content += f"""
    </div>
    <div class="footer">
        <p>注：本报告由 AI 基于过去24小时抓取的 {len(all_articles)} 条内容自动生成，仅供参考。</p>
    </div>
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

    print("报告已保存: report.html (优化排版+丰富内容) 和 report.md")
    print(f"原始数据保存: data/raw_{timestamp}.json")

def main():
    start = time.time()
    print("=== 开始抓取信源（过去24小时） ===")
    all_articles = fetch_all_sources()
    all_articles = mark_report_articles(all_articles)
    print(f"抓取完成，共 {len(all_articles)} 条有效文章，耗时 {time.time()-start:.1f} 秒")
    if not all_articles:
        print("⚠️ 未抓到任何文章")
        with open("report.md", "w") as f:
            f.write("# 抓取失败\n\n未抓到任何文章，请检查日志。")
        with open("report.html", "w") as f:
            f.write("<h1>抓取失败</h1><p>未抓到任何文章，请检查日志。</p>")
        return
    print("=== 调用 AI 分析（GitHub Models） ===")
    report = call_ai_analysis(all_articles)
    save_reports(report, all_articles)
    print(f"全部完成，总耗时 {time.time()-start:.1f} 秒")

if __name__ == "__main__":
    main()
