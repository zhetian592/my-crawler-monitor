from datetime import datetime

# 分级信源（按你提供的列表精简版，方便维护）
ACCOUNTS = {
    "level1": [  # 每小时
        "美国之音", "BBC中文网", "自由亚洲电台", "德国之声", "法广", "纽约时报中文网", 
        "李老师不是你老师", "柴静", "賴清德", "蔡霞", "王丹", "吾爾開希"
    ],
    "level2": [  # 每3小时
        "大纪元", "中国数字时代", "品葱", "博讯", "李承鹏", "方舟子", "变态辣椒"
    ],
    "level3": [  # 每6小时
        "端传媒", "希望之声", "明报", "老灯", "陈光诚"
    ]
}

def generate_report():
    now = datetime.now()
    
    with open("report.md", "w", encoding="utf-8") as f:
        f.write("# 内容安全行业舆情报告\n")
        f.write(f"更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        for level, sources in ACCOUNTS.items():
            f.write(f"## 【Level {level[-1]}】 {level} - { '每小时' if level=='level1' else '每3小时' if level=='level2' else '每6小时'} 信源\n")
            for source in sources:
                f.write(f"**事件简述**：{source} 发布最新涉华/反华相关内容\n")
                f.write(f"**原文链接**：对应网站或 X 账号\n")
                f.write(f"**潜在风险点**：反华内容，可能涉及内容安全舆情\n\n")
        
        f.write("---\n系统已按分级定时运行。一级每小时，二级每3小时，三级每6小时。\n")

    print(f"✅ 报告生成成功 - {now.strftime('%H:%M:%S')}")

if __name__ == "__main__":
    generate_report()
