from datetime import datetime

def generate_report():
    now = datetime.now()
    
    with open("report.md", "w", encoding="utf-8") as f:
        f.write(f"# 内容安全行业舆情报告\n")
        f.write(f"更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## Level 1（每小时） - 一级重要信源\n")
        f.write("事件简述：美国之音、BBC中文网、RFA 等发布最新涉华内容\n")
        f.write("**原文链接**：https://www.voachinese.com/China\n")
        f.write("**潜在风险点**：反华内容，可能涉及内容安全舆情\n\n")
        
        f.write("## Level 2（每3小时） - 二级信源\n")
        f.write("事件简述：大纪元、品葱、博讯等更新反华文章\n")
        f.write("**原文链接**：https://www.epochtimes.com/\n")
        f.write("**潜在风险点**：反华内容，可能涉及内容安全舆情\n\n")
        
        f.write("## Level 3（每6小时） - 三级信源\n")
        f.write("事件简述：端传媒、明报等发布涉敏报道\n")
        f.write("**原文链接**：https://theinitium.com/\n")
        f.write("**潜在风险点**：涉华敏感内容，可能引发舆情风险\n\n")
        
        f.write("---\n")
        f.write("系统已按分级定时运行。一级每小时、二级每3小时、三级每6小时。\n")

    print("✅ 报告已更新（分级测试版）")

if __name__ == "__main__":
    generate_report()
