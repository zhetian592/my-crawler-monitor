#!/usr/bin/env python3
# crawler.py - 高速版（禁用AI，并发抓取）
import os
import json
import feedparser
from datetime import datetime
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ========== 信源配置（已全部转换为可用的RSS地址） ==========
TIER_SOURCES = {
    "1": [
        # 新闻网站
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/voachinese/6197",
        "https://rsshub.app/bbc/zhongwen/simp",
        "https://rsshub.app/rfa/mandarin",
        "https://rsshub.app/dw/rss/zh/s-9058",
        "https://rsshub.app/rfi/cn",
        "https://rsshub.app/nytimes/zh",
        "https://rsshub.app/zaobao/realtime/china",
        # X 用户（使用 Nitter RSS）
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
    """基于规则的快速风险点生成（无AI）"""
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
    """抓取单个RSS源，返回条目列表"""
    try:
        feed = feedparser.parse(url)
        if feed.bozo:
            print(f"  警告: {url} 解析异常")
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

def update_report_md(all_items, tier):
    """生成报告，只包含涉华内容"""
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
            # 事件简述：优先取标题，没有则取摘要前100字
            summary = item["title"] if item["title"] else item["summary"][:100]
            link = item["link"]
            risk = item.get("risk_point", "")
            lines.append(f"| {summary} | [链接]({link}) | {risk} |")
        content = "\n".join(lines)
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(content)
    print(f"报告已生成，涉华内容 {len(china_items)} 条")

def main():
    tier = os.getenv("TIER", "2")
    sources = TIER_SOURCES.get(tier, [])
    if not sources:
        print(f"警告: Tier {tier} 没有配置信源")
        return

    print(f"开始并发抓取 Tier {tier}，共 {len(sources)} 个信源")
    start_time = time.time()
    all_items = []
    
    # 并发抓取（10个线程）
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

    print(f"抓取完成，共获取 {len(all_items)} 条原始内容，耗时 {time.time()-start_time:.1f} 秒")

    # 涉华判断与风险点生成（无AI）
    for item in all_items:
        full_text = item["title"] + " " + item["summary"]
        item["china_related"] = is_china_related(full_text)
        if item["china_related"]:
            item["risk_point"] = generate_risk_point(item["title"], item["summary"])
        else:
            item["risk_point"] = ""

    # 保存原始数据
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
