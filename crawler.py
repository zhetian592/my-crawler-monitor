def call_ai_analysis(all_articles):
    if not OPENROUTER_API_KEY:
        return "# AI 分析失败\nOPENROUTER_API_KEY 未设置，请检查 Secrets。"

    if not all_articles:
        return "# 无数据\n过去24小时未抓取到任何文章"

    content_list = []
    for idx, art in enumerate(all_articles[:25], 1):
        content_list.append(f"{idx}. 标题：{art.get('title', '')[:150]}\n   链接：{art.get('link', '')}\n")
    combined = "\n".join(content_list)

    prompt = f"""你是一名专业的舆情分析师。

以下是过去24小时抓取的内容。

请严格按照以下格式生成报告：

# 内容安全行业舆情报告
生成时间：{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC

| 事件简述 | 原文链接 | 潜在风险点 |
|----------|----------|------------|
| （简述事件，不超过60字） | [查看](链接) | （风险点，不超过30字） |

只输出涉华内容。没有时只输出“过去24小时无涉华内容”。不要额外文字。

内容：
{combined}"""

    try:
        response = requests.post(
            f"{BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json"
            },
            json={
                "model": "deepseek/deepseek-chat:free",   # ← 改成这个稳定模型
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.3,
                "max_tokens": 2000
            },
            timeout=60
        )
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]["content"]
        else:
            return f"# AI 分析失败\nHTTP {response.status_code}\n{response.text[:300]}"
    except Exception as e:
        return f"# AI 分析失败\n异常: {str(e)}"
