#!/usr/bin/env python3
# crawler.py
import os
import json
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup
from openai import OpenAI

# ========== 配置信源（已按你提供的列表填写，但需要替换为真正的RSS地址） ==========
TIER_SOURCES = {
    "1": [
        # VOA 中文网
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/voachinese/6197",
        # BBC 中文
        "https://rsshub.app/bbc/zhongwen/simp",
        # RFA
        "https://rsshub.app/rfa/mandarin",
        # DW
        "https://rsshub.app/dw/rss/zh/s-9058",
        # RFI
        "https://rsshub.app/rfi/cn",
        # 纽约时报中文网
        "https://rsshub.app/nytimes/zh",
        # 联合早报 中国实时
        "https://rsshub.app/zaobao/realtime/china",
        # X 用户（全部改用 Nitter，更稳定）
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
    "2": [],   # 空，所有信源已放入一级
    "3": []
}

# ========== 涉华关键词 ==========
CHINA_KEYWORDS = [
    "中国", "中共", "北京", "习近平", "台湾", "香港", "新疆", "西藏",
    "南海", "中美", "华为", "字节跳动", "TikTok", "一带一路", "武统"
]

def is_china_related(text):
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in CHINA_KEYWORDS)

def clean_html(html_text):
    if not html_text:
        return ""
    soup = BeautifulSoup(html_text, "html.parser")
    return soup.get_text().replace("\n", " ").strip()

def generate_risk_point(title, summary):
    if "台湾" in title or "台湾" in summary:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in title:
        return "涉及新疆议题，需防范西方舆论炒作"
    if "南海" in title:
        return "地缘政治敏感，可能引发区域紧张"
    return "可能引起网络舆论关注"

# ========== OpenRouter AI 分析 ==========
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")

def analyze_with_ai(title, summary):
    if not OPENROUTER_API_KEY:
        return {"analysis_summary": "AI未配置", "risk_point": generate_risk_point(title, summary)}
    
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
        return {
            "analysis_summary": result.get("analysis_summary", "")[:50],
            "risk_point": result.get("risk_point", "")[:30]
        }
    except Exception as e:
        print(f"AI分析失败: {e}")
        return {"analysis_summary": "分析失败", "risk_point": generate_risk_point(title, summary)}

# ========== 抓取 RSS ==========
def fetch_rss_items(url):
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:20]:
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = clean_html(entry.get("content", [{}])[0].get("value", ""))
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
        print(f"抓取失败 {url}: {e}")
        return []

# ========== 生成报告 ==========
def update_report_md(all_items, tier):
    china_items = [i for i in all_items if i.get("china_related")]
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
            lines.append(f"| {summary} | [链接]({link}) | {risk} |")
        content = "\n".join(lines)
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(content)

# ========== 主函数 ==========
def main():
    tier = os.getenv("TIER", "2")
    sources = TIER_SOURCES.get(tier, [])
    if not sources:
        print(f"警告: Tier {tier} 没有配置信源")
        return
    print(f"开始抓取 Tier {tier}，共 {len(sources)} 个信源")
    all_items = []
    for url in sources:
        print(f"抓取: {url}")
        items = fetch_rss_items(url)
        for item in items:
            full_text = item["title"] + " " + item["summary"]
            item["china_related"] = is_china_related(full_text)
            if item["china_related"]:
                ai_result = analyze_with_ai(item["title"], item["summary"])
                item["analysis_summary"] = ai_result["analysis_summary"]
                item["risk_point"] = ai_result["risk_point"]
            else:
                item["analysis_summary"] = ""
                item["risk_point"] = ""
            all_items.append(item)
        print(f"  获取 {len(items)} 条，涉华 {sum(1 for i in items if i.get('china_related'))} 条")
    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    with open(f"data/tier{tier}_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)
    update_report_md(all_items, tier)

if __name__ == "__main__":
    main()
