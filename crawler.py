import os
import json
import requests
import feedparser
from datetime import datetime
from typing import List, Dict

# ========== 配置：根据 TIER 定义不同的信源 ==========
# 请替换成你实际要监控的 RSS 地址或 API
TIER_SOURCES = {
    "1": [
        "https://rsshub.app/twitter/user/elonmusk",
        "https://rsshub.app/weibo/user/2803301701",   # 人民日报
        # 添加你的一级信源...
    ],
    "2": [
        "https://rsshub.app/zhihu/people/activities/xxx",
        # 添加你的二级信源...
    ],
    "3": [
        "https://rsshub.app/36kr/newsflashes",
        # 添加你的三级信源...
    ]
}

# 涉华关键词（可根据需要修改）
CHINA_KEYWORDS = [
    "中国", "中共", "北京", "习近平", "台湾", "香港", "新疆", "西藏",
    "南海", "中美", "华为", "字节跳动", "TikTok", "一带一路", "武统"
]

def is_china_related(text: str) -> bool:
    """判断文本是否涉及中国（关键词匹配）"""
    text_lower = text.lower()
    for kw in CHINA_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False

def generate_risk_point(title: str, summary: str) -> str:
    """生成潜在风险点，每条不超过30字"""
    # 你可以扩展更多规则，或者后续接入免费AI
    if "台湾" in title or "台湾" in summary:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in title:
        return "涉及新疆议题，需防范西方舆论炒作"
    if "华为" in title and "制裁" in summary:
        return "科技供应链风险，可能影响相关企业"
    if "南海" in title:
        return "地缘政治敏感，可能引发区域紧张"
    return "可能引起网络舆论关注"

def fetch_rss_items(url: str) -> List[Dict]:
    """抓取RSS源，返回条目列表"""
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:20]:  # 每个源最多20条
            item = {
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", ""),
                "source": url,
                "fetched_at": datetime.utcnow().isoformat()
            }
            items.append(item)
        return items
    except Exception as e:
        print(f"Error fetching {url}: {e}")
        return []

def update_report_md(all_items: List[Dict], tier: str):
    """生成 report.md，包含事件简述、原文链接、潜在风险点"""
    # 过滤涉华内容
    china_items = [item for item in all_items if item.get("china_related", False)]
    if not china_items:
        content = f"# 舆情报告 (Tier {tier})\n\n过去24小时无涉华内容。\n"
    else:
        lines = [f"# 舆情报告 (Tier {tier})", f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC", ""]
        lines.append("| 事件简述 | 原文链接 | 潜在风险点 |")
        lines.append("|---------|----------|------------|")
        for item in china_items:
            summary = item["summary"][:100].replace("\n", " ")  # 截取前100字符
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
    for url in sources:
        items = fetch_rss_items(url)
        for item in items:
            full_text = item["title"] + " " + item["summary"]
            item["china_related"] = is_china_related(full_text)
            if item["china_related"]:
                item["risk_point"] = generate_risk_point(item["title"], item["summary"])
            else:
                item["risk_point"] = ""
            all_items.append(item)
    # 保存原始数据到 data/ 目录
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    data_file = f"data/tier{tier}_{timestamp}.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    print(f"Saved {len(all_items)} items to {data_file}")
    # 更新 report.md
    update_report_md(all_items, tier)

if __name__ == "__main__":
    main()
