#!/usr/bin/env python3
# crawler.py - 完整信源版 + OpenRouter AI 分析
import os
import json
import feedparser
import time
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 配置 =================
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
BASE_URL = "https://openrouter.ai/api/v1"
AI_MODEL = "meta-llama/llama-3.2-3b-instruct:free"   # 稳定免费模型

# RSSHub 实例（可换成你自己的）
RSSHUB_INSTANCE = "https://rsshub.app"
NITTER_INSTANCE = "https://nitter.net"   # X 账号 RSS 代理

# ================= 信源列表（原始 URL）=================
RAW_SOURCES = [
    # 新闻网站
    "https://www.voachinese.com/China",
    "https://www.voachinese.com/p/6197.html",
    "https://www.bbc.com/zhongwen/simp",
    "https://www.rfa.org/mandarin",
    "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
    "https://www.rfi.fr/cn/",
    "https://cn.nytimes.com/",
    "https://www.zaobao.com/realtime/china",
    # X 账号
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

def url_to_rss(original_url):
    """将原始 URL 转换为 RSS 地址"""
    if "voachinese.com/China" in original_url:
        return f"{RSSHUB_INSTANCE}/voachinese/china"
    if "voachinese.com/p/6197.html" in original_url:
        return f"{RSSHUB_INSTANCE}/voachinese/6197"
    if "bbc.com/zhongwen/simp" in original_url:
        # 尝试 BBC 自带 RSS
        return "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"
    if "rfa.org/mandarin" in original_url:
        return f"{RSSHUB_INSTANCE}/rfa/mandarin"
    if "dw.com/zh" in original_url:
        return f"{RSSHUB_INSTANCE}/dw/rss/zh/s-9058"
    if "rfi.fr/cn" in original_url:
        return f"{RSSHUB_INSTANCE}/rfi/cn"
    if "cn.nytimes.com" in original_url:
        return f"{RSSHUB_INSTANCE}/nytimes/zh"
    if "zaobao.com/realtime/china" in original_url:
        # 联合早报自带 RSS
        return "https://www.zaobao.com/realtime/china/feed"
    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        return f"{NITTER_INSTANCE}/{username}/rss"
    return original_url

def fetch_rss_items(rss_url, original_url):
    """抓取单个 RSS，返回过去24小时内的条目（最多12条）"""
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(rss_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            print(f"  HTTP {resp.status_code} - {original_url}")
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
                "source": original_url,
                "fetched_at": datetime.utcnow().isoformat()
            })
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        print(f"  抓取异常 {original_url}: {e}")
        return []

def fetch_all_sources():
    print(f"开始抓取 {len(RAW_SOURCES)} 个信源（过去24小时）...")
    all_items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_rss_items, url_to_rss(url), url): url for url in RAW_SOURCES}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"✓ {url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {url} 失败: {e}")
    return all_items

# ================= AI 分析（OpenRouter）=================
def call_ai_analysis(all_articles):
    if not OPENROUTER_API_KEY:
        return "# AI 分析失败\nOPENROUTER_API_KEY 未设置，请检查 Secrets。"
    if not all_articles:
        return "# 无数据\n过去24小时未抓取到任何文章。"

    # 限制传给 AI 的文章数量（避免 token 超限）
    max_articles = 40
    selected = all_articles[:max_articles]
    content_list = []
    for idx, art in enumerate(selected, 1):
        content_list.append(
            f"{idx}. 标题：{art.get('title', '')[:150]}\n"
            f"   摘要：{art.get('summary', '')[:200]}\n"
            f"   链接：{art.get('link', '')}\n"
        )
    combined = "\n".join(content_list)

    prompt = f"""你是一名专业的网络安全和舆情分析师。

以下是过去24小时从多个信源（包括 VOA、BBC、RFA、DW、RFI、纽约时报、联合早报及 X 平台）抓取到的部分内容（共 {len(selected)} 条，总抓取 {len(all_articles)} 条）。

请严格按照以下格式生成**内容安全行业舆情报告**：

# 内容安全行业舆情报告
生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

| 事件简述 | 原文链接 | 潜在风险点 |
|----------|----------|------------|
| （简述，不超过60字） | [查看](链接) | （风险点，不超过30字） |

要求：
- 只输出涉华内容（涉及中国、中共、习近平、台湾、香港、新疆、西藏、南海、中美关系等）。
- 如果没有任何涉华内容，只输出一行“过去24小时无涉华内容”。
- 不要添加任何额外解释、开头语或结束语。

抓取内容如下：
{combined}"""

    try:
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": AI_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 2500
            },
            timeout=90
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"# AI 分析失败\nHTTP {response.status_code}\n{response.text[:500]}"
    except Exception as e:
        return f"# AI 分析失败\n异常: {str(e)}"

# ================= 保存报告 =================
def save_reports(markdown_report, all_articles):
    # 1. Markdown
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(markdown_report)

    # 2. HTML 报告（表格可点击）
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
<p>注：本报告由 AI 自动生成，基于过去24小时抓取的 {len(all_articles)} 条原始内容。</p>
</div>
</body>
</html>"""
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    # 3. 保存原始数据
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    with open(f"data/raw_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"报告已保存: report.md, report.html")
    print(f"原始数据保存: data/raw_{timestamp}.json")

# ================= 主函数 =================
def main():
    start = time.time()
    print("=== 开始抓取信源（过去24小时） ===")
    all_articles = fetch_all_sources()
    print(f"共抓取 {len(all_articles)} 条文章，耗时 {time.time()-start:.1f} 秒")

    if not all_articles:
        print("⚠️ 未抓到任何文章，请检查网络或 RSS 源。")
        with open("report.md", "w") as f:
            f.write("# 抓取失败\n\n未抓到任何文章，请检查 Actions 日志。")
        return

    print("=== 调用 AI 分析 ===")
    report = call_ai_analysis(all_articles)

    save_reports(report, all_articles)
    print(f"全部完成，总耗时 {time.time()-start:.1f} 秒")

if __name__ == "__main__":
    main()
