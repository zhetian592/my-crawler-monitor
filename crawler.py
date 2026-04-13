#!/usr/bin/env python3
# crawler.py
import os
import json
import feedparser
from datetime import datetime
from typing import List, Dict
from bs4 import BeautifulSoup
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys

# ========== 配置信源 ==========
# 注意：这里必须填入 RSS 地址（RSSHub 或 Nitter 生成的链接），不能是普通网页。
# 例如：
#   "https://rsshub.app/voachinese/china"
#   "https://nitter.net/whyyoutouzhele/rss"
TIER_SOURCES = {
    "1": [
        # 请替换为你实际可用的 RSS 地址
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/bbc/zhongwen/simp",
        "https://rsshub.app/zaobao/realtime/china",
        "https://nitter.net/whyyoutouzhele/rss",
    ],
    "2": [],
    "3": []
}

# ========== 涉华关键词 ==========
CHINA_KEYWORDS = [
    "中国", "中共", "北京", "习近平", "台湾", "香港", "新疆", "西藏",
    "南海", "中美", "华为", "字节跳动", "TikTok", "一带一路", "武统"
]

# ========== 初始化 AI 客户端（智谱AI） ==========
ZHIPUAI_API_KEY = os.environ.get("ZHIPUAI_API_KEY")
ai_client = None

if ZHIPUAI_API_KEY:
    try:
        from zhipuai import ZhipuAI
        ai_client = ZhipuAI(api_key=ZHIPUAI_API_KEY)
        print("智谱AI 客户端初始化成功")
    except ImportError:
        print("警告: 未安装 zhipuai 库，AI 分析功能不可用。请运行: pip install zhipuai")
    except Exception as e:
        print(f"警告: AI 客户端初始化失败: {e}")
else:
    print("提示: 未设置 ZHIPUAI_API_KEY 环境变量，AI 分析功能将跳过")

# ========== 辅助函数 ==========
def is_china_related(text: str) -> bool:
    """关键词匹配判断是否涉华"""
    text_lower = text.lower()
    for kw in CHINA_KEYWORDS:
        if kw.lower() in text_lower:
            return True
    return False

def clean_html(html_text: str) -> str:
    """清洗 HTML 标签"""
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text().replace("\n", " ").strip()

def generate_risk_point(title: str, summary: str) -> str:
    """基于规则的兜底风险点（当 AI 不可用时使用）"""
    if "台湾" in title or "台湾" in summary:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in title:
        return "涉及新疆议题，需防范西方舆论炒作"
    if "华为" in title and "制裁" in summary:
        return "科技供应链风险，可能影响相关企业"
    if "南海" in title:
        return "地缘政治敏感，可能引发区域紧张"
    return "可能引起网络舆论关注，建议进一步核实"

def analyze_with_ai(title: str, summary: str) -> Dict:
    """
    使用智谱AI GLM-4-Flash 分析内容
    返回 {"summary": "分析总结", "risk_point": "风险点"}
    """
    default = {
        "summary": "AI分析未启用",
        "risk_point": generate_risk_point(title, summary)
    }
    if not ai_client:
        return default

    prompt = f"""你是一名专业的网络安全和舆情分析师。请分析以下内容，并输出JSON格式结果。

标题：{title}
摘要：{summary[:500]}

要求：
1. "analysis_summary": 一句话概括本条内容的核心观点，不超过50字。
2. "risk_point": 指出潜在风险点，不超过30字。

输出格式示例：
{{"analysis_summary": "xxx", "risk_point": "xxx"}}
"""
    try:
        response = ai_client.chat.completions.create(
            model="glm-4-flash",  # 免费模型
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        result = json.loads(response.choices[0].message.content)
        return {
            "summary": result.get("analysis_summary", "")[:50],
            "risk_point": result.get("risk_point", "")[:30]
        }
    except Exception as e:
        print(f"AI 分析失败: {e}")
        return default

def fetch_rss_items(url: str) -> List[Dict]:
    """抓取单个 RSS 源，返回条目列表"""
    try:
        feed = feedparser.parse(url)
        if feed.bozo:  # 解析异常
            print(f"警告: RSS 解析可能有问题 - {url}: {feed.bozo_exception}")
        items = []
        for entry in feed.entries[:20]:
            # 提取标题和摘要
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = clean_html(entry.get("content", [{}])[0].get("value", ""))
            if not summary:
                summary = title  # 降级

            item = {
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary[:500],
                "published": entry.get("published", entry.get("updated", "")),
                "source": url,
                "fetched_at": datetime.utcnow().isoformat()
            }
            items.append(item)
        return items
    except Exception as e:
        print(f"抓取失败 {url}: {e}")
        return []

def update_report_md(all_items: List[Dict], tier: str):
    """生成 report.md，包含涉华内容表格"""
    china_items = [item for item in all_items if item.get("china_related", False)]
    if not china_items:
        content = f"# 舆情报告 (Tier {tier})\n\n生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n过去24小时无涉华内容。\n"
    else:
        lines = [
            f"# 舆情报告 (Tier {tier})",
            f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC",
            "",
            "| 事件简述 | 原文链接 | 潜在风险点 |",
            "|---------|----------|------------|"
        ]
        for item in china_items:
            summary = item.get("analysis_summary") or item["summary"][:100]
            link = item["link"]
            risk = item.get("risk_point", "")
            if not risk:
                risk = generate_risk_point(item["title"], item["summary"])
            lines.append(f"| {summary} | [链接]({link}) | {risk} |")
        content = "\n".join(lines)
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(content)
    print(f"已生成 report.md，包含 {len(china_items)} 条涉华内容")

def main():
    tier = os.getenv("TIER", "2")
    sources = TIER_SOURCES.get(tier, [])
    if not sources:
        print(f"警告: Tier {tier} 没有配置任何信源，请编辑 TIER_SOURCES")
        sys.exit(0)

    print(f"开始抓取 Tier {tier}，共 {len(sources)} 个信源")
    all_items = []

    # 串行抓取（避免并发请求被封）
    for url in sources:
        print(f"抓取: {url}")
        items = fetch_rss_items(url)
        for item in items:
            full_text = item["title"] + " " + item["summary"]
            item["china_related"] = is_china_related(full_text)
            if item["china_related"]:
                # 调用 AI 分析
                ai_result = analyze_with_ai(item["title"], item["summary"])
                item["analysis_summary"] = ai_result["summary"]
                item["risk_point"] = ai_result["risk_point"]
            else:
                item["analysis_summary"] = ""
                item["risk_point"] = ""
            all_items.append(item)
        print(f"  获取到 {len(items)} 条，其中涉华 {sum(1 for i in items if i.get('china_related'))} 条")

    # 保存原始数据到 data/
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    data_file = f"data/tier{tier}_{timestamp}.json"
    with open(data_file, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    print(f"原始数据已保存到 {data_file}")

    # 生成报告
    update_report_md(all_items, tier)

if __name__ == "__main__":
    main()
