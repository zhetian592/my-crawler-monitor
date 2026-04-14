#!/usr/bin/env python3
# crawler.py - 抓取 RSS 后一次性交给 Grok 生成舆情报告
import os
import json
import feedparser
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ================= 配置 =================
# Grok API 配置（使用 xAI 官方接口）
GROK_API_KEY = os.environ.get("GROK_API_KEY")
GROK_MODEL = "grok-beta"  # 或 "grok-2-latest"，根据实际可用模型调整
GROK_BASE_URL = "https://api.x.ai/v1"   # xAI 官方 endpoint

# 信源列表（原始 URL，脚本内自动转换为 RSS）
RAW_SOURCES = [
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
    "https://x.com/ChingteLai",
    "https://x.com/YesterdayBigcat",
    "https://x.com/wangzhian8848",
    "https://x.com/wangdan1989",
    "https://x.com/wuerkaixi",
    "https://x.com/Chai20230817",
    "https://x.com/newszg_official",
    "https://x.com/realcaixia",
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

# 将原始 URL 转换为 RSS 地址
def url_to_rss(url):
    """根据原始 URL 返回 RSS 地址"""
    # 新闻网站
    if "voachinese.com/China" in url:
        return "https://rsshub.app/voachinese/china"
    if "voachinese.com/p/6197.html" in url:
        return "https://rsshub.app/voachinese/6197"
    if "bbc.com/zhongwen/simp" in url:
        return "https://rsshub.app/bbc/zhongwen/simp"
    if "rfa.org/mandarin" in url:
        return "https://rsshub.app/rfa/mandarin"
    if "dw.com/zh" in url:
        return "https://rsshub.app/dw/rss/zh/s-9058"
    if "rfi.fr/cn" in url:
        return "https://rsshub.app/rfi/cn"
    if "cn.nytimes.com" in url:
        return "https://rsshub.app/nytimes/zh"
    if "zaobao.com/realtime/china" in url:
        return "https://rsshub.app/zaobao/realtime/china"
    # X 账号
    if "x.com/" in url:
        username = url.split("/")[-1]
        # 使用 Nitter 实例（如果 nitter.net 被墙，可换其他实例）
        return f"https://nitter.net/{username}/rss"
    # 默认返回原链接（不可用，会失败）
    return url

# ================= 抓取 RSS =================
def clean_html(html_text):
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text().replace("\n", " ").strip()

def fetch_rss_items(rss_url, original_url):
    """抓取单个 RSS 源，返回过去24小时内的条目列表"""
    try:
        feed = feedparser.parse(rss_url)
        if feed.bozo:
            print(f"  警告: {original_url} 解析异常")
        cutoff = datetime.utcnow() - timedelta(hours=24)
        items = []
        for entry in feed.entries:
            # 解析时间
            published = entry.get("published", entry.get("updated", ""))
            if published:
                try:
                    # 尝试多种格式
                    pub_time = None
                    for fmt in ("%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S"):
                        try:
                            pub_time = datetime.strptime(published, fmt)
                            break
                        except:
                            continue
                    if pub_time and pub_time.replace(tzinfo=None) < cutoff:
                        continue
                except:
                    pass  # 时间解析失败则保留
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = clean_html(entry.get("content", [{}])[0].get("value", ""))
            if not summary:
                summary = title
            items.append({
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary[:500],
                "published": published,
                "source": original_url,
                "fetched_at": datetime.utcnow().isoformat()
            })
            if len(items) >= 20:  # 每个源最多20条
                break
        return items
    except Exception as e:
        print(f"  抓取失败 {original_url}: {e}")
        return []

def fetch_all_sources():
    """并发抓取所有信源，返回所有文章列表"""
    rss_urls = [url_to_rss(url) for url in RAW_SOURCES]
    print(f"开始并发抓取 {len(rss_urls)} 个信源...")
    all_items = []
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_rss_items, rss_url, raw_url): raw_url 
                         for raw_url, rss_url in zip(RAW_SOURCES, rss_urls)}
        for future in as_completed(future_to_url):
            raw_url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"✓ {raw_url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {raw_url} 失败: {e}")
    return all_items

# ================= 调用 Grok AI =================
def call_grok_analysis(all_articles):
    """将全部文章提交给 Grok，要求生成舆情报告"""
    if not GROK_API_KEY:
        raise Exception("GROK_API_KEY 未设置，请在环境变量中配置")
    
    # 构建内容列表（每条文章只保留标题、摘要、链接）
    content_list = []
    for idx, art in enumerate(all_articles, 1):
        content_list.append(f"{idx}. 标题：{art['title']}\n   摘要：{art['summary'][:300]}\n   链接：{art['link']}\n")
    combined = "\n".join(content_list)
    
    prompt = f"""你是一名专业的网络安全和舆情分析师。以下是过去24小时内从多个信源（包括VOA、BBC、RFA、DW、RFI、纽约时报、联合早报以及大量X账号）抓取到的所有原创内容。

请仔细阅读这些内容，并完成以下任务：

1. 筛选出其中**涉华**（涉及中国、中共、习近平、台湾、香港、新疆、西藏、南海、中美关系等）的内容。
2. 基于筛选出的涉华内容，生成一份**内容安全行业舆情报告**，报告格式如下：

### 舆情报告

| 事件简述 | 原文链接 | 潜在风险点 |
|----------|----------|------------|
| （简述事件，不超过50字） | （可点击的链接） | （风险点，不超过30字） |
| ... | ... | ... |

**要求**：
- 每一条涉华内容单独一行。
- “原文链接”列中，请使用 Markdown 格式 `[链接](原文URL)` 或直接给出可点击的HTML链接。
- “潜在风险点”需从政治风险、社会稳定、国际关系等角度分析，每条不超过30字。
- 如果没有任何涉华内容，请输出“过去24小时无涉华内容”。

以下是所有抓取到的内容：

{combined}

请直接输出上述格式的报告，不要添加额外解释。"""

    # 调用 Grok API（使用 OpenAI 兼容接口）
    from openai import OpenAI
    client = OpenAI(
        api_key=GROK_API_KEY,
        base_url=GROK_BASE_URL,
    )
    try:
        response = client.chat.completions.create(
            model=GROK_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=4000,
        )
        report = response.choices[0].message.content
        return report
    except Exception as e:
        print(f"Grok API 调用失败: {e}")
        # 降级：返回错误信息
        return f"# Grok 分析失败\n\n错误信息：{str(e)}\n\n请检查 API Key 和网络设置。"

# ================= 保存报告 =================
def save_report(report_text):
    """保存报告为 HTML 和 Markdown 格式"""
    # 保存为 Markdown
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report_text)
    
    # 尝试将 Markdown 表格转换为 HTML（简单处理）
    html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>舆情报告</title>
<style>
    body {{ font-family: Arial, sans-serif; margin: 20px; }}
    table {{ border-collapse: collapse; width: 100%; margin-top: 20px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
    a {{ color: #0366d6; text-decoration: none; }}
    a:hover {{ text-decoration: underline; }}
</style>
</head>
<body>
<h1>内容安全行业舆情报告</h1>
<p>生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
<hr>
<div id="report">
"""
    # 简单转换：将 Markdown 表格转为 HTML 表格（基础版）
    lines = report_text.split("\n")
    in_table = False
    table_html = ""
    for line in lines:
        if line.startswith("|") and "|" in line:
            if not in_table:
                in_table = True
                table_html = '<table>\n'
            cells = [c.strip() for c in line.split("|")[1:-1]]
            if line.startswith("|---"):
                continue
            table_html += "<tr>\n"
            for cell in cells:
                # 处理 Markdown 链接 [text](url)
                if "[" in cell and "](" in cell:
                    import re
                    match = re.search(r'\[(.*?)\]\((.*?)\)', cell)
                    if match:
                        text, url = match.group(1), match.group(2)
                        cell = f'<a href="{url}" target="_blank">{text}</a>'
                table_html += f"<td>{cell}</td>\n"
            table_html += "</tr>\n"
        else:
            if in_table:
                table_html += "</table>\n"
                html_content += table_html
                in_table = False
                table_html = ""
            html_content += line + "<br>\n"
    if in_table:
        html_content += table_html + "</table>\n"
    html_content += "</div></body></html>"
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    print("报告已保存为 report.md 和 report.html")

# ================= 主流程 =================
def main():
    start_time = time.time()
    print("=== 开始抓取所有信源过去24小时内容 ===")
    all_articles = fetch_all_sources()
    print(f"共抓取到 {len(all_articles)} 条文章，耗时 {time.time()-start_time:.1f} 秒")
    
    if not all_articles:
        print("未抓取到任何内容，退出")
        return
    
    print("=== 提交给 Grok AI 分析并生成报告 ===")
    report = call_grok_analysis(all_articles)
    
    save_report(report)
    print(f"全部完成，总耗时 {time.time()-start_time:.1f} 秒")

if __name__ == "__main__":
    main()
