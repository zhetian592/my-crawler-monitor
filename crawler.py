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
        # VOA 中文网（RSS）
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/voachinese/6197",
        # BBC 中文网
        "https://rsshub.app/bbc/zhongwen/simp",
        # RFA
        "https://rsshub.app/rfa/mandarin",
        # DW 在线报导
        "https://rsshub.app/dw/zh/在线报导/s-9058",
        # RFI
        "https://rsshub.app/rfi/cn",
        # 纽约时报中文网
        "https://rsshub.app/nytimes/zh",
        # 联合早报 中国实时
        "https://rsshub.app/zaobao/realtime/china",
        # X 用户（一级）
        "https://rsshub.app/twitter/user/whyyoutouzhele",
        "https://rsshub.app/twitter/user/Chai20230817",
        "https://rsshub.app/twitter/user/ChingteLai",
        "https://rsshub.app/twitter/user/newszg_official",
        "https://rsshub.app/twitter/user/YesterdayBigcat",
        "https://rsshub.app/twitter/user/realcaixia",
        "https://rsshub.app/twitter/user/wangzhian8848",
        "https://rsshub.app/twitter/user/june4thmuseum",
        "https://rsshub.app/twitter/user/wangdan1989",
        "https://rsshub.app/twitter/user/hrw_chinese",
        "https://rsshub.app/twitter/user/wuerkaixi",
        "https://rsshub.app/twitter/user/torontobigface",
    ],
    "2": [
        # 网站
        "https://rsshub.app/stnn",
        "https://rsshub.app/6park",
        "https://rsshub.app/boxun",
        "https://rsshub.app/reddit/r/mohu",
        "https://rsshub.app/sintaiwan",
        "https://rsshub.app/chinesedigitaltimes",
        "https://rsshub.app/ntdtv/b5",
        "https://rsshub.app/secretchina",
        "https://rsshub.app/creaders/blog",
        "https://rsshub.app/epochtimes",
        "https://rsshub.app/pincong",
        "https://rsshub.app/lexiangge",
        "https://rsshub.app/fanzei",
        "https://rsshub.app/hanfeng1918",
        "https://rsshub.app/iwantrun",
        "https://rsshub.app/xizang-zhiye",
        "https://rsshub.app/uyghurcongress/cn",
        # X 用户（二级）
        "https://rsshub.app/twitter/user/dayangelcp",
        "https://rsshub.app/twitter/user/XiJPDynasty",
        "https://rsshub.app/twitter/user/chinatransition",
        "https://rsshub.app/twitter/user/chonglangzhiyin",
        "https://rsshub.app/twitter/user/pear14525902",
        "https://rsshub.app/twitter/user/xingzhe2021",
        "https://rsshub.app/twitter/user/RedPigCartoon",
        "https://rsshub.app/twitter/user/jhf8964",
        "https://rsshub.app/twitter/user/Cian_Ci",
        "https://rsshub.app/twitter/user/fangshimin",
        "https://rsshub.app/twitter/user/remonwangxt",
        "https://rsshub.app/twitter/user/badiucao",
        "https://rsshub.app/twitter/user/xinwendiaocha",
        "https://rsshub.app/twitter/user/WOMEN4China",
        "https://rsshub.app/twitter/user/Ruters0615",
        "https://rsshub.app/twitter/user/CitizensDailyCN",
        "https://rsshub.app/twitter/user/ZhouFengSuo",
        "https://rsshub.app/twitter/user/hchina89",
        "https://rsshub.app/twitter/user/gaoyu200812",
        "https://rsshub.app/twitter/user/amnestychinese",
        "https://rsshub.app/twitter/user/lidangzzz",
        "https://rsshub.app/twitter/user/liangziyueqian1",
        "https://rsshub.app/twitter/user/YongyuanCui1",
        "https://rsshub.app/twitter/user/jielijian",
        "https://rsshub.app/twitter/user/xiaojingcanxue",
        "https://rsshub.app/twitter/user/CHENWEIMING2017",
        "https://rsshub.app/twitter/user/xiangjunweiwu",
        "https://rsshub.app/twitter/user/BoKuangyi",
        "https://rsshub.app/twitter/user/tibetdotcom",
        "https://rsshub.app/twitter/user/chinesepen_org",
        "https://rsshub.app/twitter/user/UHRP_Chinese",
        "https://rsshub.app/twitter/user/wurenhua",
    ],
    "3": [
        # 网站
        "https://rsshub.app/mingpao",
        "https://rsshub.app/theinitium",
        "https://rsshub.app/soundofhope",
        "https://rsshub.app/chinademocrats",
        "https://rsshub.app/hk01",
        "https://rsshub.app/aboluowang",
        "https://rsshub.app/bannedbook",
        # 注意：某些 blogspot 和自定义域名可能无法直接转 RSS，需要手动寻找 RSS 或放弃
        # X 用户（三级）
        "https://rsshub.app/twitter/user/zijuan_chen",
        "https://rsshub.app/twitter/user/weiquanwang",
        "https://rsshub.app/twitter/user/hnczyhhwck",
        "https://rsshub.app/twitter/user/laodeng89",
        # 其余你提供的三级网站（部分无法直接 RSSHub 支持，可尝试通用路由）
        "https://rsshub.app/2newcenturynet",
        "https://rsshub.app/lingbaxianzhang",
        "https://rsshub.app/dongtaiwang",
        "https://rsshub.app/minzhuzhongguo",
        "https://rsshub.app/chinainperspective",
        "https://rsshub.app/msguancha",
        "https://rsshub.app/bjs",
        "https://rsshub.app/2047",
        "https://rsshub.app/jinpianwang",
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
