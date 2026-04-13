import os
import json
import feedparser
from datetime import datetime
from typing import List, Dict
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import quote

# ================= 配置信源 =================
TIER_SOURCES = {
    "1": [
        # 一级网站
        "https://www.voachinese.com/China",
        "https://www.voachinese.com/p/6197.html",
        "https://www.bbc.com/zhongwen/simp",
        "https://www.rfa.org/mandarin",
        "https://www.dw.com/zh/%E5%9C%A8%E7%BA%BF%E6%8A%A5%E5%AF%BC/s-9058",
        "https://www.rfi.fr/cn/",
        "https://cn.nytimes.com/",
        "https://www.zaobao.com/realtime/china",
        # 一级社交媒体
        "https://x.com/whyyoutouzhele",
        "https://x.com/Chai20230817",
        "https://x.com/ChingteLai",
        "https://x.com/newszg_official",
        "https://x.com/YesterdayBigcat",
        "https://x.com/realcaixia",
        "https://x.com/wangzhian8848",
        "https://x.com/june4thmuseum",
        "https://x.com/wangdan1989",
        "https://x.com/hrw_chinese",
        "https://x.com/wuerkaixi",
        "https://x.com/torontobigface",
    ],
    "2": [
        # 二级网站
        "http://www.stnn.cc/",
        "https://www.6park.com/us.shtml",
        "https://boxun.com/",
        "https://www.reddit.com/r/mohu/",
        "http://www.sintaiwan.url.tw/",
        "https://chinadigitaltimes.net/chinese/",
        "https://www.ntdtv.com/b5/",
        "https://www.secretchina.com/",
        "https://blog.creaders.net/",
        "https://www.epochtimes.com/",
        "https://pincong.rocks/",
        "http://www.lexiangge.com/",
        "https://www.fanzei.net/",
        "http://hanfeng1918.com/",
        "https://iwantrun.com/",
        "https://xizang-zhiye.org/",
        "https://cn.uyghurcongress.org/",
        # 二级社交媒体
        "https://x.com/dayangelcp",
        "https://x.com/XiJPDynasty",
        "https://x.com/chinatransition",
        "https://x.com/chonglangzhiyin",
        "https://x.com/pear14525902",
        "https://x.com/xingzhe2021",
        "https://x.com/RedPigCartoon",
        "https://x.com/jhf8964",
        "https://x.com/Cian_Ci",
        "https://x.com/fangshimin",
        "https://x.com/remonwangxt",
        "https://x.com/badiucao",
        "https://x.com/xinwendiaocha",
        "https://x.com/WOMEN4China",
        "https://x.com/Ruters0615",
        "https://x.com/CitizensDailyCN",
        "https://x.com/ZhouFengSuo",
        "https://x.com/hchina89",
        "https://x.com/gaoyu200812",
        "https://x.com/amnestychinese",
        "https://x.com/lidangzzz",
        "https://x.com/liangziyueqian1",
        "https://x.com/YongyuanCui1",
        "https://x.com/jielijian",
        "https://x.com/xiaojingcanxue",
        "https://x.com/CHENWEIMING2017",
        "https://x.com/xiangjunweiwu",
        "https://x.com/BoKuangyi",
        "https://x.com/tibetdotcom",
        "https://x.com/chinesepen_org",
        "https://x.com/UHRP_Chinese",
        "https://x.com/wurenhua",
    ],
    "3": [
        # 三级网站
        "https://www.mingpao.com/",
        "https://theinitium.com/",
        "https://www.soundofhope.org/",
        "https://chinademocrats.org/",
        "http://wqw2010.blogspot.com/",
        "https://www.hk01.com/",
        "https://2newcenturynet.blogspot.com/",
        "https://lingbaxianzhang.blogspot.com/",
        "http://dongtaiwang.com/loc/phome.php?v=0",
        "http://minzhuzhongguo.org/",
        "http://www.chinainperspective.com/",
        "https://msguancha.com/",
        "http://bjs.org/",
        "https://2047.one/",
        "https://jinpianwang.com/",
        "https://www.aboluowang.com/index.html",
        "https://www.bannedbook.org/",
        # 三级社交媒体
        "https://x.com/zijuan_chen",
        "https://x.com/weiquanwang",
        "https://x.com/hnczyhhwck",
        "https://x.com/laodeng89",
        "https://x.com/taocomic",
        "https://x.com/SpeechFreedomCN",
        "https://x.com/uzhuan2/following",
        "https://x.com/GFWfrog",
        "https://x.com/aboluowang",
        "https://x.com/zhbl01",
        "https://x.com/Rumoreconomy",
        "https://x.com/xjpw1cnm",
        "https://x.com/baizhiyundong",
        "https://x.com/wfeidegenggaoj",
        "https://x.com/wuyuesanren",
        "https://x.com/uzhuan2/following",
        "https://x.com/iguangcheng",
        "https://x.com/Foreign_Force",
        "https://x.com/8964Remember",
        "https://x.com/64anonymous799",
        "https://x.com/GanchengW",
        "https://x.com/xiangjunweiwu",
        "https://x.com/dashengmedia",
        "https://x.com/FH_China",
        "https://x.com/huirights",
        "https://x.com/74rXysi",
        "https://x.com/CHRDnet",
        "https://x.com/RightsLawyersCN",
        "https://x.com/tiffany21047370",
        "https://x.com/LiutaoTang",
    ]
}

# ================= 中国相关关键词 =================
CHINA_KEYWORDS = [
    "中国", "中共", "北京", "习近平", "台湾", "香港", "新疆", "西藏",
    "南海", "中美", "华为", "字节跳动", "TikTok", "一带一路", "武统"
]

# ================= 功能函数 =================
def is_china_related(text: str) -> bool:
    text_lower = text.lower()
    return any(kw.lower() in text_lower for kw in CHINA_KEYWORDS)

def generate_risk_point(title: str, summary: str) -> str:
    if "台湾" in title or "台湾" in summary:
        return "违反一个中国原则，可能引发外交争议"
    if "新疆" in title:
        return "涉及新疆议题，需防范西方舆论炒作"
    if "华为" in title and "制裁" in summary:
        return "科技供应链风险，可能影响相关企业"
    if "南海" in title:
        return "地缘政治敏感，可能引发区域紧张"
    return "可能引起网络舆论关注"

def clean_text(html_text: str) -> str:
    text = BeautifulSoup(html_text, "html.parser").get_text()
    return text.replace("\n", " ").replace("|", "/").strip()

def fetch_rss_items(url: str) -> List[Dict]:
    try:
        feed = feedparser.parse(url)
        items = []
        for entry in feed.entries[:20]:
            summary_text = clean_text(entry.get("summary", ""))
            item = {
                "title": clean_text(entry.get("title", "")),
                "link": entry.get("link", ""),
                "summary": summary_text,
                "published": entry.get("published", entry.get("updated", "")),
                "source": url,
                "fetched_at": datetime.utcnow().isoformat()
            }
            items.append(item)
       
