import os
import json
from datetime import datetime
import feedparser
import requests
from bs4 import BeautifulSoup

# ================== 信源分级 ==================
ACCOUNTS = {
    "level1": [ "https://www.voachinese.com/China", "https://x.com/whyyoutouzhele" ],
    "level2": [ "http://www.stnn.cc/", "https://x.com/dayangelcp" ],
    "level3": [ "https://www.mingpao.com/", "https://x.com/zijuan_chen" ]
}

# ================== 中国相关关键词 ==================
KEYWORDS = [
    "中国", "习近平", "人权", "六四", "维吾尔", "西藏", "台湾", "民主",
    "独裁", "审查", "反共", "中共", "迫害", "天安门"
]

# ================== 风险点规则 ==================
def generate_risk_point(title, summary):
    if "台湾" in title or "台湾" in summary:
        return "可能违反一个中国原则，引发外交争议"
    if "新疆" in title or "维吾尔" in title:
        return "涉及新疆议题，需防范西方舆论炒作"
    if "人权" in title or "六四" in title:
        return "敏感历史事件，可能引发舆情关注"
    if "华为" in title and "制裁" in summary:
        return "科技供应链风险，可能影响企业"
    return "可能引起网络舆论关注"

# ================== 文本清理 ==================
def clean_text(html):
    return BeautifulSoup(html, "html.parser").get_text().replace("\n", " ").replace("|","/").strip()

# ================== 抓取 RSS 或网页标题 ==================
def fetch_items(url):
    items = []
    try:
        feed = feedparser.parse(url)
        if feed.entries:
            for entry in feed.entries[:5]:
                title = clean_text(entry.get("title",""))
                summary = clean_text(entry.get("summary",""))
                items.append({
                    "title": title,
                    "summary": summary,
                    "link": entry.get("link",""),
                    "time": entry.get("published", entry.get("updated","")),
                    "source": url,
                    "risk": generate_risk_point(title, summary) if any(k in title+summary for k in KEYWORDS) else ""
                })
        else:
            # 尝试抓取网页 <title>
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                soup = BeautifulSoup(resp.text, "html.parser")
                title = soup.title.string.strip() if soup.title else url
                items.append({
                    "title": title,
                    "summary": "",
                    "link": url,
                    "time": "",
                    "source": url,
                    "risk": generate_risk_point(title, "") if any(k in title for k in KEYWORDS) else ""
                })
    except Exception as e:
        print(f"抓取失败 {url}: {e}")
    return items

# ================== 生成报告 ==================
def generate_report():
    now = datetime.now()
    all_items = []

    for level, urls in ACCOUNTS.items():
        for url in urls:
            items = fetch_items(url)
            for i in items:
                i["level"] = level
                all_items.append(i)

    # 保存 JSON 数据
    os.makedirs("data", exist_ok=True)
    json_file = f"data/report_{now.strftime('%Y%m%d_%H%M%S')}.json"
    with open(json_file,"w",encoding="utf-8") as f:
        json.dump(all_items,f,ensure_ascii=False,indent=2)

    # 生成 Markdown 报告
    md_file = "report.md"
    with open(md_file,"w",encoding="utf-8") as f:
        f.write(f"# 内容安全舆情报告\n更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for level in ["level1","level2","level3"]:
            f.write(f"## {level.upper()} 信源\n\n")
            level_items = [i for i in all_items if i["level"]==level]
            if not level_items:
                f.write("暂无相关内容。\n\n")
                continue
            f.write("| 标题 | 摘要 | 链接 | 风险点 |\n")
            f.write("|------|------|------|------|\n")
            for i in level_items:
                summary = (i["summary"][:100]+"...") if i["summary"] else ""
                f.write(f"| {i['title']} | {summary} | [链接]({i['link']}) | {i['risk']} |\n")
            f.write("\n")

    print(f"✅ 报告生成完成，共 {len(all_items)} 条数据，JSON 已保存到 {json_file}")

if __name__=="__main__":
    generate_report()
