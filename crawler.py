import os
import feedparser
import json
from datetime import datetime
import openai
import time

# ===================== 配置 =====================
SOURCES = {
    "level1": [
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/voachinese/6197",
        "https://rsshub.app/bbc/zhongwen/simp",
        "https://rsshub.app/rfa/mandarin",
        "https://rsshub.app/dw/zh/在线报导/s-9058",
        "https://rsshub.app/rfi/cn",
        "https://rsshub.app/nytimes/zh",
        "https://rsshub.app/zaobao/realtime/china",
        # X 一级账号示例
        "https://rsshub.app/twitter/user/whyyoutouzhele",
        "https://rsshub.app/twitter/user/Chai20230817",
        "https://rsshub.app/twitter/user/ChingteLai",
    ],
    "level2": [
        "https://rsshub.app/stnn",
        "https://rsshub.app/6park",
        "https://rsshub.app/boxun",
        "https://rsshub.app/reddit/r/mohu",
    ],
    "level3": [
        "https://rsshub.app/mingpao",
        "https://rsshub.app/theinitium",
        "https://rsshub.app/soundofhope.org",
    ]
}

# OpenAI Key
openai.api_key = os.getenv("OPENAI_API_KEY")

# ===================== 功能 =====================
def fetch_rss_items(url, limit=5):
    """抓取 RSS 条目"""
    try:
        feed = feedparser.parse(url)
        if feed.bozo:
            print(f"[WARN] {url} RSS 解析异常: {feed.bozo_exception}")
            return []
        items = []
        for entry in feed.entries[:limit]:
            items.append({
                "title": entry.get("title", ""),
                "link": entry.get("link", ""),
                "summary": entry.get("summary", ""),
                "published": entry.get("published", "")
            })
        return items
    except Exception as e:
        print(f"[ERROR] {url} 抓取失败: {e}")
        return []

def analyze_with_ai(text):
    """调用 GPT 分析文本，生成摘要和风险点"""
    prompt = f"""
请阅读以下内容，并分析：
1. 是否涉及中国敏感话题（台湾、新疆、维吾尔、人权、外交等）
2. 提炼事件摘要（50字以内）
3. 生成潜在风险点（不超过30字）
4. 给出风险等级（高/中/低）

内容：
{text}

请返回 JSON 格式：
{{
    "sensitive": true/false,
    "summary": "...",
    "risk_point": "...",
    "risk_level": "高/中/低"
}}
"""
    try:
        resp = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            temperature=0.2,
            request_timeout=60
        )
        result_text = resp.choices[0].message.content
        # 尝试解析 JSON
        result_json = json.loads(result_text)
        return result_json
    except Exception as e:
        print(f"[AI ERROR] 分析失败: {e}")
        return {"sensitive": False, "summary": "", "risk_point": "", "risk_level": "低"}

def generate_report(items):
    """生成 Markdown 报告"""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# 智能舆情报告",
        f"生成时间：{now} UTC",
        "",
        "| 摘要 | 链接 | 风险点 | 风险等级 | 来源等级 |",
        "|------|------|--------|----------|-----------|"
    ]
    for item in items:
        lines.append(
            f"| {item['summary']} | [链接]({item['link']}) | {item['risk_point']} | {item['risk_level']} | {item['level']} |"
        )
    with open("report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 报告生成完成，共 {len(items)} 条")

# ===================== 主程序 =====================
def main():
    all_items = []
    for level, urls in SOURCES.items():
        for url in urls:
            print(f"抓取 {url} ...")
            items = fetch_rss_items(url)
            for it in items:
                text = it['title'] + " " + it['summary']
                ai_result = analyze_with_ai(text)
                if ai_result.get("sensitive"):
                    all_items.append({
                        "title": it['title'],
                        "link": it['link'],
                        "summary": ai_result.get("summary",""),
                        "risk_point": ai_result.get("risk_point",""),
                        "risk_level": ai_result.get("risk_level","低"),
                        "level": level
                    })
                # 避免短时间请求太多被封
                time.sleep(1)
    generate_report(all_items)

if __name__ == "__main__":
    main()
