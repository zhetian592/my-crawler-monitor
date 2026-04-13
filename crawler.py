import os
import feedparser
import requests
from datetime import datetime
import openai

# ===================== 配置 =====================
# RSS / X 用户示例
SOURCES = {
    "level1": [
        "https://rsshub.app/voachinese/china",
        "https://rsshub.app/twitter/user/whyyoutouzhele"
    ],
    "level2": [
        "https://rsshub.app/6park"
    ]
}

# OpenAI Key
openai.api_key = os.getenv("OPENAI_API_KEY")

# ===================== 功能 =====================
def fetch_rss_items(url, limit=10):
    """抓取 RSS 或 RSSHub 的最新条目"""
    try:
        feed = feedparser.parse(url)
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
        print(f"[ERROR] 拉取 {url} 失败: {e}")
        return []

def analyze_with_ai(text):
    """调用 OpenAI GPT 分析内容"""
    prompt = f"""
请阅读以下内容，并基于中国政治、外交、社会敏感事件生成分析：
1. 是否涉及敏感话题（台湾、新疆、人权、科技、外交等）
2. 生成潜在风险点（不超过30字）
3. 提炼简短事件摘要（50字左右）
4. 给出风险等级（高、中、低）
内容：
{text}
请以 JSON 格式返回：
{{
  "sensitive": true/false,
  "risk_point": "...",
  "summary": "...",
  "risk_level": "高/中/低"
}}
"""
    try:
        response = openai.ChatCompletion.create(
            model="gpt-3.5-turbo",
            messages=[{"role":"user","content":prompt}],
            temperature=0.2
        )
        content = response['choices'][0]['message']['content']
        # 尝试解析 JSON
        import json
        return json.loads(content)
    except Exception as e:
        print(f"[AI ERROR] 分析失败: {e}")
        return {
            "sensitive": False,
            "risk_point": "",
            "summary": "",
            "risk_level": "低"
        }

def generate_report(all_items):
    """生成 Markdown 报告"""
    now = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    lines = [
        f"# 舆情智能分析报告",
        f"生成时间：{now} UTC",
        "",
        "| 摘要 | 原文链接 | 风险点 | 风险等级 | 来源等级 |",
        "|------|----------|--------|----------|-----------|"
    ]
    for item in all_items:
        lines.append(
            f"| {item['ai_summary']} | [链接]({item['link']}) | {item['risk_point']} | {item['risk_level']} | {item['level']} |"
        )
    with open("report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 报告生成完成，共 {len(all_items)} 条")

# ===================== 主程序 =====================
def main():
    all_items = []
    for level, urls in SOURCES.items():
        for url in urls:
            print(f"抓取 {url} ...")
            items = fetch_rss_items(url)
            for item in items:
                text = item['title'] + " " + item['summary']
                ai_result = analyze_with_ai(text)
                if ai_result.get("sensitive"):
                    all_items.append({
                        "title": item['title'],
                        "link": item['link'],
                        "ai_summary": ai_result.get("summary", ""),
                        "risk_point": ai_result.get("risk_point", ""),
                        "risk_level": ai_result.get("risk_level", ""),
                        "level": level
                    })
    generate_report(all_items)

if __name__ == "__main__":
    main()
