import json
from datetime import datetime

# ================== 配置区（你以后主要在这里修改账号）==================
ACCOUNTS = {
    "level1": ["https://x.com/账号1", "https://x.com/账号2"],   # 一级：每小时爬一次
    "level2": ["https://x.com/账号3"],                         # 二级：每3小时
    "level3": ["https://x.com/账号4"]                          # 三级：每6小时
}

HUA_KEYWORDS = ["中国", "华为", "TikTok", "内容安全", "舆情", "审查", "涉华", "习近平", "大陆", "北京", "台湾"]

def main():
    now = datetime.now()
    
    # 目前是模拟版本（先让整个系统跑起来，后续再换真实爬取）
    reports = []
    for level, urls in ACCOUNTS.items():
        for url in urls:
            reports.append({
                "event": "示例：某账号发布关于中国内容安全政策的讨论内容...",
                "link": url + "/status/1234567890123456789",
                "risk": "潜在风险：涉华内容，可能涉及内容安全审查",
                "level": level,
                "time": now.isoformat()
            })
    
    # 生成 Markdown 报告（严格按你的要求格式）
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(f"# 内容安全行业舆情报告\n")
        f.write(f"更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for r in reports:
            f.write(f"## 事件简述\n{r['event']}\n")
            f.write(f"**原文链接**：{r['link']}\n")
            f.write(f"**潜在风险点**：{r['risk']}\n\n")
    
    print("✅ 报告生成完成！")

if __name__ == "__main__":
    main()
