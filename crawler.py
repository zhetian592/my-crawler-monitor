#!/usr/bin/env python3
# crawler.py - 两阶段处理：先并发抓取，后 AI 分析
import os
import json
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ================= 配置 =================
# 是否启用 AI 分析（通过环境变量控制，默认 false）
ENABLE_AI = os.environ.get("ENABLE_AI", "").lower() == "true"

# OpenRouter API Key（仅当启用 AI 时需要）
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

# 信源配置（已全部转换为 RSS 地址）
TIER_SOURCES = {
    "1": [
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/voachinese/6197",
        "https://rsshub.app/bbc/zhongwen/simp",
        "https://rsshub.app/rfa/mandarin",
        "https://rsshub.app/dw/rss/zh/s-9058",
        "https://rsshub.app/rfi/cn",
        "https://rsshub.app/nytimes/zh",
        "https://rsshub.app/zaobao/realtime/china",
        # X 用户（Nitter RSS）
        "https://nitter.net/whyyoutouzhele/rss",
        "https://nitter.net/ChingteLai/rss",
        "https://nitter.net/YesterdayBigcat/rss",
        "https://nitter.net/wangzhian8848/rss",
        "https://nitter.net/wangdan1989/rss",
        "https://nitter.net/wuerkaixi/rss",
        "https://nitter.net/Chai20230817/rss",
        "https://nitter.net/newszg_official/rss",
        "https://nitter.net/realcaixia/rss",
        "https://nitter.net/june4thmuseum/rss",
        "https://nitter.net/hrw_chinese/rss",
        "https://nitter.net/torontobigface/rss",
        "https://nitter.net/dayangelcp/rss",
        "https://nitter.net/chinatransition/rss",
        "https://nitter.net/pear14525902/rss",
        "https://nitter.net/RedPigCartoon/rss",
        "https://nitter.net/Cian_Ci/rss",
        "https://nitter.net/remonwangxt/rss",
        "https://nitter.net/xinwendiaocha/rss",
        "https://nitter.net/Ruters0615/rss",
        "https://nitter.net/ZhouFengSuo/rss",
        "https://nitter.net/gaoyu200812/rss",
        "https://nitter.net/lidangzzz/rss",
        "https://nitter.net/YongyuanCui1/rss",
        "https://nitter.net/xiaojingcanxue/rss",
        "https://nitter.net/xiangjunweiwu/rss",
        "https://nitter.net/tibetdotcom/rss",
        "https://nitter.net/UHRP_Chinese/rss",
        "https://nitter.net/XiJPDynasty/rss",
        "https://nitter.net/chonglangzhiyin/rss",
        "https://nitter.net/xingzhe2021/rss",
        "https://nitter.net/jhf8964/rss",
        "https://nitter.net/fangshimin/rss",
        "https://nitter.net/badiucao/rss",
        "https://nitter.net/WOMEN4China/rss",
        "https://nitter.net/CitizensDailyCN/rss",
        "https://nitter.net/hchina89/rss",
        "https://nitter.net/amnestychinese/rss",
        "https://nitter.net/liangziyueqian1/rss",
        "https://nitter.net/jielijian/rss",
        "https://nitter.net/CHENWEIMING2017/rss",
        "https://nitter.net/BoKuangyi/rss",
        "https://nitter.net/chinesepen_org/rss",
        "https://nitter.net/wurenhua/rss",
    ],
    "2": [],
    "3": []
}

# 涉华关键词（用于过滤）
CHINA_KEYWORDS = [
    "中国", "中共", "北京", "习近平", "台湾", "香港", "新疆", "西藏",
    "南海", "中美", "华为", "字节跳动", "TikTok", "一带一路", "武统"
]

# ================= 辅助函数 =================
def is_china_related(text):
    """关键词匹配判断是否涉华"""
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in CHINA_KEYWORDS)

def clean_html(html_text):
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text().replace("\n", " ").strip()

def generate_risk_point(title, summary):
    """基于规则的快速风险点（无 AI）"""
    t = title + " " + summary
    if "台湾" in t:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in t:
        return "涉及新疆议题，需防范西方舆论炒作"
    if "南海" in t:
        return "地缘政治敏感，可能引发区域紧张"
    if "华为" in t and "制裁" in t:
        return "科技供应链风险"
    return "可能引起网络舆论关注"

def fetch_rss_items(url):
    """抓取单个 RSS 源，返回原始条目列表（不做任何过滤）"""
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:20]:
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
                "published": entry.get("published", ""),
                "source": url,
                "fetched_at": datetime.utcnow().isoformat()
            })
        return items
    except Exception as e:
        print(f"  抓取失败 {url}: {e}")
        return []

# ================= AI 分析（可选） =================
def analyze_with_ai(title, summary):
    """调用 OpenRouter API 进行分析，返回 (analysis_summary, risk_point)"""
    if not ENABLE_AI or not OPENROUTER_API_KEY:
        return ("", generate_risk_point(title, summary))
    
    # 延迟导入，避免未安装 openai 时报错
    from openai import OpenAI
    client = OpenAI(
        base_url="https://openrouter.ai/api/v1",
        api_key=OPENROUTER_API_KEY,
    )
    prompt = f"""你是一名专业的网络安全和舆情分析师。请分析以下内容，并输出JSON格式结果。

标题：{title}
摘要：{summary[:500]}

要求：
1. "analysis_summary": 一句话概括核心观点，不超过50字。
2. "risk_point": 指出潜在风险点，不超过30字。

输出格式：{{"analysis_summary": "...", "risk_point": "..."}}"""
    try:
        completion = client.chat.completions.create(
            model="meta-llama/llama-3.2-3b-instruct:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        result = json.loads(completion.choices[0].message.content)
        return (result.get("analysis_summary", "")[:50], result.get("risk_point", "")[:30])
    except Exception as e:
        print(f"AI分析失败: {e}")
        return ("", generate_risk_point(title, summary))

def batch_ai_analysis(china_items):
    """对涉华条目列表进行 AI 分析（支持小并发）"""
    if not china_items:
        return
    print(f"开始 AI 分析，共 {len(china_items)} 条涉华内容")
    start = time.time()
    
    # 使用小并发（2-3个）避免 API 限流
    with ThreadPoolExecutor(max_workers=3) as executor:
        future_to_idx = {}
        for idx, item in enumerate(china_items):
            future = executor.submit(analyze_with_ai, item["title"], item["summary"])
            future_to_idx[future] = idx
        
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            try:
                summary, risk = future.result()
                china_items[idx]["analysis_summary"] = summary
                china_items[idx]["risk_point"] = risk
            except Exception as e:
                print(f"AI分析第 {idx} 条失败: {e}")
                china_items[idx]["analysis_summary"] = ""
                china_items[idx]["risk_point"] = generate_risk_point(
                    china_items[idx]["title"], china_items[idx]["summary"]
                )
    
    print(f"AI 分析完成，耗时 {time.time()-start:.1f} 秒")

# ================= 报告生成 =================
def generate_html_report(china_items, tier, timestamp):
    """生成 HTML 报告，链接可点击"""
    if not china_items:
        return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>舆情报告</title></head>
<body>
<h1>舆情报告 (Tier {tier})</h1>
<p>生成时间：{timestamp}</p>
<p>过去24小时无涉华内容。</p>
</body>
</html>"""
    
    rows = ""
    for item in china_items:
        summary = item.get("analysis_summary") or item["title"] or item["summary"][:100]
        link = item["link"]
        risk = item.get("risk_point", "")
        rows += f"""<
<tr>
            <td>{summary}</td>
            <td><a href="{link}" target="_blank">查看原文</a></td>
            <td>{risk}</td>
        </tr>\n"""
    
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>舆情报告</title>
<style>
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f2f2f2; }}
</style>
</head>
<body>
<h1>舆情报告 (Tier {tier})</h1>
<p>生成时间：{timestamp}</p>
<table>
    <thead>
        <tr><th>事件简述</th><th>原文链接</th><th>潜在风险点</th></tr>
    </thead>
    <tbody>
{rows}
    </tbody>
</table>
</body>
</html>"""

def generate_markdown_report(china_items, tier, timestamp):
    """生成 Markdown 报告（备用）"""
    if not china_items:
        return f"# 舆情报告 (Tier {tier})\n\n生成时间：{timestamp}\n\n过去24小时无涉华内容。\n"
    lines = [
        f"# 舆情报告 (Tier {tier})",
        f"生成时间：{timestamp}",
        "",
        "| 事件简述 | 原文链接 | 潜在风险点 |",
        "|---------|----------|------------|"
    ]
    for item in china_items:
        summary = item.get("analysis_summary") or item["title"] or item["summary"][:100]
        link = item["link"]
        risk = item.get("risk_point", "")
        lines.append(f"| {summary} | [链接]({link}) | {risk} |")
    return "\n".join(lines)

# ================= 主流程 =================
def main():
    tier = os.getenv("TIER", "2")
    sources = TIER_SOURCES.get(tier, [])
    if not sources:
        print(f"警告: Tier {tier} 没有配置信源")
        return

    print(f"=== 阶段一：并发抓取 RSS（共 {len(sources)} 个信源）===")
    start_time = time.time()
    all_items = []
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        future_to_url = {executor.submit(fetch_rss_items, url): url for url in sources}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"✓ {url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {url} 失败: {e}")
    
    fetch_time = time.time() - start_time
    print(f"抓取完成，共获取 {len(all_items)} 条原始内容，耗时 {fetch_time:.1f} 秒")

    # 保存原始数据（未过滤、未分析）
    os.makedirs("data", exist_ok=True)
    timestamp_str = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    raw_file = f"data/raw_tier{tier}_{timestamp_str}.json"
    with open(raw_file, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    print(f"原始数据已保存到 {raw_file}")

    # === 阶段二：过滤涉华内容 + AI 分析 ===
    print("\n=== 阶段二：过滤涉华内容 ===")
    china_items = []
    for item in all_items:
        full_text = item["title"] + " " + item["summary"]
        if is_china_related(full_text):
            china_items.append(item)
    print(f"涉华内容 {len(china_items)} 条（占比 {len(china_items)/len(all_items)*100:.1f}%）")

    if ENABLE_AI and OPENROUTER_API_KEY:
        batch_ai_analysis(china_items)
    else:
        print("AI 分析未启用（ENABLE_AI=false 或未设置 API Key），使用规则生成风险点")
        for item in china_items:
            item["analysis_summary"] = ""
            item["risk_point"] = generate_risk_point(item["title"], item["summary"])

    # === 阶段三：生成报告 ===
    print("\n=== 阶段三：生成报告 ===")
    now_str = datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S') + " UTC"
    html_content = generate_html_report(china_items, tier, now_str)
    md_content = generate_markdown_report(china_items, tier, now_str)

    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(md_content)
    
    print(f"报告已生成：report.html 和 report.md")
    print(f"总耗时 {time.time() - start_time:.1f} 秒")

if __name__ == "__main__":
    main()
