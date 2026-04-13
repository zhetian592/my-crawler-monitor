import os
import json
import feedparser
from datetime import datetime
from typing import List, Dict
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========== 配置：根据 TIER 定义不同的信源 ==========
TIER_SOURCES = {
    "1": [
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/voachinese/6197",
        "https://rsshub.app/bbc/zhongwen/simp",
        "https://rsshub.app/rfa/mandarin",
    ],
    "2": [
        "https://rsshub.app/stnn",
        "https://rsshub.app/6park",
    ],
    "3": [
        "https://rsshub.app/mingpao",
        "https://rsshub.app/theinitium",
    ]
}

CHINA_KEYWORDS = [
    "中国", "中共", "北京", "习近平", "台湾", "香港", "新疆", "西藏",
    "南海", "中美", "华为", "字节跳动", "TikTok", "一带一路", "武统"
]

def is_china_related(text: str) -> bool:
    text_lower = text.lower()
    for kw in CHINA_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False

def generate_risk_point(title: str, summary: str) -> str:
    if "台湾" in title or "台湾" in summary:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in title:
        return "涉及新疆议题，需防范西方舆论炒作"
    if "华为" in title and "制裁" in summary:
        return "科技供应链风险，可能影响相关企业"
    if "南海" in title:
        return "地缘政治敏感，可能引发区域紧张"
    return "可能引起网络舆论关注"

def clean_text(html_text: str) -> str:
    """去掉 HTML 标签，并替换 Markdown 表格敏感字符"""
    text = BeautifulSoup(html_text, "html.parser").get_text()
    text = text.replace("\n", " ").replace("|", "/").strip()
    return text

def fetch_rss_items(url: str) -> List[Dict]:
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:20]:
            summary_text = clean_text(entry.get("summary", ""))
            item = {
                "title": clean_text(entry.get("title", "")),
                "link": entry.get("link", ""),
                "summary": summary_text,
                "published": entry.get("published", entry.get("updated", "")),
                "source": url,
                "fetched_at": datetime.utcnow().isoformat()
            }
            items.append(item)
        print(f"[OK] Fetched {len(items)} items from {url}")
        return items
    except Exception as e:
        print(f"[ERROR] Fetching {url}: {e}")
        return []

def update_report_md(all_items: List[Dict], tier: str):
    china_items = [item for item in all_items if item.get("china_related", False)]
    if not china_items:
        content = f"# 舆情报告 (Tier {tier})\n\n过去24小时无涉华内容。\n"
    else:
        lines = [f"# 舆情报告 (Tier {tier})",
                 f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
                 "",
                 "| 事件简述 | 原文链接 | 潜在风险点 |",
                 "|---------|----------|------------|"]
        for item in china_items:
            summary = item["summary"][:100]
            link = item["link"]
            risk = item.get("risk_point", "无")
            lines.append(f"| {summary} | [链接]({link}) | {risk} |")
        content = "\n".join(lines)
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(content)
    print(f"Updated report.md with {len(china_items)} China-related items")

def main():
    tier = os.getenv("TIER", "2")
    sources = TIER_SOURCES.get(tier, [])
    print(f"Running crawler for Tier {tier}, sources: {sources}")

    all_items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_rss_items, url): url for url in sources}
        for future in as_completed(future_to_url):
            items = future.result()
            for item in items:
                full_text = item["title"] + " " + item["summary"]
                item["china_related"] = is_china_related(full_text)
                if item["china_related"]:
                    item["risk_point"] = generate_risk_point(item["title"], item["summary"])
                else:
                    item["risk_point"] = ""
                all_items.append(item)

    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    data_file = f"data/tier{tier}_{timestamp}.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(all_items)} items to {data_file}")

    update_report_md(all_items, tier)

if __name__ == "__main__":
    main()
