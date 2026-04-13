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
        # 一级网站
        "https://www.voachinese.com/China",
        "https://www.voachinese.com/p/6197.html",
        "https://www.bbc.com/zhongwen/simp",
        "https://www.rfa.org/mandarin",
        "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
        "https://www.rfi.fr/cn/",
        "https://cn.nytimes.com/",
        "https://www.zaobao.com/realtime/china",
        # 一级社交媒体
        "https://x.com/whyyoutouzhele",
        "https://x.com/Chai20230817",
        "https://x.com/ChingteLai",
        "https://x.com/newszg_official",
        "https://x.com/YesterdayBigcat",
        "https://x.com/realcaixia",
        "https://x.com/wangzhian8848",
        "https://x.com/june4thmuseum",
        "https://x.com/wangdan1989",
        "https://x.com/hrw_chinese",
        "https://x.com/wuerkaixi",
        "https://x.com/torontobigface",
    ],
    "2": [
        # 二级网站
        "http://www.stnn.cc/",
        "https://www.6park.com/us.shtml",
        "https://boxun.com/",
        "https://www.reddit.com/r/mohu/",
        "http://www.sintaiwan.url.tw/",
        "https://chinadigitaltimes.net/chinese/",
        "https://www.ntdtv.com/b5/",
        "https://www.secretchina.com/",
        "https://blog.creaders.net/",
        "https://www.epochtimes.com/",
        "https://pincong.rocks/",
        "http://www.lexiangge.com/",
        "https://www.fanzei.net/",
        "http://hanfeng1918.com/",
        "https://iwantrun.com/",
        "https://xizang-zhiye.org/",
        "https://cn.uyghurcongress.org/",
        # 二级社交媒体
        "https://x.com/dayangelcp",
        "https://x.com/XiJPDynasty",
        "https://x.com/chinatransition",
        "https://x.com/chonglangzhiyin",
        "https://x.com/pear14525902",
        "https://x.com/xingzhe2021",
        "https://x.com/RedPigCartoon",
        "https://x.com/jhf8964",
        "https://x.com/Cian_Ci",
        "https://x.com/fangshimin",
        "https://x.com/remonwangxt",
        "https://x.com/badiucao",
        "https://x.com/xinwendiaocha",
        "https://x.com/WOMEN4China",
        "https://x.com/Ruters0615",
        "https://x.com/CitizensDailyCN",
        "https://x.com/ZhouFengSuo",
        "https://x.com/hchina89",
        "https://x.com/gaoyu200812",
        "https://x.com/amnestychinese",
        "https://x.com/lidangzzz",
        "https://x.com/liangziyueqian1",
        "https://x.com/YongyuanCui1",
        "https://x.com/jielijian",
        "https://x.com/xiaojingcanxue",
        "https://x.com/CHENWEIMING2017",
        "https://x.com/xiangjunweiwu",
        "https://x.com/BoKuangyi",
        "https://x.com/tibetdotcom",
        "https://x.com/chinesepen_org",
        "https://x.com/UHRP_Chinese",
        "https://x.com/wurenhua",
    ],
    "3": [
        # 三级网站
        "https://www.mingpao.com/",
        "https://theinitium.com/",
        "https://www.soundofhope.org/",
        "https://chinademocrats.org/",
        "http://wqw2010.blogspot.com/",
        "https://www.hk01.com/",
        "https://2newcenturynet.blogspot.com/",
        "https://lingbaxianzhang.blogspot.com/",
        "http://dongtaiwang.com/loc/phome.php?v=0",
        "http://minzhuzhongguo.org/",
        "http://www.chinainperspective.com/",
        "https://msguancha.com/",
        "http://bjs.org/",
        "https://2047.one/",
        "https://jinpianwang.com/",
        "https://www.aboluowang.com/index.html",
        "https://www.bannedbook.org/",
        # 三级社交媒体
        "https://x.com/zijuan_chen",
        "https://x.com/weiquanwang",
        "https://x.com/hnczyhhwck",
        "https://x.com/laodeng89",
        "https://x.com/taocomic",
        "https://x.com/SpeechFreedomCN",
        "https://x.com/uzhuan2/following",
        "https://x.com/GFWfrog",
        "https://x.com/aboluowang",
        "https://x.com/zhbl01",
        "https://x.com/Rumoreconomy",
        "https://x.com/xjpw1cnm",
        "https://x.com/baizhiyundong",
        "https://x.com/wfeidegenggaoj",
        "https://x.com/wuyuesanren",
        "https://x.com/uzhuan2/following",
        "https://x.com/iguangcheng",
        "https://x.com/Foreign_Force",
        "https://x.com/8964Remember",
        "https://x.com/64anonymous799",
        "https://x.com/GanchengW",
        "https://x.com/xiangjunweiwu",
        "https://x.com/dashengmedia",
        "https://x.com/FH_China",
        "https://x.com/huirights",
        "https://x.com/74rXysi",
        "https://x.com/CHRDnet",
        "https://x.com/RightsLawyersCN",
        "https://x.com/tiffany21047370",
        "https://x.com/LiutaoTang",
    ]
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
