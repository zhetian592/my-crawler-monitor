#!/usr/bin/env python3
# crawler.py - 先抓取 → 过滤 → 批量AI分析 → 生成清晰报告
import os
import json
import feedparser
import time
from datetime import datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from openai import OpenAI

# ================= 配置 =================
ENABLE_AI = os.environ.get("ENABLE_AI", "true").lower() == "true"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

TIER_SOURCES = {
    "1": [  # 一级 - 每小时
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/bbc/zhongwen/simp",
        "https://rsshub.app/rfa/mandarin",
        "https://rsshub.app/dw/rss/zh/s-9058",
        "https://rsshub.app/rfi/cn",
        "https://rsshub.app/nytimes/zh",
        "https://rsshub.app/zaobao/realtime/china",
        "https://nitter.net/whyyoutouzhele/rss",
        "https://nitter.net/realcaixia/rss",
        "https://nitter.net/wangzhian8848/rss",
        "https://nitter.net/wangdan1989/rss",
    ],
    "2": [  # 二级 - 每3小时
        "https://rsshub.app/chinadigitaltimes/chinese",
        "https://rsshub.app/epochtimes/gb",
        "https://rsshub.app/pincong/rocks",
    ],
    "3": [  # 三级 - 每6小时
        "https://rsshub.app/theinitium",
        "https://rsshub.app/mingpao",
        "https://rsshub.app/soundofhope",
    ]
}

CHINA_KEYWORDS = ["中国", "中共", "习近平", "台湾", "香港", "新疆", "西藏", "南海", "华为", "六四", "人权", "民主"]

def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text().strip()[:600]

def is_china_related(text):
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in CHINA_KEYWORDS)

def generate_rule_risk(title, summary):
    t = (title + " " + summary).lower()
    if "台湾" in t:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in t or "西藏" in t:
        return "涉及敏感地区，易被舆论炒作"
    if "六四" in t or "人权" in t:
        return "历史/人权议题，舆情风险高"
    return "可能引起网络舆论关注"

# ================= AI 批量分析（全部抓取完后再统一调用） =================
def batch_ai_analysis(items):
    if not ENABLE_AI or not OPENROUTER_API_KEY or not items:
        for item in items:
            item["risk_point"] = generate_rule_risk(item["title"], item["summary"])
        return items

    print(f"开始批量 AI 分析，共 {len(items)} 条涉华内容...")
    client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)

    for item in items:
        try:
            prompt = f"""分析以下内容，只输出JSON：
标题：{item["title"]}
摘要：{item["summary"][:400]}

要求：
- "risk_point": 一句话风险点（严格≤30字）
- "analysis_summary": 一句话核心观点（≤50字）

只返回JSON，不要其他文字。"""

            response = client.chat.completions.create(
                model="meta-llama/llama-3.2-3b-instruct:free",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.3,
                response_format={"type": "json_object"}
            )
            
            result = json.loads(response.choices[0].message.content)
            item["risk_point"] = result.get("risk_point", generate_rule_risk(item["title"], item["summary"]))
            item["analysis_summary"] = result.get("analysis_summary", "")
            
            time.sleep(8)  # 避免免费模型限流（8秒间隔）

        except Exception as e:
            print(f"AI分析失败: {e}")
            item["risk_point"] = generate_rule_risk(item["title"], item["summary"])
            item["analysis_summary"] = ""

    return items

# ================= 主流程 =================
def main():
    tier = os.getenv("TIER", "1")
    sources = TIER_SOURCES.get(tier, [])
    
    print(f"=== Tier {tier} 开始抓取 ===")
    all_items = []
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(lambda u: feedparser.parse(u).entries[:15], url): url for url in sources}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                entries = future.result()
                for entry in entries:
                    title = clean_html(entry.get("title", ""))
                    summary = clean_html(entry.get("summary", entry.get("description", "")))
                    if is_china_related(title + " " + summary):
                        all_items.append({
                            "title": title,
                            "link": entry.get("link", url),
                            "summary": summary
                        })
                print(f"✓ {url} 抓取完成")
            except Exception as e:
                print(f"✗ {url} 失败: {e}")

    print(f"抓取完成，共 {len(all_items)} 条涉华内容")

    # 全部抓取完后再统一做 AI 分析
    all_items = batch_ai_analysis(all_items)

    # 生成清晰表格报告
    now = datetime.utcnow()
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(f"# 内容安全行业舆情报告 (Tier {tier})\n")
        f.write(f"生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n")
        f.write("| 事件简述 | 原文链接 | 潜在风险点 |\n")
        f.write("|----------|----------|------------|\n")
        
        for item in all_items:
            summary = (item.get("analysis_summary") or item["title"])[:120]
            link = item["link"]
            risk = item.get("risk_point", "可能引起网络舆论关注")
            f.write(f"| {summary} | [查看]({link}) | {risk} |\n")

    print("报告生成完成 → report.md")

if __name__ == "__main__":
    main()
