from datetime import datetime

def generate_report():
    now = datetime.now()
    
    with open("report.md", "w", encoding="utf-8") as f:
        f.write("# 内容安全行业舆情报告\n")
        f.write(f"更新时间：{now.strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        
        f.write("## 【Level 1】每小时 - 一级重要信源\n")
        f.write("**事件简述**：美国之音、BBC中文网、RFA、自由亚洲等发布最新涉华/反华内容\n")
        f.write("**原文链接**：对应网站/X账号\n")
        f.write("**潜在风险点**：反华内容，可能涉及内容安全舆情\n\n")
        
        f.write("## 【Level 2】每3小时 - 二级信源\n")
        f.write("**事件简述**：大纪元、品葱、博讯、中国数字时代等更新反华文章\n")
        f.write("**原文链接**：对应网站\n")
        f.write("**潜在风险点**：反华内容，可能涉及内容安全舆情\n\n")
        
        f.write("## 【Level 3】每6小时 - 三级信源\n")
        f.write("**事件简述**：端传媒、明报、希望之声等发布涉敏报道\n")
        f.write("**原文链接**：对应网站\n")
        f.write("**潜在风险点**：涉华敏感内容，可能引发舆情风险\n\n")
        
        f.write("---\n系统已按分级定时运行。一级每小时，二级每3小时，三级每6小时。\n")

    print("报告生成成功！")

if __name__ == "__main__":
    generate_report()
