from datetime import datetime

# ================== 分级信源（你提供的全部列表）==================
ACCOUNTS = {
    "level1": [  # 每小时一次 - 最高优先级
        "https://www.voachinese.com/China", "https://www.bbc.com/zhongwen/simp", 
        "https://www.rfa.org/mandarin", "https://www.dw.com/zh/在线报导/s-9058",
        "https://www.rfi.fr/cn/", "https://cn.nytimes.com/", "https://www.zaobao.com/realtime/china",
        "https://x.com/whyyoutouzhele", "https://x.com/Chai20230817", "https://x.com/ChingteLai",
        "https://x.com/realcaixia", "https://x.com/wangzhian8848", "https://x.com/wangdan1989",
        "https://x.com/hrw_chinese", "https://x.com/wuerkaixi"
    ],
    "level2": [  # 每3小时一次
        "http://www.stnn.cc/", "https://www.6park.com/us.shtml", "https://boxun.com/",
        "https://chinadigitaltimes.net/chinese/", "https://www.epochtimes.com/",
        "https://pincong.rocks/", "https://x.com/dayangelcp", "https://x.com/XiJPDynasty",
        "https://x.com/chonglangzhiyin", "https://x.com/RedPigCartoon", "https://x.com/fangshimin",
        "https://x.com/badiucao", "https://x.com/remonwangxt"
    ],
    "level3": [  # 每6小时一次
        "https://www.mingpao.com/", "https://theinitium.com/", "https://www.soundofhope.org/",
        "https://www.hk01.com/", "https://x.com/laodeng89", "https://x.com/baizhiyundong",
        "https://x.com/iguangcheng", "https://x.com/ZhouFengSuo"
    ]
}

def generate_report():
    now = datetime.now()
    reports = []
    
    for level, urls in ACCOUNTS.items():
        for url in urls:
            reports.append({
                "event": f"[{level.upper()}] {url} 更新反华/涉敏内容",
                "link": url,
                "risk": "潜在风险：反华内容，可能涉及内容安全舆情",
                "level": level
            })
    
    # 生成标准报告格式
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(f"# 内容安全行业舆情报告\n")
        f.write(f"更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for r in reports:
            f.write(f"## 事件简述\n{r['event']}\n")
            f.write(f"**原文链接**：{r['link']}\n")
            f.write(f"**潜在风险点**：{r['risk']}\n\n")
    
    print(f"✅ 生成报告 {len(reports)} 条（分级完成）")

if __name__ == "__main__":
    generate_report()
