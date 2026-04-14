#!/usr/bin/env python3
# crawler.py - 使用 GitHub Models (经典 PAT) 进行 AI 分析
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
# 从环境变量读取经典 PAT（需要具备 repo 权限）
GH_TOKEN = os.environ.get("GH_MODELS_TOKEN")
if not GH_TOKEN:
    # 兼容旧版
    GH_TOKEN = os.environ.get("GITHUB_TOKEN")

# GitHub Models API 配置
AI_BASE_URL = "https://models.inference.ai.azure.com"
AI_MODEL = "gpt-4o-mini"   # 或 "gpt-4.1-mini"

# RSSHub 和 Nitter 实例
RSSHUB_INSTANCES = ["https://rsshub.app", "https://rsshub.feeded.xyz"]
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.poast.org", "https://nitter.linuxboot.org"]

RAW_SOURCES = [
    "https://www.voachinese.com/China",
    "https://www.voachinese.com/p/6197.html",
    "https://www.bbc.com/zhongwen/simp",
    "https://www.rfa.org/mandarin",
    "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
    "https://www.rfi.fr/cn/",
    "https://cn.nytimes.com/",
    "https://www.zaobao.com/realtime/china",
    # X 账号（全部保留）
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
    "https://x.com/dayangelcp",
    "https://x.com/chinatransition",
    "https://x.com/pear14525902",
    "https://x.com/RedPigCartoon",
    "https://x.com/Cian_Ci",
    "https://x.com/remonwangxt",
    "https://x.com/xinwendiaocha",
    "https://x.com/Ruters0615",
    "https://x.com/ZhouFengSuo",
    "https://x.com/gaoyu200812",
    "https://x.com/lidangzzz",
    "https://x.com/YongyuanCui1",
    "https://x.com/xiaojingcanxue",
    "https://x.com/xiangjunweiwu",
    "https://x.com/tibetdotcom",
    "https://x.com/UHRP_Chinese",
    "https://x.com/XiJPDynasty",
    "https://x.com/chonglangzhiyin",
    "https://x.com/xingzhe2021",
    "https://x.com/jhf8964",
    "https://x.com/fangshimin",
    "https://x.com/badiucao",
    "https://x.com/WOMEN4China",
    "https://x.com/CitizensDailyCN",
    "https://x.com/hchina89",
    "https://x.com/amnestychinese",
    "https://x.com/liangziyueqian1",
    "https://x.com/jielijian",
    "https://x.com/CHENWEIMING2017",
    "https://x.com/BoKuangyi",
    "https://x.com/chinesepen_org",
    "https://x.com/wurenhua",
]

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
    if "voachinese.com/China" in url:
        return f"{RSSHUB_INSTANCES[0]}/voachinese/china"
    if "voachinese.com/p/6197.html" in url:
        return f"{RSSHUB_INSTANCES[0]}/voachinese/6197"
    if "bbc.com/zhongwen/simp" in url:
        return "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"
    if "rfa.org/mandarin" in url:
        return f"{RSSHUB_INSTANCES[0]}/rfa/mandarin"
    if "dw.com/zh" in url:
        return f"{RSSHUB_INSTANCES[0]}/dw/rss/zh/s-9058"
    if "rfi.fr/cn" in url:
        return f"{RSSHUB_INSTANCES[0]}/rfi/cn"
    if "cn.nytimes.com" in url:
        return f"{RSSHUB_INSTANCES[0]}/nytimes/zh"
    if "zaobao.com/realtime/china" in url:
        return "https://www.zaobao.com/realtime/china/feed"
    if "x.com/" in url:
        return None
    return url

def fetch_single_rss(rss_url, original_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(rss_url, headers=headers, timeout=20)
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
                "source": original_url,
                "fetched_at": datetime.utcnow().isoformat()
            })
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        print(f"  抓取异常 {original_url}: {e}")
        return []

def fetch_with_retry(original_url):
    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        for nitter in NITTER_INSTANCES:
            test_url = f"{nitter}/{username}/rss"
            items = fetch_single_rss(test_url, original_url)
            if items:
                print(f"  ✓ X {username} 使用 {nitter} 成功")
                return items
            else:
                print(f"  ⚠ X {username} 使用 {nitter} 失败")
        return []
    rss_url = url_to_rss(original_url)
    if not rss_url:
        return []
    return fetch_single_rss(rss_url, original_url)

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

def call_ai_analysis(all_articles):
    if not GH_TOKEN:
        return "# AI 分析失败\nGH_MODELS_TOKEN 未设置，请检查 Secrets。"

    if not all_articles:
        return "# 无数据\n未抓取到任何文章。"

    # 限制发送给 AI 的文章数量（避免 token 超限）
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

以下是从多个信源（VOA、BBC、RFA、DW、RFI、纽约时报、联合早报及 X 平台）抓取到的过去24小时内的部分内容（共 {len(articles_for_ai)} 条，实际抓取 {len(all_articles)} 条）。

请仔细阅读这些内容，然后完成以下任务：

1. 筛选出其中**涉华**的内容（涉及中国、中共、习近平、台湾、香港、新疆、西藏、南海、中美关系等）。
2. 基于筛选出的涉华内容，生成一份**内容安全行业舆情报告**，使用 Markdown 表格格式：

| 事件简述 | 原文链接 | 潜在风险点 |
|----------|----------|------------|
| （简述，不超过60字） | [查看](原文URL) | （风险点，不超过30字） |

要求：
- 每一条涉华内容单独占一行。
- “原文链接”列请使用 `[查看](URL)` 格式。
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
            max_tokens=3000,
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"AI 调用失败: {e}")
        return f"# AI 分析失败\n异常: {str(e)}"

def save_reports(report_text, all_articles):
    # 保存 Markdown
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report_text)

    # 生成 HTML 报告（将 Markdown 表格转换为 HTML）
    html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>内容安全舆情报告</title>
<style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 20px; }}
    h1 {{ font-size: 1.8em; border-bottom: 1px solid #eaecef; }}
    table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
    th, td {{ border: 1px solid #dfe2e5; padding: 8px 12px; text-align: left; vertical-align: top; }}
    th {{ background-color: #f6f8fa; }}
    a {{ color: #0366d6; text-decoration: none; }}
</style>
</head>
<body>
<h1>内容安全行业舆情报告</h1>
<p>生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
<div id="report">
"""
    lines = report_text.split("\n")
    in_table = False
    for line in lines:
        if line.startswith("|") and "|" in line:
            if not in_table:
                html_content += '<tr>\n<thead>'
                in_table = True
            if re.match(r'^\|[\s\-:]+\|$', line):
                continue
            cells = [c.strip() for c in line.split("|")[1:-1]]
            html_content += "<tr>\n"
            for cell in cells:
                link_match = re.search(r'\[(.*?)\]\((.*?)\)', cell)
                if link_match:
                    text, url = link_match.group(1), link_match.group(2)
                    cell = f'<a href="{url}" target="_blank">{text}</a>'
                html_content += f"<td>{cell}</td>\n"
            html_content += "</tr>\n"
        else:
            if in_table:
                html_content += "</thead><tbody></tbody></table>\n"
                in_table = False
            if line.strip():
                html_content += f"<p>{line}</p>\n"
    if in_table:
        html_content += "</tbody></table>\n"
    html_content += f"""
</div>
<p>注：本报告由 AI 基于过去24小时抓取的 {len(all_articles)} 条内容生成。</p>
</body>
</html>"""
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    # 保存原始数据
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    with open(f"data/raw_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print("报告已保存: report.md, report.html")
    print(f"原始数据保存: data/raw_{timestamp}.json")

def main():
    start = time.time()
    print("=== 开始抓取信源（过去24小时） ===")
    all_articles = fetch_all_sources()
    print(f"抓取完成，共 {len(all_articles)} 条有效文章，耗时 {time.time()-start:.1f} 秒")
    if not all_articles:
        print("⚠️ 未抓到任何文章")
        with open("report.md", "w") as f:
            f.write("# 抓取失败\n\n未抓到任何文章，请检查日志。")
        with open("report.html", "w") as f:
            f.write("<h1>抓取失败</h1><p>未抓到任何文章。</p>")
        return
    print("=== 调用 AI 分析（GitHub Models） ===")
    report = call_ai_analysis(all_articles)
    save_reports(report, all_articles)
    print(f"全部完成，总耗时 {time.time()-start:.1f} 秒")

if __name__ == "__main__":
    main()
