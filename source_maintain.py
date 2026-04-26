# source_maintain.py
import time
import random
import requests
import yaml
from collections import defaultdict
from fake_useragent import UserAgent
import json

# ---------- 健康管理器 ----------
class SourceHealth:
    def __init__(self, max_fails=3, cooldown_minutes=10):
        self.max_fails = max_fails
        self.cooldown = cooldown_minutes * 60
        self.fail_counts = defaultdict(int)
        self.disabled_until = {}
        self.on_disable = None   # 回调函数：禁用时告警
        self.on_recover = None

    def record_fail(self, source_name):
        self.fail_counts[source_name] += 1
        if self.fail_counts[source_name] >= self.max_fails:
            self.disabled_until[source_name] = time.time() + self.cooldown
            if self.on_disable:
                self.on_disable(source_name)

    def record_success(self, source_name):
        if source_name in self.disabled_until:
            if self.on_recover:
                self.on_recover(source_name)
        self.fail_counts[source_name] = 0
        self.disabled_until.pop(source_name, None)

    def is_disabled(self, source_name):
        if source_name not in self.disabled_until:
            return False
        if time.time() > self.disabled_until[source_name]:
            del self.disabled_until[source_name]
            self.fail_counts[source_name] = 0
            return False
        return True

# ---------- 镜像池 ----------
class MirrorPool:
    def __init__(self, urls):
        self.original_urls = list(urls)
        self.available = list(urls)

    def get_next_mirror(self):
        if not self.available:
            # 全部耗尽时提示并重置
            print('[WARN] 所有镜像均已失败，重置池并重试')
            self.available = list(self.original_urls)
        url = self.available.pop(0)
        return url

    def report_failure(self, url):
        if url in self.available:
            self.available.remove(url)

    def report_success(self, url):
        # 成功后可选放回，这里保持轮转避免热故障
        pass

# ---------- 稳健抓取器 ----------
class RobustFetcher:
    def __init__(self, max_retries=2, timeout=15, extra_headers=None):
        self.ua = UserAgent()
        self.session = requests.Session()
        self.max_retries = max_retries
        self.timeout = timeout
        self.extra_headers = extra_headers or {}

    def fetch(self, url, proxies=None):
        headers = {
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml',
            'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        }
        headers.update(self.extra_headers)
        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.get(url, headers=headers,
                                        proxies=proxies, timeout=self.timeout)
                resp.raise_for_status()
                if len(resp.text) < 200:
                    raise ValueError("empty content")
                return resp
            except Exception as e:
                if attempt == self.max_retries:
                    raise
                time.sleep(random.uniform(1, 3) * (attempt + 1))
        return None

# ---------- 配置文件加载（兼容原信源列表） ----------
def load_sources(config_file='sources.yaml'):
    """加载信源配置，若无 YAML 文件则使用默认硬编码列表（兼容旧版）"""
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
            return data['sources']
    except Exception:
        print('[INFO] sources.yaml 不存在，使用内置默认信源')
        # 原项目中的信源列表（示例）
        return {
            'bbc': {'type': 'rss', 'urls': ['http://feeds.bbci.co.uk/news/rss.xml']},
            'dw': {'type': 'rss', 'urls': ['https://rss.dw.com/rdf/rss-en-all']},
            'rfi_cn': {'type': 'web', 'urls': ['https://www.rfi.fr/cn/']},
        }

# ---------- AI 自动修复（需要时启用） ----------
class AIAutoHeal:
    def __init__(self, model="gpt-4o-mini", api_key=None):
        self.model = model
        self.api_key = api_key
        # 简单存储成功案例，避免重复调用LLM
        self.fix_history = {}

    def diagnose(self, source_name, url, error, response_text=None, last_good_snippet=None, consecutive_fails=0):
        """调用LLM分析故障，返回修复方案字典或None"""
        # 实际调用LLM的代码，这里用模拟代替
        # 你需要根据实际使用的AI接口实现（如 openai）
        prompt = f"""
        信源 {source_name} 连续失败{consecutive_fails}次。
        URL: {url}
        错误: {type(error).__name__}: {str(error)[:200]}
        响应片段: {response_text[:1000] if response_text else '无'}
        上次成功片段: {last_good_snippet[:500] if last_good_snippet else '无'}
        请输出JSON修复方案。
        """
        # 模拟返回（实际需调用你的AI函数）
        return {
            "diagnosis": "RSS地址可能已变更",
            "fix_type": "url_change",
            "suggested_url": "https://新的地址/rss.xml",
            "suggested_headers": {},
            "parse_rule_change": None,
            "confidence": 0.7
        }

    def apply_plan(self, plan):
        """根据修复计划临时修改信源配置（需与配置管理联动）"""
        # 这里仅做演示，实际需要更新 sources 字典
        print(f"[AUTOHEAL] 应用修复: {plan['fix_type']}")
        return True
