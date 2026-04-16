#!/usr/bin/env python3
# crawler.py - 统一分析，AI 自动识别报告并优先展示，增加信息来源列，自动清理旧文件
import os
import json
import feedparser
import time
import requests
import re
import random
import hashlib
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

RSSHUB_INSTANCES = ["https://rsshub.app", "https://rsshub.ktachibana.party"]

NITTER_INSTANCES = {
    "https://nitter.net": {"healthy": True, "fail_count": 0},
    "https://nitter.poast.org": {"healthy": True, "fail_count": 0},
    "https://nitter.private.coffee": {"healthy": True, "fail_count": 0},
    "https://nitter.42l.fr": {"healthy": True, "fail_count": 0},
}
NITTER_FAIL_THRESHOLD = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]

# 保留历史报告的天数（可修改）
KEEP_DAYS = 7

# ================= 信源列表 =================
RAW_SOURCES = [
    "https://www.bbc.com/zhongwen/simp",
    "https://www.rfa.org/mandarin",
    "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
    "https://www.rfi.fr/cn/",
    "https://cn.nytimes.com/",
    "https://www.ntdtv.com/gb/instant-news.html",
    "https://www.epochtimes.com/gb/instant-news.htm",
    "https://x.com/whyyoutouzhele",
    "https://x.com/wangzhian8848",
    "https://x.com/newszg_official",
    "https://x.com/wangdan1989",
    "https://x.com/torontobigface",
    "https://x.com/hrw_chinese",
    "https://x.com/dayangelcp",
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
    "https://x.com/wurenhua",
    "https://x.com/zaobaosg",
    "https://x.com/dajiyuan",
    "https://x.com/NTDChinese",
    "https://x.com/VOAChinese",
    "https://x.com/USCC_GOV",
    "https://x.com/ODNIgov",
    "https://x.com/ChinaSelect",
    "https://x.com/CNASdc",
    "https://x.com/CSR_Institute",
    "https://x.com/hrw",
    "https://x.com/amnesty",
    "https://x.com/FreedomHouse",
    "https://x.com/ASPI_org",
    "https://x.com/JamestownFdn",
    "https://x.com/CECCgov",
]

# ================= 辅助函数 =================
def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text().strip()[:500]

def parse_published_strict(published_str):
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
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
        except:
            continue
    return None

def content_hash(title, summary):
    text = (title + " " + summary)[:500]
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def url_to_rss(url):
    rsshub = random.choice(RSSHUB_INSTANCES)
    if "voachinese.com" in url:
        return [f"{rsshub}/voachinese/china", "http://feeds.feedburner.com/voacn"]
    if "bbc.com/zhongwen/simp" in url:
        return "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"
    if "rfa.org/mandarin" in url:
        return [f"{rsshub}/rfa/mandarin", "https://www.rfa.org/mandarin/rss"]
    if "dw.com/zh" in url:
        return "https://rss.dw.com/rdf/rss-chi-all"
    if "rfi.fr/cn" in url:
        return "https://www.rfi.fr/cn/general/rss"
    if "cn.nytimes.com" in url:
        return "https://cn.nytimes.com/rss/news.xml"
    if "ntdtv.com" in url:
        return [f"{rsshub}/ntdtv/instant-news", "https://www.ntdtv.com/gb/feed"]
    if "epochtimes.com" in url:
        return [f"{rsshub}/epochtimes/gb", "https://www.epochtimes.com/gb/feed"]
    if "x.com/" in url:
        return None
    if "uscc.gov" in url:
        return f"{rsshub}/uscc/reports"
    return url

def fetch_single_rss(rss_url, original_url, processed_hashes):
    try:
        headers = {"User-Agent": random.choice(USER_AGENTS)}
        time.sleep(random.uniform(0.5, 1.8))
        resp = requests.get(rss_url, headers=headers, timeout=25)
        if resp.status_code != 200:
            print(f"  ⚠ HTTP {resp.status_code} - {original_url}")
            return []
        feed = feedparser.parse(resp.content)
        cutoff = datetime.utcnow() - timedelta(hours=24)
        items = []
        for entry in feed.entries:
            published_str = entry.get("published", entry.get("updated", ""))
            pub_dt = parse_published_strict(published_str)
            if pub_dt is not None and pub_dt < cutoff:
                continue
            if pub_dt is None:
                print(f"  ⚠ 时间字段缺失或无法解析，保留条目: {entry.get('title', '')[:50]}")
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = clean_html(entry.get("content", [{}])[0].get("value", ""))
            if not summary:
                summary = title
            h = content_hash(title, summary)
            if h in processed_hashes:
                continue
            processed_hashes.add(h)
            # 提取友好的来源名称
            if "x.com/" in original_url:
                parts = original_url.split("/")
                source_name = "@" + parts[3] if len(parts) > 3 else original_url
            else:
                domain_match = re.search(r'https?://([^/]+)', original_url)
                source_name = domain_match.group(1) if domain_match else original_url
            items.append({
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary,
                "source": original_url,
                "source_name": source_name,
                "published_str": published_str if published_str else "未知时间",
                "fetched_at": datetime.utcnow().isoformat()
            })
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        print(f"  ✗ 抓取异常 {original_url}: {e}")
        return []

def fetch_with_retry(original_url, processed_hashes):
    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        healthy_instances = [inst for inst, status in NITTER_INSTANCES.items() if status["healthy"]]
        if not healthy_instances:
            print(f"  ✗ 无健康的 Nitter 实例，跳过 X 账号 {username}")
            return []
        for nitter in healthy_instances:
            test_url = f"{nitter}/{username}/rss"
            print(f"  → 尝试 X {username} 使用 {nitter}")
            items = fetch_single_rss(test_url, original_url, processed_hashes)
            if items:
                print(f"  ✓ X {username} 成功 via {nitter} (条数: {len(items)})")
                NITTER_INSTANCES[nitter]["fail_count"] = 0
                return items
            else:
                print(f"  ⚠ X {username} 失败 via {nitter}")
                NITTER_INSTANCES[nitter]["fail_count"] += 1
                if NITTER_INSTANCES[nitter]["fail_count"] >= NITTER_FAIL_THRESHOLD:
                    NITTER_INSTANCES[nitter]["healthy"] = False
                    print(f"  ⚠ Nitter 实例 {nitter} 已标记为不健康")
            time.sleep(0.5)
        print(f"  ✗ X {username} 所有健康实例均失败")
        return []
    rss_candidates = url_to_rss(original_url)
    if not rss_candidates:
        print(f"  ✗ 无法生成 RSS 地址: {original_url}")
        return []
    if isinstance(rss_candidates, str):
        rss_candidates = [rss_candidates]
    for rss_url in rss_candidates:
        items = fetch_single_rss(rss_url, original_url, processed_hashes)
        if items:
            print(f"  ✓ {original_url} 成功 (条数: {len(items)}) via {rss_url}")
            return items
        else:
            print(f"  ⚠ {original_url} 失败 via {rss_url}")
        time.sleep(0.5)
    print(f"  ✗ {original_url} 所有 RSS 地址均失败")
    return []

def fetch_all_sources():
    print(f"开始抓取 {len(RAW_SOURCES)} 个信源（过去24小时）...")
    all_items = []
    processed_hashes = set()
    with ThreadPoolExecutor(max_workers=6) as executor:
        future_to_url = {executor.submit(fetch_with_retry, url, processed_hashes): url for url in RAW_SOURCES}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"✓ {url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {url} 异常: {e}")
    print(f"去重后共 {len(all_items)} 条（已通过内容哈希去重）")
    return all_items

def deduplicate_table_rows(rows):
    seen = set()
    unique = []
    for row in rows:
        cells = [c.strip() for c in row.split("|")[1:-1]]
        if not cells:
            continue
        event = cells[0]
        if event not in seen:
            seen.add(event)
            unique.append(row)
    return unique

def call_ai_unified(articles):
    if not articles:
        return "无相关内容。\n"
    
    def estimate_tokens(text):
        return int(len(text) / 1.5)
    
    blocks = []
    for art in articles:
        meta = f"发布时间：{art.get('published_str', '未知')} | 来源：{art.get('source_name', '未知')}"
        block = f"{meta}\n标题：{art.get('title', '')[:150]}\n摘要：{art.get('summary', '')[:300]}\n链接：{art.get('link', '')}\n"
        blocks.append(block)
    
    batches = []
    current_batch = []
    current_tokens = 0
    prompt_prefix = """你是一名专业的网络安全和舆情分析师。你的任务是：从以下内容中筛选出**涉及中国的负面舆情**。

**重要说明**：
- 请优先输出来自官方机构、智库、政府部门的报告类内容（如 USCC、HRW、Amnesty、ASPI 等），这类内容放在表格的前面。
- 对于普通新闻和普通 X 账号的内容，放在报告类内容之后。
- 输出使用 Markdown 表格格式，表格头为：| 事件简述 | 原文链接 | 潜在风险点 | 信息来源 |
- 每一条负面内容单独占一行。
- 原文链接列使用 `[查看](URL)` 格式。
- “信息来源”列填写内容的来源（例如 @USCC_GOV、BBC中文 等）。
- 如果没有任何负面涉华内容，只输出一行“无”。
- 不要添加任何额外解释。

每条内容前已附带“发布时间”和“来源”，请利用这些信息判断时效性和可信度。

以下是抓取到的部分内容：\n\n"""
    prompt_tokens = estimate_tokens(prompt_prefix)
    max_content_tokens = 6000
    for block in blocks:
        block_tokens = estimate_tokens(block)
        if current_tokens + block_tokens + prompt_tokens > max_content_tokens and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        current_batch.append(block)
        current_tokens += block_tokens
    if current_batch:
        batches.append(current_batch)
    
    print(f"共 {len(articles)} 条内容，分为 {len(batches)} 批进行 AI 分析")
    
    all_table_rows = []
    table_header = "| 事件简述 | 原文链接 | 潜在风险点 | 信息来源 |"
    table_sep = "|----------|----------|------------|----------|"
    client = openai.OpenAI(base_url=AI_BASE_URL, api_key=GH_TOKEN)
    for batch_idx, batch in enumerate(batches, 1):
        combined = "\n".join(batch)
        prompt = prompt_prefix + combined
        try:
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=3000,
            )
            content = response.choices[0].message.content
            if content is None:
                print(f"  ✗ AI 分析批次 {batch_idx} 返回空内容，跳过")
                continue
            lines = content.split("\n")
            in_table = False
            for line in lines:
                if line.startswith("|") and "|" in line:
                    if not in_table:
                        in_table = True
                    if re.match(r'^\|[\s\-:]+\|$', line):
                        continue
                    if line.startswith(table_header):
                        continue
                    all_table_rows.append(line)
        except Exception as e:
            print(f"  ✗ AI 分析批次 {batch_idx} 失败: {e}")
            continue
    
    if not all_table_rows:
        return "无相关内容。\n"
    
    unique_rows = deduplicate_table_rows(all_table_rows)
    final_table = "\n".join([table_header, table_sep] + unique_rows)
    return final_table

def generate_html_report(report_text):
    html_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <title>内容安全行业舆情报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 20px; line-height: 1.5; }}
        h1 {{ font-size: 1.8rem; border-bottom: 1px solid #eaecef; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #dfe2e5; padding: 8px 12px; text-align: left; vertical-align: top; }}
        th {{ background-color: #f6f8fa; }}
        a {{ color: #0366d6; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #6a737d; }}
    </style>
</head>
<body>
<h1>📊 内容安全行业舆情报告</h1>
<p>生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
<div id="report">
"""
    lines = report_text.split("\n")
    in_table = False
    for line in lines:
        if line.startswith("|") and "|" in line:
            if not in_table:
                html_content += '<td>\n<thead>\n'
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
                html_content += "</thead><tbody></tbody><table>\n"
                in_table = False
            if line.strip():
                html_content += f"<p>{line}</p>\n"
    if in_table:
        html_content += "</thead><tbody></tbody></table>\n"
    html_content += f"""
</div>
<div class="footer">
    <p>注：本报告由 AI 基于过去24小时抓取的内容自动生成，仅供参考。</p>
</div>
</body>
</html>"""
    return html_content

def save_reports_with_history(report_text, all_articles):
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report_text)
    html_content = generate_html_report(report_text)
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    os.makedirs("reports", exist_ok=True)
    history_path = f"reports/report_{timestamp}.html"
    with open(history_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    generate_index_page()
    os.makedirs("data", exist_ok=True)
    with open(f"data/raw_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)
    print(f"报告已保存: report.html, report.md, 历史归档 {history_path}")

def generate_index_page():
    reports_dir = "reports"
    if not os.path.exists(reports_dir):
        return
    files = [f for f in os.listdir(reports_dir) if f.startswith("report_") and f.endswith(".html")]
    files.sort(reverse=True)
    index_html = """<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>历史舆情报告</title>
<style>body { font-family: sans-serif; margin: 20px; } a { text-decoration: none; }</style>
</head>
<body><h1>历史舆情报告列表</h1><ul>"""
    for f in files:
        timestamp = f.replace("report_", "").replace(".html", "")
        display = timestamp[:4] + "-" + timestamp[4:6] + "-" + timestamp[6:8] + " " + timestamp[9:11] + ":" + timestamp[11:13] + ":" + timestamp[13:15]
        index_html += f'<li><a href="{f}">{display} UTC</a></li>'
    index_html += "</ul><p><a href='../report.html'>查看最新报告</a></p></body></html>"
    with open(os.path.join(reports_dir, "index.html"), "w", encoding="utf-8") as f:
        f.write(index_html)

def cleanup_old_files(days=KEEP_DAYS):
    """删除超过指定天数的历史报告和原始数据文件"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    # 清理 reports/ 下的 report_*.html 文件（保留 index.html）
    reports_dir = "reports"
    if os.path.exists(reports_dir):
        for f in os.listdir(reports_dir):
            if f.startswith("report_") and f.endswith(".html"):
                filepath = os.path.join(reports_dir, f)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if mtime < cutoff:
                        os.remove(filepath)
                        print(f"  🗑 已删除旧报告: {f}")
                except Exception as e:
                    print(f"  ⚠ 删除文件 {f} 失败: {e}")
    # 清理 data/ 下的 raw_*.json 文件
    data_dir = "data"
    if os.path.exists(data_dir):
        for f in os.listdir(data_dir):
            if f.startswith("raw_") and f.endswith(".json"):
                filepath = os.path.join(data_dir, f)
                try:
                    mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
                    if mtime < cutoff:
                        os.remove(filepath)
                        print(f"  🗑 已删除旧数据: {f}")
                except Exception as e:
                    print(f"  ⚠ 删除文件 {f} 失败: {e}")

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
            f.write("<h1>抓取失败</h1><p>未抓到任何文章，请检查日志。</p>")
        return
    print("=== 调用 AI 分析（统一分析，AI 自动识别报告并优先展示） ===")
    report = call_ai_unified(all_articles)
    full_report = "# 📊 内容安全行业舆情报告\n\n" + report
    save_reports_with_history(full_report, all_articles)
    print(f"=== 清理超过 {KEEP_DAYS} 天的旧文件 ===")
    cleanup_old_files()
    print(f"全部完成，总耗时 {time.time()-start:.1f} 秒")

if __name__ == "__main__":
    main()
