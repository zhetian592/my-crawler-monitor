#!/usr/bin/env python3
# crawler.py - 优化版：严格时间过滤 + token 分批 + 精确优先级 + 历史归档 + 跨源去重 + Nitter 健康检查
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

# Nitter 实例池（带健康状态）
NITTER_INSTANCES = {
    "https://nitter.net": {"healthy": True, "fail_count": 0},
    "https://nitter.poast.org": {"healthy": True, "fail_count": 0},
    "https://nitter.private.coffee": {"healthy": True, "fail_count": 0},
    "https://nitter.42l.fr": {"healthy": True, "fail_count": 0},
}
# 禁用阈值：连续失败 3 次则标记为不健康
NITTER_FAIL_THRESHOLD = 3

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36",
]

# 精确报告源白名单（域名或路径片段）
REPORT_SOURCES_WHITELIST = [
    "uscc.gov", "dni.gov", "selectcommitteeontheccp.house.gov", "cnas.org",
    "gov.uk/government/collections/six-monthly-report-on-hong-kong", "csri.global",
    "hrw.org", "amnesty.org", "freedomhouse.org", "aspi.org.au",
    "chinapower.csis.org", "jamestown.org", "cecc.gov", "wqw2010.blogspot.com"
]

# ================= 信源列表（与之前相同，此处省略，请保留你最后的 RAW_SOURCES） =================
RAW_SOURCES = [
    # ... 这里保持你原有的完整列表（包括新闻、X账号、报告源）...
    # 由于篇幅限制，请从你之前的代码中复制 RAW_SOURCES 完整内容到这里
]
# 注意：实际使用时请确保 RAW_SOURCES 已包含所有你需要的源

# ================= 辅助函数 =================
def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text().strip()[:500]

def parse_published_strict(published_str):
    """严格解析时间，支持多种格式，无法解析时返回 None"""
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

def is_report_source(source_url):
    """精确判断是否为报告型信源"""
    source_lower = source_url.lower()
    return any(domain in source_lower for domain in REPORT_SOURCES_WHITELIST)

def content_hash(title, summary):
    """生成内容哈希，用于跨源去重"""
    text = (title + " " + summary)[:500]
    return hashlib.md5(text.encode('utf-8')).hexdigest()

def fetch_single_rss(rss_url, original_url, processed_hashes):
    """抓取 RSS，严格时间过滤 + 内容哈希去重"""
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
            # 严格时间过滤
            published = entry.get("published", entry.get("updated", ""))
            pub_dt = parse_published_strict(published)
            if pub_dt is None:
                # 无法解析时间，则跳过（避免旧内容混入）
                print(f"  ⚠ 跳过无有效时间的条目: {entry.get('title', '')[:50]}")
                continue
            if pub_dt < cutoff:
                continue
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = clean_html(entry.get("content", [{}])[0].get("value", ""))
            if not summary:
                summary = title
            # 跨源去重
            h = content_hash(title, summary)
            if h in processed_hashes:
                continue
            processed_hashes.add(h)
            items.append({
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary,
                "source": original_url,
                "fetched_at": datetime.utcnow().isoformat(),
                "published": published,
                "is_report": is_report_source(original_url)
            })
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        print(f"  ✗ 抓取异常 {original_url}: {e}")
        return []

def fetch_with_retry(original_url, processed_hashes):
    """带重试的抓取，支持 X 账号健康检查"""
    # X 账号处理
    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        # 获取当前健康的 Nitter 实例列表
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
                # 成功，重置该实例的失败计数
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
    # 普通网站
    rss_candidates = url_to_rss(original_url)  # 需要你保留原有的 url_to_rss 函数
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
    # 使用全局哈希集合跨源去重
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

def call_ai_analysis_batch(all_articles, max_tokens_per_batch=3000):
    """
    分批调用 AI，避免 token 超限。
    返回合并后的 Markdown 报告。
    """
    if not GH_TOKEN:
        return "# AI 分析失败\nGH_MODELS_TOKEN 未设置"
    if not all_articles:
        return "# 无数据\n未抓取到任何文章"

    # 估算 token 数（粗略：1 token ≈ 0.75 汉字，取 1.5 倍安全）
    def estimate_tokens(text):
        return len(text) * 1.5

    # 构建内容列表
    content_blocks = []
    for idx, art in enumerate(all_articles, 1):
        tag = "【报告】" if art.get("is_report") else ""
        block = f"{idx}. {tag}标题：{art.get('title', '')[:150]}\n摘要：{art.get('summary', '')[:300]}\n链接：{art.get('link', '')}\n"
        content_blocks.append(block)

    # 分批
    batches = []
    current_batch = []
    current_tokens = 0
    prompt_prefix = """你是一名专业的网络安全和舆情分析师。你的任务是：从以下内容中筛选出**涉及中国的负面舆情**。

**重要说明**：
- 对于标记为 `【报告】` 的条目，请优先将其排在报告的最前面，并在最终输出的“事件简述”列中也保留 `【报告】` 标记。
- 只输出**负面涉华**内容，不要输出正面或中性内容。
- 使用 Markdown 表格格式，表格头：| 事件简述 | 原文链接 | 潜在风险点 |
- 每一条负面内容单独占一行。
- 原文链接列使用 `[查看](URL)` 格式。
- 如果没有任何负面涉华内容，只输出一行“过去24小时无涉华负面内容”。
- 不要添加任何额外解释。

以下是抓取到的部分内容：\n\n"""
    prompt_tokens = estimate_tokens(prompt_prefix)

    for block in content_blocks:
        block_tokens = estimate_tokens(block)
        if current_tokens + block_tokens + prompt_tokens > max_tokens_per_batch and current_batch:
            batches.append(current_batch)
            current_batch = []
            current_tokens = 0
        current_batch.append(block)
        current_tokens += block_tokens
    if current_batch:
        batches.append(current_batch)

    print(f"共 {len(all_articles)} 条内容，分为 {len(batches)} 批进行 AI 分析")

    combined_report = ""
    client = openai.OpenAI(base_url=AI_BASE_URL, api_key=GH_TOKEN)

    for batch_idx, batch in enumerate(batches, 1):
        combined = "\n".join(batch)
        prompt = prompt_prefix + combined
        try:
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                max_tokens=2000,
            )
            batch_report = response.choices[0].message.content
            combined_report += f"\n## 批次 {batch_idx}\n\n{batch_report}\n"
        except Exception as e:
            print(f"AI 分析批次 {batch_idx} 失败: {e}")
            combined_report += f"\n## 批次 {batch_idx} 分析失败\n\n异常: {str(e)}\n"

    # 合并后如果有多个批次，可以再调用一次 AI 进行去重合并（可选，这里简单拼接）
    return combined_report

def save_reports_with_history(report_text, all_articles):
    """保存最新报告 + 历史归档 + 索引页"""
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    # 最新版本
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(report_text)
    # 生成 HTML（与之前相同，略）
    html_content = generate_html_report(report_text, all_articles)
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)

    # 历史归档
    os.makedirs("reports", exist_ok=True)
    history_path = f"reports/report_{timestamp}.html"
    with open(history_path, "w", encoding="utf-8") as f:
        f.write(html_content)

    # 生成索引页
    generate_index_page()

    # 保存原始数据
    os.makedirs("data", exist_ok=True)
    with open(f"data/raw_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print(f"报告已保存: report.html, report.md, 历史归档 {history_path}")

def generate_index_page():
    """生成 reports/index.html 列出所有历史报告"""
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

def generate_html_report(report_text, all_articles):
    """生成 HTML 报告（与之前相同，略）"""
    # 这里粘贴你原来 save_reports 中的 HTML 生成逻辑，或者复用之前的函数
    # 为了简洁，省略具体代码，实际使用时请补全
    return "<html>...</html>"

def main():
    start = time.time()
    print("=== 开始抓取信源（过去24小时） ===")
    all_articles = fetch_all_sources()
    print(f"抓取完成，共 {len(all_articles)} 条有效文章，耗时 {time.time()-start:.1f} 秒")
    if not all_articles:
        print("⚠️ 未抓到任何文章")
        with open("report.md", "w") as f:
            f.write("# 抓取失败\n\n未抓到任何文章，请检查日志。")
        return
    print("=== 调用 AI 分析（分批处理） ===")
    report = call_ai_analysis_batch(all_articles)
    save_reports_with_history(report, all_articles)
    print(f"全部完成，总耗时 {time.time()-start:.1f} 秒")

if __name__ == "__main__":
    main()
