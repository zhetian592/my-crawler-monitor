import os
import feedparser
import json
from datetime import datetime
import openai
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ================== 配置 ==================
# OpenAI Key
openai.api_key = os.getenv("OPENAI_API_KEY")

# 信源列表（已包含示例，你可以按需补全）
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
        "https://rsshub.app/twitter/user/whyyoutouzhele",
        "https://rsshub.app/twitter/user/Chai20230817",
        "https://rsshub.app/twitter/user/ChingteLai",
        # … 继续补全一级 X 用户
    ],
    "level2": [
        "https://rsshub.app/stnn",
        "https://rsshub.app/6park",
        "https://rsshub.app/boxun",
        "https://rsshub.app/reddit/r/mohu",
        # … 继续补全二级网站与 X 用户
    ],
    "level3": [
        "https://rsshub.app/mingpao",
        "https://rsshub.app/theinitium",
        "https://rsshub.app/soundofhope.org",
        # … 继续补全三级网站与 X 用户
    ]
}

# 关键词（用于 AI 分析提示）
KEYWORDS = ["中国", "习近平", "人权", "六四", "维吾尔", "西藏", "台湾", "民主", "独裁", "审查", "反共", "中共", "迫害", "天安门"]

# ================== 功能 ==================

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
                "published": entry.get("published", ""),
                "source": url
            })
        return items
    except Exception as e:
        print(f"[ERROR] {url} 抓取失败: {e}")
        return []

def analyze_with_ai(text):
    """调用 GPT 分析文本，返回敏感信息和风险点"""
    prompt = f"""
请分析以下内容：
1. 是否涉及中国敏感话题（台湾、新疆、维吾尔、人权、外交等）
2. 提炼事件摘要（50字以内）
3. 生成潜在风险点（30字以内）
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
        result_text = resp.choices[0].message.content.strip()
        try:
            return json.loads(result_text)
        except:
            print(f"[WARN] AI 返回非 JSON，使用默认值\n返回内容：{result_text}")
            return {"sensitive": False, "summary": "", "risk_point": "", "risk_level": "低"}
    except Exception as e:
        print(f"[ERROR] AI 调用失败: {e}")
        return {"sensitive": False, "summary": "", "risk_point": "", "risk_level": "低"}

def process_item(item, level):
    """处理单条 RSS 条目"""
    text = item['title'] + " " + item['summary']
    ai_result = analyze_with_ai(text)
    if ai_result.get("sensitive"):
        return {
            "title": item['title'],
            "link": item['link'],
            "summary": ai_result.get("summary",""),
            "risk_point": ai_result.get("risk_point",""),
            "risk_level": ai_result.get("risk_level","低"),
            "level": level
        }
    return None

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
    os.makedirs("report", exist_ok=True)
    with open("report/report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"✅ 报告生成完成，共 {len(items)} 条")

# ================== 主程序 ==================
def main():
    all_items = []
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for level, urls in SOURCES.items():
            for url in urls:
                futures.append(executor.submit(fetch_rss_items, url))
        for future in as_completed(futures):
            rss_items = future.result()
            for item in rss_items:
                for level_name, urls in SOURCES.items():
                    if item['source'] in urls:
                        processed = process_item(item, level_name)
                        if processed:
                            all_items.append(processed)
                time.sleep(0.5)  # 避免过快调用 AI
    generate_report(all_items)

if __name__ == "__main__":
    main()
