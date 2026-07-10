# 在文件顶部导入区增加（可选）
try:
    from dateutil import parser as dateutil_parser
    DATEUTIL_AVAILABLE = True
except ImportError:
    DATEUTIL_AVAILABLE = False

# 修改 url_to_rss 函数
def url_to_rss(url: str, rsshub_instances: List[str]) -> Union[str, List[str], None]:
    # 若本身是 RSS/XML 地址，直接使用
    if any(url.endswith(ext) for ext in ('.xml', '/feed', '/rss')) or '/feed/' in url:
        return url

    rsshub = random.choice(rsshub_instances)

    # === VOA：优先用官方 API，其次 RSSHub，不再使用 FeedBurner ===
    if "voachinese.com" in url:
        return [
            "https://www.voachinese.com/api/z$ygejto",       # 官方动态内容接口
            "https://www.voachinese.com/api/z$ygeqjto",      # 备用
            f"{rsshub}/voachinese/china",                    # RSSHub 保底
        ]
    # ... 其余映射保持不变 ...

# 增强日期解析
def parse_published_strict(published_str: Optional[str]) -> Optional[datetime]:
    if not published_str:
        return None
    formats = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%d %H:%M:%S",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S.%f%z",          # 带毫秒+时区
        "%Y-%m-%dT%H:%M:%S.%fZ",           # 带毫秒Z
        "%a, %d %b %Y %H:%M:%S %Z",        # 已存在，保留
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(published_str, fmt)
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
        except:
            continue
    # 兜底：使用 dateutil（若可用）
    if DATEUTIL_AVAILABLE:
        try:
            dt = dateutil_parser.parse(published_str)
            if dt.tzinfo:
                dt = dt.replace(tzinfo=None)
            return dt
        except:
            pass
    return None

# 新增：VOA 直接 HTML 抓取
def fetch_voa_direct(url: str, processed_hashes: set, url_cache: URLDedupCache, time_window_hours: int) -> List[Dict]:
    try:
        resp = fetch_url(url, timeout=25)
        soup = BeautifulSoup(resp.content, "html.parser")
        items = []
        cutoff = datetime.utcnow() - timedelta(hours=time_window_hours)
        for article in soup.select('a[href*="/a/"]'):
            link = article.get("href", "")
            if not link:
                continue
            if not link.startswith("http"):
                link = "https://www.voachinese.com" + link
            if url_cache.seen(link):
                continue
            title = article.get_text(strip=True)
            if not title or len(title) < 10:
                continue
            h = content_hash(title, "")
            if h in processed_hashes:
                continue
            processed_hashes.add(h)
            pub_dt = None
            time_elem = article.find_previous("time") or article.find_next("time")
            if time_elem and time_elem.get("datetime"):
                pub_dt = parse_published_strict(time_elem["datetime"])
            items.append({
                "title": title,
                "link": link,
                "summary": title,
                "source": url,
                "source_name": "www.voachinese.com",
                "published_str": pub_dt.isoformat() if pub_dt else "未知时间",
                "pub_dt": pub_dt.isoformat() if pub_dt else None,
                "time_ago": format_time_ago(pub_dt),
                "fetched_at": datetime.utcnow().isoformat()
            })
            url_cache.add(link)
        logger.info(f"VOA HTML直接抓取：{len(items)} 条")
        return items
    except Exception as e:
        logger.error(f"VOA HTML抓取失败: {e}")
        return []

# 在 fetch_with_retry() 末尾所有 RSS 尝试失败后，加入 VOA 兜底
def fetch_with_retry(original_url: str, processed_hashes: set, url_cache: URLDedupCache, time_window_hours: int) -> List[Dict]:
    # ... 原有逻辑 ...
    # 所有 RSS 地址均失败后：
    if "voachinese.com" in original_url:
        logger.info(f"VOA RSS 全部失败，尝试直接抓取 HTML: {original_url}")
        html_items = fetch_voa_direct(original_url, processed_hashes, url_cache, time_window_hours)
        if html_items:
            return html_items
    return []
