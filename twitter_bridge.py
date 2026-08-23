#!/usr/bin/env python3
# twitter_bridge.py - 自建 Twitter RSS 桥接（使用 X 登录 Token）
# 启动: TWITTER_AUTH_TOKEN=xxx python twitter_bridge.py --port 3000
# 环境变量:
#   TWITTER_AUTH_TOKEN  - X/Twitter 登录后的 auth_token cookie（必需）
#   TWITTER_CT0         - X/Twitter 的 ct0 cookie（可选，自动获取）

import argparse
import json
import time
import random
import logging
import sys
import os
import re
from collections import OrderedDict
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, quote
from xml.sax.saxutils import escape as xml_escape

import requests

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger('twitter-bridge')

# ===================== 配置 =====================
CACHE_TTL = 900          # 缓存 15 分钟
CACHE_MAX_SIZE = 100
DEFAULT_TIMEOUT = 30

# Twitter API 公共 Bearer Token（用于 guest token 激活）
BEARER_TOKEN = (
    "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D"
    "1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)

# Twitter GraphQL Query IDs（从 x.com 主 JS 动态提取，2026-08-23）
QUERY_IDS = {
    "UserByScreenName": "Gb-d6r0vxPOADdG62OEBpQ",
    "UserTweets": "SXVCYB8XHSS25nzIljNtZA",
}

# 备用 Query IDs（如果主 ID 失效，按顺序尝试）
FALLBACK_QUERY_IDS = {
    "UserByScreenName": [
        "Gb-d6r0vxPOADdG62OEBpQ",
        "G3KGOASz96M-Qu0nwmGXNg",
        "k5XapwcSikNsEsILW5FvgA",
    ],
    "UserTweets": [
        "SXVCYB8XHSS25nzIljNtZA",
        "V7H0Ap3eTZx6QvxGhhGOtw",
        "nO3VVx1Fz_guJXmlJ0aX0A",
    ],
}

UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "Chrome/134.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "Chrome/133.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "Chrome/132.0.0.0 Safari/537.36",
]

# ===================== 缓存 =====================
_cache = OrderedDict()
_cache_lock = __import__('threading').Lock()


def cache_get(key):
    with _cache_lock:
        entry = _cache.get(key)
        if entry and time.time() - entry[0] < CACHE_TTL:
            _cache.move_to_end(key)
            return entry[1]
    return None


def cache_set(key, content):
    with _cache_lock:
        _cache[key] = (time.time(), content)
        _cache.move_to_end(key)
        if len(_cache) > CACHE_MAX_SIZE:
            _cache.popitem(last=False)


# ===================== Twitter API 客户端 =====================
class TwitterClient:
    def __init__(self, auth_token: str, ct0: str = None):
        self.auth_token = auth_token
        self.ct0 = ct0
        self.guest_token = None
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": random.choice(UA_LIST),
            "Authorization": f"Bearer {BEARER_TOKEN}",
        })
        self._activate_guest_token()
        if not self.ct0:
            self._fetch_ct0()

    def _activate_guest_token(self):
        """激活 guest token（用于访问公共 API）"""
        try:
            resp = self.session.post(
                "https://api.twitter.com/1.1/guest/activate.json",
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                self.guest_token = data.get("guest_token")
                if self.guest_token:
                    self.session.headers["x-guest-token"] = self.guest_token
                    logger.info("Guest token 激活成功")
                    return
        except Exception as e:
            logger.warning(f"Guest token 激活失败: {e}")
        # 使用备用方法
        self.guest_token = ""

    def _fetch_ct0(self):
        """从 Twitter 首页获取 ct0 cookie"""
        try:
            resp = self.session.get(
                "https://twitter.com/",
                timeout=15,
                cookies={"auth_token": self.auth_token} if self.auth_token else None,
            )
            for cookie in resp.cookies:
                if cookie.name == "ct0":
                    self.ct0 = cookie.value
                    logger.info(f"获取到 ct0: {self.ct0[:10]}...")
                    return
            # 从 HTML 中提取
            match = re.search(r'ct0=([a-f0-9]+)', resp.text)
            if match:
                self.ct0 = match.group(1)
                logger.info(f"从 HTML 提取 ct0: {self.ct0[:10]}...")
                return
        except Exception as e:
            logger.warning(f"获取 ct0 失败: {e}")

    def _make_authenticated_request(self, url, params=None):
        """使用 auth_token 发起认证请求"""
        headers = {
            "User-Agent": random.choice(UA_LIST),
            "Authorization": f"Bearer {BEARER_TOKEN}",
            "x-csrf-token": self.ct0 or "",
            "x-twitter-active-user": "yes",
            "x-twitter-auth-type": "OAuth2Session",
            "Origin": "https://twitter.com",
            "Referer": "https://twitter.com/",
        }
        if self.guest_token:
            headers["x-guest-token"] = self.guest_token

        cookies = {"auth_token": self.auth_token}
        if self.ct0:
            cookies["ct0"] = self.ct0

        return self.session.get(
            url,
            params=params,
            headers=headers,
            cookies=cookies,
            timeout=DEFAULT_TIMEOUT,
        )

    def get_user_by_screen_name(self, username: str) -> dict:
        """通过用户名查找用户信息"""
        variables = json.dumps({
            "screen_name": username,
            "withSafetyModeUserFields": True,
            "withSuperFollowsUserFields": False,
        })
        features = json.dumps({
            "hidden_profile_likes_enabled": True,
            "hidden_profile_subscriptions_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "subscriptions_verification_info_is_identity_verified_enabled": True,
            "subscriptions_verification_info_verified_since_enabled": True,
            "highlights_tweets_tab_ui_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "tweetypie_unmention_optimization_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "freedom_of_speech_not_reach_appeal_label_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_media_download_video_enabled": False,
            "responsive_web_enhance_cards_enabled": False,
        })

        for query_id in FALLBACK_QUERY_IDS["UserByScreenName"]:
            try:
                resp = self._make_authenticated_request(
                    f"https://twitter.com/i/api/graphql/{query_id}/UserByScreenName",
                    params={"variables": variables, "features": features},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    user_result = data.get("data", {}).get("user", {})
                    if user_result and user_result.get("result"):
                        result = user_result["result"]
                        if result.get("__typename") == "User":
                            logger.info(f"找到用户 @{username}: rest_id={result.get('rest_id')}")
                            return result
                elif resp.status_code == 403:
                    logger.warning(f"Query ID {query_id} 返回 403，尝试下一个")
                    continue
                else:
                    logger.warning(f"UserByScreenName 查询失败 (status={resp.status_code}): {resp.text[:200]}")
            except Exception as e:
                logger.warning(f"Query ID {query_id} 异常: {e}")
                continue

        logger.error(f"无法找到用户 @{username}")
        return None

    def get_user_tweets(self, user_id: str, count: int = 40) -> list:
        """获取用户推文"""
        variables = json.dumps({
            "userId": user_id,
            "count": count,
            "includePromotedContent": False,
            "withQuickPromoteEligibilityTweetFields": False,
            "withVoice": True,
            "withV2Timeline": True,
        })
        features = json.dumps({
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "graphql_is_translatable_rweb_tweet_is_translatable_enabled": True,
            "view_counts_everywhere_api_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "creator_subscriptions_quote_tweet_preview_enabled": False,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_rich_text_read_enabled": True,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_media_download_video_enabled": False,
            "responsive_web_enhance_cards_enabled": False,
        })

        for query_id in FALLBACK_QUERY_IDS["UserTweets"]:
            try:
                resp = self._make_authenticated_request(
                    f"https://twitter.com/i/api/graphql/{query_id}/UserTweets",
                    params={"variables": variables, "features": features},
                )
                if resp.status_code == 200:
                    data = resp.json()
                    timeline = data.get("data", {}).get("user", {}).get("result", {}).get("timeline_v2", {})
                    if not timeline:
                        # 尝试另一种结构
                        instructions = (
                            data.get("data", {})
                            .get("user", {})
                            .get("result", {})
                            .get("timeline", {})
                            .get("timeline", {})
                            .get("instructions", [])
                        )
                    else:
                        instructions = timeline.get("instructions", [])

                    tweets = self._parse_tweets(instructions)
                    if tweets:
                        logger.info(f"获取到 {len(tweets)} 条推文 (query_id={query_id})")
                        return tweets
                    else:
                        logger.warning(f"Query ID {query_id} 返回 0 条推文")
                elif resp.status_code == 403:
                    logger.warning(f"Query ID {query_id} 返回 403，尝试下一个")
                    continue
                else:
                    logger.warning(f"UserTweets 查询失败 (status={resp.status_code}): {resp.text[:200]}")
            except Exception as e:
                logger.warning(f"Query ID {query_id} 异常: {e}")
                continue

        logger.error(f"无法获取用户 {user_id} 的推文")
        return []

    def _parse_tweets(self, instructions: list) -> list:
        """解析推文数据"""
        tweets = []
        if not instructions:
            return tweets

        for instruction in instructions:
            if instruction.get("type") == "TimelineAddEntries":
                for entry in instruction.get("entries", []):
                    content = entry.get("content", {})
                    if content.get("entryType") == "TimelineTimelineItem":
                        tweet_result = (
                            content.get("itemContent", {})
                            .get("tweet_results", {})
                            .get("result", {})
                        )
                        if tweet_result and tweet_result.get("__typename") == "Tweet":
                            # 处理转推
                            if "tweet" in tweet_result.get("legacy", {}):
                                # 可能是转推的包装
                                pass

                            legacy = tweet_result.get("legacy", {})
                            core = tweet_result.get("core", {})
                            user_results = core.get("user_results", {}).get("result", {})
                            user_legacy = user_results.get("legacy", {})

                            tweet_id = legacy.get("id_str") or tweet_result.get("rest_id")
                            full_text = legacy.get("full_text", "")
                            created_at = legacy.get("created_at", "")

                            # 解析实体（链接、@提及等）
                            entities = legacy.get("entities", {})
                            urls = {u["url"]: u.get("expanded_url", u["url"])
                                    for u in entities.get("urls", [])}
                            for short_url, expanded_url in urls.items():
                                full_text = full_text.replace(short_url, expanded_url)

                            # 处理媒体
                            media_list = legacy.get("extended_entities", {}).get("media", [])
                            media_urls = []
                            for media in media_list:
                                media_urls.append(media.get("media_url_https", ""))

                            screen_name = user_legacy.get("screen_name", "") or user_results.get("screen_name", "")
                            user_name = user_legacy.get("name", "") or user_results.get("name", "")

                            tweets.append({
                                "id": tweet_id,
                                "text": full_text.strip(),
                                "created_at": created_at,
                                "screen_name": screen_name,
                                "user_name": user_name,
                                "link": f"https://x.com/{screen_name}/status/{tweet_id}",
                                "media_urls": media_urls,
                                "retweet_count": legacy.get("retweet_count", 0),
                                "favorite_count": legacy.get("favorite_count", 0),
                            })

        return tweets


# ===================== RSS 生成 =====================
def build_rss(title, link, desc, items):
    now = datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom">\n'
        '<channel>\n'
    )
    xml += f"<title>{xml_escape(title)}</title>\n"
    xml += f"<link>{xml_escape(link)}</link>\n"
    xml += f"<description>{xml_escape(desc)}</description>\n"
    xml += f"<lastBuildDate>{now}</lastBuildDate>\n"
    for item in items:
        pub = item.get("pubDate", now)
        xml += "<item>\n"
        xml += f'<title>{xml_escape(item["title"])}</title>\n'
        xml += f'<link>{xml_escape(item["link"])}</link>\n'
        xml += f'<description>{xml_escape(item.get("description", ""))}</description>\n'
        xml += f"<pubDate>{pub}</pubDate>\n"
        xml += f'<guid>{xml_escape(item.get("link", item["title"]))}</guid>\n'
        xml += "</item>\n"
    xml += "</channel>\n</rss>"
    return xml


def parse_twitter_date(date_str: str) -> str:
    """将 Twitter 日期格式转换为 RFC 2822"""
    try:
        from datetime import datetime as dt
        d = dt.strptime(date_str, "%a %b %d %H:%M:%S %z %Y")
        return d.strftime("%a, %d %b %Y %H:%M:%S GMT")
    except Exception:
        return datetime.utcnow().strftime("%a, %d %b %Y %H:%M:%S GMT")


# ===================== HTTP 服务器 =====================
class TwitterBridgeHandler(BaseHTTPRequestHandler):
    client = None  # 类变量，由 main 设置

    def log_message(self, format, *args):
        logger.info(f"{self.client_address[0]} - {format % args}")

    def _send(self, code, body, content_type=None):
        if isinstance(body, bytes):
            body_str = body.decode("utf-8", errors="replace")
        else:
            body_str = str(body)

        if content_type is None:
            if code >= 400 or not body_str.strip().startswith("<?xml"):
                content_type = "text/plain; charset=utf-8"
            else:
                content_type = "application/rss+xml; charset=utf-8"

        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body_str.encode("utf-8"))

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # ---- 健康检查 ----
        if path == "/health":
            self._send(
                200,
                json.dumps({
                    "status": "ok",
                    "cache_size": len(_cache),
                    "auth_configured": bool(
                        os.environ.get("TWITTER_AUTH_TOKEN")
                    ),
                }),
                "application/json",
            )
            return

        # ---- 首页 ----
        if path == "" or path == "/":
            self._send(
                200,
                json.dumps({
                    "service": "Twitter RSS Bridge",
                    "routes": ["/twitter/user/:username"],
                    "auth_configured": bool(
                        os.environ.get("TWITTER_AUTH_TOKEN")
                    ),
                }),
                "application/json",
            )
            return

        # ---- Twitter 用户 RSS ----
        if path.startswith("/twitter/user/") or path.startswith("/twitter/"):
            parts = path.split("/")
            username = parts[-1] if parts[-1] else parts[-2]
            if not username:
                self._send(400, "缺少用户名")
                return

            cache_key = f"twitter:{username}"
            cached = cache_get(cache_key)
            if cached:
                self._send(200, cached)
                return

            if not self.client:
                self._send(503, "Twitter 客户端未初始化，请检查 TWITTER_AUTH_TOKEN")
                return

            try:
                user = self.client.get_user_by_screen_name(username)
                if not user:
                    self._send(502, f"无法找到用户 @{username}")
                    return

                user_id = user.get("rest_id") or user.get("id_str")
                screen_name = user.get("screen_name") or user.get("legacy", {}).get("screen_name", username)
                user_name = user.get("name") or user.get("legacy", {}).get("name", username)
                profile_url = f"https://x.com/{screen_name}"

                tweets = self.client.get_user_tweets(user_id, count=40)
                if not tweets:
                    self._send(502, f"无法获取 @{username} 的推文")
                    return

                items = []
                for tweet in tweets:
                    pub_date = parse_twitter_date(tweet.get("created_at", ""))
                    text = tweet.get("text", "")
                    # 截断过长文本
                    if len(text) > 300:
                        text = text[:300] + "..."
                    
                    # 使用从用户查询中获取的 screen_name 修复链接
                    tweet_sn = tweet.get("screen_name") or screen_name
                    tweet_id = tweet.get("id", "")
                    tweet_link = tweet.get("link") or f"https://x.com/{screen_name}/status/{tweet_id}"
                    if "//status/" in tweet_link:
                        tweet_link = f"https://x.com/{screen_name}/status/{tweet_id}"

                    items.append({
                        "title": f"{tweet['user_name']}: {text[:100]}",
                        "link": tweet_link,
                        "description": text,
                        "pubDate": pub_date,
                    })

                rss = build_rss(
                    f"X/Twitter - @{screen_name}",
                    profile_url,
                    f"@{screen_name} 的推文 RSS",
                    items,
                )
                cache_set(cache_key, rss)
                logger.info(f"返回 @{username} 的 RSS ({len(items)} 条)")
                self._send(200, rss)
                return

            except Exception as e:
                logger.error(f"处理 @{username} 失败: {e}")
                self._send(502, f"获取失败: {e}")
                return

        # ---- 404 ----
        self._send(404, json.dumps({"error": "未知路由", "path": path}), "application/json")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=3000)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()

    auth_token = os.environ.get("TWITTER_AUTH_TOKEN", "").strip()
    ct0 = os.environ.get("TWITTER_CT0", "").strip()

    if auth_token:
        logger.info("正在初始化 Twitter 客户端...")
        try:
            TwitterBridgeHandler.client = TwitterClient(
                auth_token=auth_token,
                ct0=ct0 if ct0 else None,
            )
            logger.info("Twitter 客户端初始化成功")
        except Exception as e:
            logger.error(f"Twitter 客户端初始化失败: {e}")
            TwitterBridgeHandler.client = None
    else:
        logger.warning("=" * 60)
        logger.warning("⚠️  未配置 TWITTER_AUTH_TOKEN 环境变量！")
        logger.warning("   请设置环境变量后重新启动:")
        logger.warning("   set TWITTER_AUTH_TOKEN=你的token值")
        logger.warning("   python twitter_bridge.py --port 3000")
        logger.warning("=" * 60)
        TwitterBridgeHandler.client = None

    server = ThreadingHTTPServer((args.host, args.port), TwitterBridgeHandler)
    logger.info(f"🚀 Twitter RSS Bridge 已启动: http://{args.host}:{args.port}")
    logger.info(f"  路由: /twitter/user/:username")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("已停止")


if __name__ == "__main__":
    main()
