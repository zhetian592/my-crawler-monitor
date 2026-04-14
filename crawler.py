#!/usr/bin/env python3
# crawler.py - 抓取 + AI 分析 + 清晰表格报告
import os
import json
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor
import time

# ================= 配置 =================
ENABLE_AI = os.environ.get("ENABLE_AI", "true").lower() == "true"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")   # 在 GitHub Secrets 中设置

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

def generate_risk_point(title, summary):
    t = (title + summary).lower()
    if "台湾" in t:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in t or "西藏" in t:
        return "涉及敏感地区，易被西方舆论炒作"
    if "六四" in t or "人权" in t:
        return "历史/人权议题，舆情风险高"
    return "可能引起网络舆论关注"

# ================= AI 分析 =================
def analyze_with_ai(title, summary):
    if not ENABLE_AI or not OPENROUTER_API_KEY:
        return generate_risk_point(title, summary)
    
    try:
        from openai import OpenAI
        client = OpenAI(base_url="https://openrouter.ai/api/v1", api_key=OPENROUTER_API_KEY)
        
        prompt = f"""分析以下内容，输出JSON格式：
标题：{title}
摘要：{summary[:400]}

要求：
- "risk_point": 一句话风险点（严格≤30字）
- "analysis_summary": 一句话核心观点（≤50字）

只输出JSON，不要其他文字。"""

        response = client.chat.completions.create(
            model="meta-llama/llama-3.2-3b-instruct:free",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        result = json.loads(response.choices[0].message.content)
        return result.get("risk_point", generate_risk_point(title, summary))
        
    except Exception as e:
        print(f"AI 调用失败: {e}")
        return generate_risk_point(title, summary)

# ================= 主流程 =================
def main():
    tier = os.getenv("TIER", "1")
    sources = TIER_SOURCES.get(tier, [])
    
    print(f"开始抓取 Tier {tier} ...")
    all_items = []
    
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(lambda u: feedparser.parse(u).entries, url) for url in sources]
        for future in futures:
            for entry in future.result()[:15]:
                title = clean_html(entry.get("title", ""))
                summary = clean_html(entry.get("summary", entry.get("description", "")))
                if is_china_related(title + " " + summary):
                    all_items.append({
                        "title": title,
                        "link": entry.get("link", ""),
                        "summary": summary
                    })

    print(f"找到 {len(all_items)} 条涉华内容")

    # AI 分析
    for item in all_items:
        item["risk_point"] = analyze_with_ai(item["title"], item["summary"])

    # 生成清晰 Markdown 报告
    now = datetime.utcnow()
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(f"# 内容安全行业舆情报告 (Tier {tier})\n")
        f.write(f"生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n")
        f.write("| 事件简述 | 原文链接 | 潜在风险点 |\n")
        f.write("|----------|----------|------------|\n")
        
        for item in all_items:
            summary = item["title"][:120]
            link = item["link"]
            risk = item.get("risk_point", "可能引起网络舆论关注")
            f.write(f"| {summary} | [查看]({link}) | {risk} |\n")

    print("报告生成完成 → report.md")

if __name__ == "__main__":
    main()
