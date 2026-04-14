#!/usr/bin/env python3
# crawler.py - 优化版：清晰表格报告 + 分级支持
import os
import json
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ================= 配置 =================
ENABLE_AI = os.environ.get("ENABLE_AI", "").lower() == "true"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

TIER_SOURCES = {
    "1": [  # 一级：每小时
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/bbc/zhongwen/simp",
        "https://rsshub.app/rfa/mandarin",
        "https://rsshub.app/dw/rss/zh/s-9058",
        "https://rsshub.app/rfi/cn",
        "https://rsshub.app/nytimes/zh",
        "https://rsshub.app/zaobao/realtime/china",
        # X 大 V (Nitter)
        "https://nitter.net/whyyoutouzhele/rss",
        "https://nitter.net/Chai20230817/rss",
        "https://nitter.net/realcaixia/rss",
        "https://nitter.net/wangzhian8848/rss",
        "https://nitter.net/wangdan1989/rss",
    ],
    "2": [  # 二级：每3小时
        "https://rsshub.app/chinadigitaltimes/chinese",
        "https://rsshub.app/epochtimes/gb",
        "https://rsshub.app/pincong/rocks",
        "https://nitter.net/dayangelcp/rss",
        "https://nitter.net/RedPigCartoon/rss",
        "https://nitter.net/fangshimin/rss",
    ],
    "3": [  # 三级：每6小时
        "https://rsshub.app/theinitium",
        "https://rsshub.app/mingpao",
        "https://rsshub.app/soundofhope",
        "https://nitter.net/laodeng89/rss",
        "https://nitter.net/iguangcheng/rss",
    ]
}

CHINA_KEYWORDS = ["中国", "中共", "习近平", "台湾", "香港", "新疆", "西藏", "南海", "华为", "六四", "人权", "民主", "独裁", "审查"]

def clean_html(html_text):
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text().replace("\n", " ").strip()[:500]

def is_china_related(text):
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in CHINA_KEYWORDS)

def generate_risk_point(title, summary):
    t = (title + " " + summary).lower()
    if "台湾" in t:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in t or "西藏" in t:
        return "涉及敏感地区议题，需防范舆论炒作"
    if "六四" in t or "人权" in t:
        return "历史/人权议题，易引发网络舆情"
    if "华为" in t:
        return "科技供应链风险"
    return "可能引起网络舆论关注"

def fetch_rss_items(url):
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:15]:
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = title
            items.append({
                "title": title,
                "link": entry.get("link", url),
                "summary": summary,
                "source": url
            })
        return items
    except Exception:
        return []

def generate_report(china_items, tier):
    now = datetime.utcnow()
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(f"# 内容安全行业舆情报告 (Tier {tier})\n")
        f.write(f"生成时间：{now.strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n")
        
        if not china_items:
            f.write("过去24小时无明显涉华内容。\n")
            return

        f.write("| 事件简述 | 原文链接 | 潜在风险点 |\n")
        f.write("|----------|----------|------------|\n")
        
        for item in china_items:
            summary = item.get("analysis_summary") or item["title"][:120]
            link = item["link"]
            risk = item.get("risk_point", generate_risk_point(item["title"], item["summary"]))
            f.write(f"| {summary} | [链接]({link}) | {risk} |\n")

if __name__ == "__main__":
    tier = os.getenv("TIER", "1")
    sources = TIER_SOURCES.get(tier, [])
    
    print(f"开始抓取 Tier {tier} 信源...")
    all_items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(fetch_rss_items, url) for url in sources]
        for future in futures:
            all_items.extend(future.result())

    # 过滤涉华
    china_items = [item for item in all_items if is_china_related(item["title"] + " " + item["summary"])]

    # 生成报告
    generate_report(china_items, tier)
    print(f"Tier {tier} 报告生成完成，共 {len(china_items)} 条涉华内容")
