#!/usr/bin/env python3
# crawler.py - 纯本地增强版（无外部 API，生成清晰 HTML 表格）
import os
import json
import feedparser
import time
import requests
import re
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed

# ================= 配置 =================
RSSHUB_INSTANCES = ["https://rsshub.app", "https://rsshub.feeded.xyz"]
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.poast.org", "https://nitter.linuxboot.org"]

RAW_SOURCES = [
    "https://www.voachinese.com/China",
    "https://www.voachinese.com/p/6197.html",
    "https://www.bbc.com/zhongwen/simp",
    "https://www.rfa.org/mandarin",
    "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
    "https://www.rfi.fr/cn/",
    "https://cn.nytimes.com/",
    "https://www.zaobao.com/realtime/china",
    "https://x.com/whyyoutouzhele",
    "https://x.com/Chai20230817",
    "https://x.com/realcaixia",
    "https://x.com/wangzhian8848",
    "https://x.com/wangdan1989",
    "https://x.com/wuerkaixi",
    "https://x.com/newszg_official",
    "https://x.com/june4thmuseum",
    "https://x.com/hrw_chinese",
    "https://x.com/torontobigface",
    "https://x.com/dayangelcp",
    "https://x.com/chinatransition",
    "https://x.com/pear14525902",
    "https://x.com/RedPigCartoon",
    "https://x.com/Cian_Ci",
    "https://x.com/remonwangxt",
    "https://x.com/xinwendiaocha",
    "https://x.com/Ruters0615",
    "https://x.com/ZhouFengSuo",
    "https://x.com/gaoyu200812",
    "https://x.com/lidangzzz",
    "https://x.com/YongyuanCui1",
    "https://x.com/xiaojingcanxue",
    "https://x.com/xiangjunweiwu",
    "https://x.com/tibetdotcom",
    "https://x.com/UHRP_Chinese",
    "https://x.com/XiJPDynasty",
    "https://x.com/chonglangzhiyin",
    "https://x.com/xingzhe2021",
    "https://x.com/jhf8964",
    "https://x.com/fangshimin",
    "https://x.com/badiucao",
    "https://x.com/WOMEN4China",
    "https://x.com/CitizensDailyCN",
    "https://x.com/hchina89",
    "https://x.com/amnestychinese",
    "https://x.com/liangziyueqian1",
    "https://x.com/jielijian",
    "https://x.com/CHENWEIMING2017",
    "https://x.com/BoKuangyi",
    "https://x.com/chinesepen_org",
    "https://x.com/wurenhua",
]

def clean_html(text):
    if not text:
        return ""
    soup = BeautifulSoup(text, "html.parser")
    return soup.get_text().strip()[:500]

def parse_published(published_str):
    if not published_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(published_str, fmt)
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
        except:
            continue
    return None

def url_to_rss(url):
    if "voachinese.com/China" in url:
        return f"{RSSHUB_INSTANCES[0]}/voachinese/china"
    if "voachinese.com/p/6197.html" in url:
        return f"{RSSHUB_INSTANCES[0]}/voachinese/6197"
    if "bbc.com/zhongwen/simp" in url:
        return "https://feeds.bbci.co.uk/zhongwen/simp/rss.xml"
    if "rfa.org/mandarin" in url:
        return f"{RSSHUB_INSTANCES[0]}/rfa/mandarin"
    if "dw.com/zh" in url:
        return f"{RSSHUB_INSTANCES[0]}/dw/rss/zh/s-9058"
    if "rfi.fr/cn" in url:
        return f"{RSSHUB_INSTANCES[0]}/rfi/cn"
    if "cn.nytimes.com" in url:
        return f"{RSSHUB_INSTANCES[0]}/nytimes/zh"
    if "zaobao.com/realtime/china" in url:
        return "https://www.zaobao.com/realtime/china/feed"
    if "x.com/" in url:
        username = url.split("/")[-1]
        return f"{NITTER_INSTANCES[0]}/{username}/rss"
    return url

def fetch_single_rss(rss_url, original_url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        resp = requests.get(rss_url, headers=headers, timeout=20)
        if resp.status_code != 200:
            return []
        feed = feedparser.parse(resp.content)
        cutoff = datetime.utcnow() - timedelta(hours=24)
        items = []
        for entry in feed.entries:
            published = entry.get("published", entry.get("updated", ""))
            pub_dt = parse_published(published)
            if pub_dt and pub_dt < cutoff:
                continue
            title = clean_html(entry.get("title", ""))
            summary = clean_html(entry.get("summary", ""))
            if not summary:
                summary = clean_html(entry.get("content", [{}])[0].get("value", ""))
            if not summary:
                summary = title
            items.append({
                "title": title,
                "link": entry.get("link", ""),
                "summary": summary,
                "source": original_url,
                "fetched_at": datetime.utcnow().isoformat()
            })
            if len(items) >= 12:
                break
        return items
    except Exception as e:
        print(f"  抓取异常 {original_url}: {e}")
        return []

def fetch_with_retry(original_url):
    if "x.com/" in original_url:
        username = original_url.split("/")[-1]
        for nitter in NITTER_INSTANCES:
            test_url = f"{nitter}/{username}/rss"
            items = fetch_single_rss(test_url, original_url)
            if items:
                print(f"  ✓ X {username} 使用 {nitter} 成功")
                return items
            else:
                print(f"  ⚠ X {username} 使用 {nitter} 失败")
        return []
    rss_url = url_to_rss(original_url)
    if not rss_url:
        return []
    return fetch_single_rss(rss_url, original_url)

def fetch_all_sources():
    print(f"开始抓取 {len(RAW_SOURCES)} 个信源（过去24小时）...")
    all_items = []
    with ThreadPoolExecutor(max_workers=8) as executor:
        future_to_url = {executor.submit(fetch_with_retry, url): url for url in RAW_SOURCES}
        for future in as_completed(future_to_url):
            url = future_to_url[future]
            try:
                items = future.result()
                all_items.extend(items)
                print(f"✓ {url} -> {len(items)} 条")
            except Exception as e:
                print(f"✗ {url} 异常: {e}")
    # 去重
    seen = set()
    unique = []
    for item in all_items:
        if item["link"] not in seen:
            seen.add(item["link"])
            unique.append(item)
    print(f"去重后共 {len(unique)} 条（原始 {len(all_items)} 条）")
    return unique

def generate_risk_point(title, summary):
    """最大化补全版风险点匹配（已全面覆盖所有关键词）"""
    text = (title + " " + summary).lower()

    # 高风险优先
    if any(kw in text for kw in ["台湾", "台独", "武统", "赖清德", "蔡英文", "两岸关系"]):
        return "违反一个中国原则，可能引发外交争议"
    if any(kw in text for kw in ["新疆", "西藏", "维吾尔", "东突", "藏独", "港独", "南海争议"]):
        return "涉及敏感地区或分裂议题，易被西方舆论炒作"
    if any(kw in text for kw in ["六四", "天安门事件", "白纸运动", "文革", "文化大革命", "反右", "红卫兵", "六四纪念"]):
        return "历史政治运动或敏感事件，舆情风险极高"
    if any(kw in text for kw in ["华为", "中兴", "字节跳动", "TikTok", "芯片", "制裁", "贸易战"]):
        return "科技供应链或国际制裁风险"
    if any(kw in text for kw in ["习近平", "李克强", "王沪宁", "中共中央", "中央军委", "全国人大"]):
        return "涉及最高领导人或核心机构，可能引发政治舆情"

    # 中高风险（你特别强调的）
    if any(kw in text for kw in ["落马", "反腐", "腐败", "贪腐", "党纪处分", "特权阶层", "个人崇拜"]):
        return "涉及官员落马或反腐议题，可能引发社会不满"
    if any(kw in text for kw in ["聚众闹事", "群体事件", "维权", "抗议", "公民抗议", "劳工运动", "环保维权", "烂尾楼", "断供", "房地产暴雷"]):
        return "涉及群体性事件或社会维权，易引发社会稳定风险"

    # 中低风险
    if any(kw in text for kw in ["言论自由", "人权", "异议人士", "异见者", "审查", "网络封锁", "舆论管控", "媒体打压"]):
        return "涉及言论、人权或审查议题，易引发国际关注"
    if any(kw in text for kw in ["海外势力", "民运组织", "NGO", "境外媒体", "虚假新闻", "舆论引导"]):
        return "涉及境外势力或舆论引导，可能引发政治敏感"
    if any(kw in text for kw in ["失业", "青年失业", "房价", "医疗", "教育", "双减", "性别对立", "女权", "宗教迫害"]):
        return "涉及民生或社会不满，可能引发舆情"

    # 默认兜底
    return "可能引起网络舆论关注"

def save_reports(all_articles):
    # 生成 HTML 表格（清晰、可点击）
    html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>内容安全舆情报告</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; margin: 20px; line-height: 1.5; }}
        h1 {{ font-size: 1.8em; border-bottom: 1px solid #eaecef; padding-bottom: 0.3em; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; font-size: 14px; }}
        th, td {{ border: 1px solid #dfe2e5; padding: 8px 12px; text-align: left; vertical-align: top; }}
        th {{ background-color: #f6f8fa; font-weight: 600; }}
        td:nth-child(1) {{ min-width: 200px; max-width: 350px; white-space: normal; word-break: break-word; }}
        td:nth-child(2) {{ min-width: 80px; }}
        td:nth-child(3) {{ min-width: 150px; }}
        a {{ color: #0366d6; text-decoration: none; }}
        a:hover {{ text-decoration: underline; }}
        .footer {{ margin-top: 30px; font-size: 12px; color: #6a737d; border-top: 1px solid #eaecef; padding-top: 10px; }}
    </style>
</head>
<body>
<h1>内容安全行业舆情报告</h1>
<p>生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
<p>抓取信源：VOA、BBC、RFA、DW、RFI、纽约时报、联合早报、X平台</p>
<table>
    <thead>
        <tr><th>事件简述</th><th>原文链接</th><th>潜在风险点</th></tr>
    </thead>
    <tbody>
"""
    for art in all_articles:
        summary = (art.get("title", "") or art.get("summary", ""))[:120].replace("\n", " ").strip()
        link = art.get("link", "#")
        risk = generate_risk_point(art.get("title", ""), art.get("summary", ""))
        html_content += f"""
        <tr>
            <td>{summary}</td>
            <td><a href="{link}" target="_blank">查看原文</a></td>
            <td>{risk}</td>
        </tr>
"""
    html_content += f"""
    </tbody>
</table>
<div class="footer">
    <p>注：本报告基于过去24小时抓取的 {len(all_articles)} 条内容生成，风险点由规则引擎自动判定。</p>
</div>
</body>
</html>"""

    # Markdown 版本
    md_content = "# 内容安全行业舆情报告\n\n"
    md_content += f"生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC\n\n"
    md_content += "| 事件简述 | 原文链接 | 潜在风险点 |\n"
    md_content += "|----------|----------|------------|\n"
    for art in all_articles:
        summary = (art.get("title", "") or art.get("summary", ""))[:100].replace("\n", " ")
        link = art.get("link", "#")
        risk = generate_risk_point(art.get("title", ""), art.get("summary", ""))
        md_content += f"| {summary} | [查看]({link}) | {risk} |\n"

    with open("report.html", "w", encoding="utf-8") as f:
        f.write(html_content)
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(md_content)

    os.makedirs("data", exist_ok=True)
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    with open(f"data/raw_{timestamp}.json", "w", encoding="utf-8") as f:
        json.dump(all_articles, f, ensure_ascii=False, indent=2)

    print("报告已生成: report.html (推荐) 和 report.md")
    print(f"原始数据保存: data/raw_{timestamp}.json")

def main():
    start_time = time.time()
    print("=== 开始抓取信源（过去24小时） ===")
    all_articles = fetch_all_sources()
    print(f"抓取完成，共 {len(all_articles)} 条有效文章，耗时 {time.time()-start_time:.1f} 秒")
    if not all_articles:
        print("⚠️ 未抓到任何文章，请检查网络或 RSS 源。")
        with open("report.md", "w", encoding="utf-8") as f:
            f.write("# 抓取失败\n\n未抓到任何文章，请检查日志。")
        with open("report.html", "w", encoding="utf-8") as f:
            f.write("<h1>抓取失败</h1><p>未抓到任何文章，请检查 GitHub Actions 日志。</p>")
        return
    save_reports(all_articles)
    print(f"全部完成，总耗时 {time.time()-start_time:.1f} 秒")

if __name__ == "__main__":
    main()
