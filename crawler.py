#!/usr/bin/env python3
# crawler_optimized_with_keywords.py

import os
import json
import time
import re
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import requests
from bs4 import BeautifulSoup
import openai

# ================= 配置 =================
GH_TOKEN = os.environ.get("GH_MODELS_TOKEN") or os.environ.get("GITHUB_TOKEN")
AI_BASE_URL = "https://models.inference.ai.azure.com"
AI_MODEL = "gpt-4o-mini"

RSSHUB_INSTANCES = ["https://rsshub.app", "https://rsshub.feeded.xyz"]
NITTER_INSTANCES = ["https://nitter.net", "https://nitter.poast.org", "https://nitter.linuxboot.org"]

RAW_SOURCES = [
    # 放你的所有原始 RSS 和 X 账号链接
]

# ================= 敏感关键词 =================
SENSITIVE_KEYWORDS = [
    # 历史事件与政治运动
    "六四", "白纸运动", "文革", "文化大革命", "反右", "三反五反", "红卫兵", "造反派", 
    "阶级斗争", "学生运动", "镇压", "清华事件", "北大事件", "六四纪念", "天安门事件",
    
    # 社会运动与舆论
    "言论自由", "维权", "异议人士", "异见者", "劳工运动", "环保维权",
    "网络封锁", "舆论管控", "媒体打压", "公民抗议", "思想改造",
    "意识形态管控", "禁书", "禁闻", "思想整肃",
    
    # 民族与分裂主义
    "西藏独立", "港独", "台独", "台湾独立", "维吾尔独立", "东突厥斯坦", "藏区起义", "南海争议",
    
    # 科技与经济敏感
    "华为", "中兴", "字节跳动", "TikTok", "芯片", "制裁", "供应链", "外企退出", 
    "对外投资", "贸易战", "中美贸易战",
    
    # 人物与机构
    "习近平", "李克强", "王沪宁", "中共中央", "全国人大", "国务院", "公安部", 
    "中央军委", "中共",
    
    # 社会不满与腐败
    "个人崇拜", "极端主义", "腐败", "特权阶层", "党纪处分",
    
    # 海外势力与舆论风险
    "海外势力", "民运组织", "NGO", "境外基金", "境外媒体", "社交平台",
    "虚假新闻", "网络暴力", "舆论引导"
]

# ================= 工具函数 =================
def clean_html(text):
    if not text:
        return ""
    return BeautifulSoup(text, "html.parser").get_text().strip()[:500]

def parse_published(published_str):
    if not published_str:
        return None
    from dateutil.parser import parse as parse_date
    try:
        dt = parse_date(published_str)
        return dt.replace(tzinfo=None)
    except:
        return None

def url_to_rss(url):
    # 原来的 RSS 转换逻辑
    pass  # 这里可以保持原样

# ================= HTTP 会话 =================
session = requests.Session()
adapter = requests.adapters.HTTPAdapter(max_retries=3)
session.mount("http://", adapter)
session.mount("https://", adapter)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}

# ================= 抓取 =================
def fetch_single_rss(rss_url, original_url):
    try:
        resp = session.get(rss_url, headers=HEADERS, timeout=20)
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
            summary = clean_html(entry.get("summary", "")) or clean_html(entry.get("content", [{}])[0].get("value", "")) or title
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
        print(f"抓取异常 {original_url}: {e}")
        return []

def fetch_with_retry(original_url):
    # 原来的 X.com/Nitter 逻辑
    pass  # 保持原样

def fetch_all_sources():
    # 多线程抓取 + 去重
    pass  # 保持原样

# ================= 关键词筛选 =================
def is_sensitive(article):
    text = f"{article['title']} {article['summary']}".lower()
    return any(k.lower() in text for k in SENSITIVE_KEYWORDS)

# ================= 分批 AI 分析 =================
def call_ai_analysis_batched(all_articles, batch_size=15):
    if not GH_TOKEN:
        return "# AI 分析失败\nGH_MODELS_TOKEN 未设置"
    if not all_articles:
        return "# 无数据\n未抓取到任何文章"

    from openai import OpenAI
    client = OpenAI(base_url=AI_BASE_URL, api_key=GH_TOKEN)
    sensitive_articles = [a for a in all_articles if is_sensitive(a)]
    if not sensitive_articles:
        return "过去24小时无涉华内容"

    result_text = ""
    for i in range(0, len(sensitive_articles), batch_size):
        batch = sensitive_articles[i:i+batch_size]
        content_list = []
        for idx, art in enumerate(batch, i+1):
            content_list.append(
                f"{idx}. 标题：{art.get('title','')[:150]}\n"
                f"   摘要：{art.get('summary','')[:300]}\n"
                f"   链接：{art.get('link','')}"
            )
        prompt = f"""
你是一名专业的网络安全和舆情分析师。
以下为抓取内容，请筛选涉华/敏感信息，并生成内容安全行业舆情报告（Markdown 表格）：
- 列：事件简述、原文链接、潜在风险点
- 原文链接必须使用 [查看](URL) 格式
- 潜在风险点 30 字内描述
- 不要额外说明
以下是内容：
{chr(10).join(content_list)}
"""
        try:
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[
                    {"role": "system", "content": "你是一名专业的网络安全和舆情分析师。"},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4000
            )
            batch_result = response.choices[0].message.content
            result_text += batch_result + "\n"
        except Exception as e:
            print(f"AI 调用失败: {e}")
    return result_text

# ================= 报告保存 =================
def save_reports(report_text, all_articles):
    # Markdown + HTML + 原始 JSON 数据保存
    pass  # 保持原来的 HTML/Markdown 生成逻辑

# ================= 主函数 =================
def main():
    start = time.time()
    all_articles = fetch_all_sources()
    if not all_articles:
        print("未抓取到任何文章")
        return
    report = call_ai_analysis_batched(all_articles)
    save_reports(report, all_articles)
    print(f"完成，总耗时 {time.time()-start:.1f} 秒")

if __name__ == "__main__":
    main()
