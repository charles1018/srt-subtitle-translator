import asyncio
import json
import re
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, ClassVar

import aiohttp
import tiktoken

# 嘗試導入 OpenAI 客戶端
try:
    from openai import AsyncOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# 嘗試導入 Google GenAI 客戶端
try:
    from google import genai

    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

# 從本地模組導入
from srt_translator.core.cache import CacheManager
from srt_translator.core.prompt import PromptManager
from srt_translator.utils.errors import TranslationError, ValidationError
from srt_translator.utils.logging_config import setup_logger
from srt_translator.utils.post_processor import NetflixStylePostProcessor

# 使用集中化日誌配置
logger = setup_logger(__name__, "srt_translator.log")


# 定義 API 錯誤類型
class ApiErrorType(Enum):
    """LLM API 呼叫的錯誤分類

    用於分類 API 失敗的原因，便於區分不同的失敗場景並實施相應的重試策略。

    屬性:
        RATE_LIMIT: API 請求頻率限制
        TIMEOUT: API 回應超時
        CONNECTION: 網路連線失敗
        SERVER: API 伺服器錯誤
        AUTHENTICATION: API 金鑰或認證失敗
        CONTENT_FILTER: 內容被 API 安全過濾器攔截
        UNKNOWN: 未知錯誤類型
    """

    RATE_LIMIT = "rate_limit"
    TIMEOUT = "timeout"
    CONNECTION = "connection"
    SERVER = "server"
    AUTHENTICATION = "authentication"
    CONTENT_FILTER = "content_filter"
    UNKNOWN = "unknown"


@dataclass
class ApiMetrics:
    """API 使用量和效能指標"""

    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    total_tokens: int = 0
    total_cost: float = 0
    cache_hits: int = 0
    total_response_time: float = 0

    def get_average_response_time(self) -> float:
        """計算平均回應時間

        回傳:
            float: 平均回應時間（秒），無成功請求時回傳 0
        """
        if self.successful_requests == 0:
            return 0
        return self.total_response_time / self.successful_requests

    def get_success_rate(self) -> float:
        """計算請求成功率

        回傳:
            float: 成功率百分比（0-100），無請求時回傳 0
        """
        if self.total_requests == 0:
            return 0
        return (self.successful_requests / self.total_requests) * 100

    def get_cache_hit_rate(self) -> float:
        """計算快取命中率

        回傳:
            float: 快取命中率百分比（0-100），無請求時回傳 0
        """
        if self.total_requests == 0:
            return 0
        return (self.cache_hits / self.total_requests) * 100

    def get_summary(self) -> dict[str, Any]:
        """生成效能指標摘要

        回傳:
            dict: 包含所有主要指標的字典，格式化為易讀的字符串
        """
        return {
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": f"{self.get_success_rate():.2f}%",
            "cache_hit_rate": f"{self.get_cache_hit_rate():.2f}%",
            "average_response_time": f"{self.get_average_response_time():.2f}s",
            "total_tokens": self.total_tokens,
            "estimated_cost": f"${self.total_cost:.4f}",
        }


class AdaptiveConcurrencyController:
    """自適應並發控制器

    根據 API 回應時間動態調整並發請求數量，以優化翻譯效率。

    策略:
        - API 回應快時（< 0.5秒），增加並發數
        - API 回應慢時（> 1.5秒），降低並發數
        - 使用指數移動平均(EMA)平滑回應時間波動

    執行緒安全:
        此類別使用 asyncio.Lock 保護共享狀態，確保在並發環境中安全使用。
    """

    def __init__(self, initial: int = 3, min_concurrent: int = 2, max_concurrent: int = 10):
        """初始化並發控制器

        參數:
            initial: 初始並發數
            min_concurrent: 最小並發數
            max_concurrent: 最大並發數
        """
        self.current = initial
        self.min = min_concurrent
        self.max = max_concurrent
        self.avg_response_time = 0.8  # 初始估計值
        self.sample_count = 0
        self._lock = asyncio.Lock()  # 非同步鎖保護共享狀態

    async def update(self, response_time: float) -> int:
        """更新平均回應時間並調整並發數（執行緒安全）

        使用指數移動平均(EMA)平滑回應時間:
        - 權重: 90% 歷史 + 10% 新樣本

        參數:
            response_time: API 回應時間(秒)

        回傳:
            調整後的並發數
        """
        async with self._lock:
            # 使用 EMA 更新平均回應時間
            alpha = 0.1  # 新樣本權重
            self.avg_response_time = (1 - alpha) * self.avg_response_time + alpha * response_time
            self.sample_count += 1

            # 根據平均回應時間調整並發數
            if self.avg_response_time < 0.5 and self.current < self.max:
                # 回應快，增加並發
                self.current = min(self.current + 1, self.max)
                logger.debug(
                    f"並發數增加: {self.current - 1} -> {self.current} (平均回應時間: {self.avg_response_time:.2f}s)"
                )
            elif self.avg_response_time > 1.5 and self.current > self.min:
                # 回應慢，降低並發
                self.current = max(self.current - 1, self.min)
                logger.debug(
                    f"並發數降低: {self.current + 1} -> {self.current} (平均回應時間: {self.avg_response_time:.2f}s)"
                )

            return self.current

    def get_current(self) -> int:
        """獲取當前並發數（快速讀取，無鎖）

        注意: 此方法不使用鎖，適用於不需要精確值的場景（如日誌記錄）。
        在並發環境中，返回值可能略微過時。

        回傳:
            當前並發數
        """
        return self.current

    async def get_stats(self) -> dict[str, Any]:
        """獲取統計資訊（執行緒安全）

        回傳:
            統計資訊字典
        """
        async with self._lock:
            return {
                "current_concurrency": self.current,
                "min_concurrency": self.min,
                "max_concurrency": self.max,
                "avg_response_time": f"{self.avg_response_time:.2f}s",
                "sample_count": self.sample_count,
            }


class TranslationClient:
    JAPANESE_NAME_PLACEHOLDER_PREFIX: ClassVar[str] = "JN"
    JAPANESE_NAME_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:(?<=^)|(?<=[、，。！？!?「」（）『』\s]))"
        r"(([ァ-ヶー]{2,10}|[ぁ-ゖーっ]{2,10})(?:ちゃん|くん|君|さん|さま|様|先輩|先生|氏))"
        r"(?=$|[、，。！？!?」』\s]|の|が|を|に|へ|と|も|は)"
    )
    JAPANESE_KANA_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[ぁ-ゖァ-ヺー]")
    JAPANESE_HIRAGANA_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[ぁ-ゖ]")
    CJK_IDEOGRAPH_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"[一-龯々〆ヵヶ]")
    JAPANESE_PLACEHOLDER_PATTERN: ClassVar[re.Pattern[str]] = re.compile(r"\[\[[A-Z0-9]+\]\]")
    LEAKED_JAPANESE_PLACEHOLDER_PATTERN: ClassVar[re.Pattern[str]] = re.compile(
        r"(?:\[\[\s*JN\d+\s*\]\]|\[\s*JN\d+\s*\]|(?<![A-Z0-9_])JN\d+(?![A-Z0-9_]))"
    )
    UNTRANSLATED_JAPANESE_RETRY_INSTRUCTION: ClassVar[str] = (
        "CRITICAL RETRY INSTRUCTION:\n"
        "The previous output still contained untranslated Japanese.\n"
        "You MUST translate the CURRENT subtitle into Traditional Chinese (Taiwan).\n"
        "Do not leave hiragana or katakana in the final answer unless it is a protected placeholder like [[JN0]].\n"
        "Return only the translated subtitle text."
    )
    LLAMACPP_TRANSLATION_RESPONSE_FORMAT: ClassVar[dict[str, Any]] = {
        "type": "json_schema",
        "schema": {
            "type": "object",
            "properties": {
                "translation": {
                    "type": "string",
                    "description": "Translated subtitle text only.",
                }
            },
            "required": ["translation"],
            "additionalProperties": False,
        },
    }
    OLLAMA_MODEL_PROFILES: ClassVar[dict[str, dict[str, Any]]] = {
        "default": {
            "keep_alive": "10m",
            "batch_concurrency_limit": None,
            "options": {
                "temperature": 0.1,
                "num_predict": 256,
            },
        },
        "qwen3": {
            "keep_alive": "15m",
            "batch_concurrency_limit": 1,
            "options": {
                "temperature": 0.7,
                "top_p": 0.8,
                "top_k": 20,
                "min_p": 0.0,
                "num_predict": 256,
            },
        },
        "qwen3.5": {
            "keep_alive": "15m",
            "batch_concurrency_limit": 1,
            "options": {
                "temperature": 1.0,
                "top_p": 1.0,
                "top_k": 20,
                "min_p": 0.0,
                "num_predict": 256,
            },
        },
        "qwen3.5-ud": {
            "keep_alive": "15m",
            "batch_concurrency_limit": 1,
            "options": {
                "temperature": 0.85,
                "top_p": 1.0,
                "top_k": 20,
                "min_p": 0.0,
                "num_predict": 96,
            },
        },
    }
    _LLAMACPP_FALLBACK_SLOTS: ClassVar[int] = 2

    LLAMACPP_MODEL_PROFILES: ClassVar[dict[str, dict[str, Any]]] = {
        "default": {
            "batch_concurrency_limit": None,
            "options": {
                "temperature": 0.1,
                "max_tokens": 256,
            },
            "extra_body": {
                "cache_prompt": True,
                "reasoning_format": "deepseek",
                "reasoning_budget_tokens": 0,
                "seed": 42,
                "chat_template_kwargs": {"enable_thinking": False},
            },
        },
        "qwen3": {
            "batch_concurrency_limit": 1,
            "options": {
                "temperature": 0.7,
                "top_p": 0.8,
                "max_tokens": 256,
            },
            "extra_body": {
                "presence_penalty": 1.5,
                "top_k": 20,
                "min_p": 0.0,
            },
        },
        "qwen3.5": {
            "batch_concurrency_limit": 1,
            "options": {
                "temperature": 1.0,
                "top_p": 1.0,
                "max_tokens": 256,
            },
            "extra_body": {
                "presence_penalty": 2.0,
                "top_k": 20,
                "min_p": 0.0,
            },
        },
        "qwen3.5-ud": {
            "batch_concurrency_limit": None,
            "options": {
                "temperature": 0.85,
                "top_p": 1.0,
                "max_tokens": 96,
            },
            "extra_body": {
                "presence_penalty": 2.0,
                "top_k": 20,
                "min_p": 0.0,
            },
        },
    }

    def __init__(
        self,
        llm_type: str,
        base_url: str = "http://localhost:11434",
        api_key: str | None = None,
        cache_db_path: str = "data/translation_cache.db",
        netflix_style_config: dict[str, Any] | None = None,
    ):
        """
        初始化翻譯客戶端

        參數:
            llm_type: LLM 類型 ('ollama', 'openai' 或 'google')
            base_url: API 基礎 URL
            api_key: API 金鑰 (用於 OpenAI, Anthropic, Google)
            cache_db_path: 快取資料庫路徑
            netflix_style_config: Netflix 風格配置（可選）
                - enabled: 是否啟用 Netflix 風格後處理（預設: False）
                - auto_fix: 是否自動修正格式問題（預設: True）
                - strict_mode: 是否使用嚴格模式（預設: False）
                - max_chars_per_line: 每行最大字符數（預設: 16）
                - max_lines: 最多行數（預設: 2）
        """
        self.llm_type = llm_type
        if llm_type == "ollama":
            self.base_url = base_url.rstrip("/")
        elif llm_type == "llamacpp":
            normalized_base_url = (base_url or "http://localhost:8080").rstrip("/")
            if normalized_base_url.endswith("/v1"):
                normalized_base_url = normalized_base_url[:-3]
            self.base_url = normalized_base_url
        elif llm_type == "google":
            self.base_url = "https://generativelanguage.googleapis.com"
        else:
            self.base_url = "https://api.openai.com/v1"
        self.cache_manager = CacheManager(cache_db_path)
        self.prompt_manager = PromptManager()
        self.session = None
        self.api_key = api_key
        self.metrics = ApiMetrics()
        self._llamacpp_server_diagnostics: dict[str, Any] | None = None
        self._llamacpp_server_diagnostics_timestamp = 0.0
        self._llamacpp_server_diagnostics_ttl = 30.0

        # 連線池設定
        self.conn_limit = 10  # 最大連線數
        self.conn_timeout = aiohttp.ClientTimeout(
            total=120,  # 總逾時（大型本地模型首次載入可能需要較長時間）
            connect=10,  # 連線逾時
            sock_connect=10,  # Socket 連線逾時
            sock_read=90,  # Socket 讀取逾時（本地模型推理可能較慢）
        )

        # 回退機制設定
        self.fallback_models = {
            "openai": {"gpt-4": ["gpt-3.5-turbo"], "gpt-4-turbo": ["gpt-4", "gpt-3.5-turbo"], "gpt-3.5-turbo": []},
            "ollama": {
                "llama3.2": ["qwen3", "gemma3"],
                "qwen3.5": ["qwen3", "llama3.2", "gemma3"],
                "qwen3": ["llama3.2", "gemma3"],
                "gemma3": ["llama3.2", "qwen3"],
                "mistral": ["llama3.2", "qwen3"],
            },
            "google": {
                "gemini-2.5-pro": ["gemini-2.5-flash", "gemini-2.0-flash"],
                "gemini-2.5-flash": ["gemini-2.0-flash", "gemini-1.5-flash"],
                "gemini-2.0-flash": ["gemini-1.5-flash"],
                "gemini-1.5-pro": ["gemini-1.5-flash"],
                "gemini-1.5-flash": [],
            },
            "llamacpp": {},  # llama-server 只載入單一模型，無需回退
        }

        # Google Gemini 客戶端
        self.google_client = None
        if llm_type == "google":
            if not GOOGLE_AVAILABLE:
                logger.error("未安裝 Google GenAI 客戶端函式庫，Google 模式不可用")
                raise ImportError("請安裝 Google GenAI Python 套件: pip install google-genai")

            self.google_client = genai.Client(api_key=api_key)
            logger.info("Google Gemini 客戶端已初始化")

            # Google 模型價格計算（每百萬 token）
            self.pricing = {
                "gemini-2.0-flash": {"input": 0.0, "output": 0.0},  # 免費
                "gemini-2.5-flash": {"input": 0.00000015, "output": 0.0000006},
                "gemini-2.5-pro": {"input": 0.00000125, "output": 0.000005},
                "gemini-1.5-flash": {"input": 0.000000075, "output": 0.0000003},
                "gemini-1.5-pro": {"input": 0.00000125, "output": 0.000005},
            }

        # llama.cpp 客戶端（透過 OpenAI 相容 API）
        elif llm_type == "llamacpp":
            if not OPENAI_AVAILABLE:
                logger.error("未安裝 OpenAI 客戶端函式庫，llama.cpp 模式需要 openai 套件")
                raise ImportError("請安裝 OpenAI Python 套件: pip install openai")

            # 本地推理可能較慢（尤其 CPU-only 或思考模型），設定較長逾時
            llamacpp_timeout = 600  # 10 分鐘
            self.openai_client: AsyncOpenAI | None = AsyncOpenAI(
                base_url=f"{self.base_url}/v1",
                api_key="sk-no-key-required",  # llama-server 預設無需認證
                timeout=llamacpp_timeout,
                max_retries=1,  # 本地模型重試意義不大
            )
            # llamacpp 不需要速率限制，但需要 token_usage 屬性以相容 OpenAI 路徑
            self.request_timestamps: list[float] = []
            self.token_usage: list[tuple[float, int]] = []
            self.pricing: dict[str, dict[str, float]] = {}

            logger.info(f"llama.cpp 客戶端已初始化，連線至 {self.base_url}（逾時: {llamacpp_timeout}s）")

        # OpenAI 客戶端最佳化
        elif llm_type == "openai":
            if not OPENAI_AVAILABLE:
                logger.error("未安裝 OpenAI 客戶端函式庫，OpenAI 模式不可用")
                raise ImportError("請安裝 OpenAI Python 套件: pip install openai")

            self.openai_client: AsyncOpenAI | None = AsyncOpenAI(api_key=api_key, timeout=self.conn_timeout.total)

            # 為各模型載入適當的 tokenizer
            self.tokenizers: dict[str, Any] = {}
            self._load_tokenizers()

            # 速率限制追蹤
            self.request_timestamps: list[float] = []  # 用於追蹤 API 請求時間
            self.max_requests_per_minute = 3500  # OpenAI API 預設限制
            self.max_tokens_per_minute = 180000  # OpenAI API 預設限制
            self.token_usage: list[tuple[float, int]] = []  # 用於追蹤 token 使用量

            # 價格計算
            self.pricing = {
                "gpt-3.5-turbo": {"input": 0.0000005, "output": 0.0000015},  # $0.0005 / 1K input, $0.0015 / 1K output
                "gpt-4": {"input": 0.00003, "output": 0.00006},  # $0.03 / 1K input, $0.06 / 1K output
                "gpt-4-turbo": {"input": 0.00001, "output": 0.00003},  # $0.01 / 1K input, $0.03 / 1K output
            }
        else:
            self.openai_client = None

        # Netflix 風格後處理器（可選功能）
        netflix_config = netflix_style_config or {}
        self.enable_netflix_style = netflix_config.get("enabled", False)
        self.post_processor = None

        if self.enable_netflix_style:
            try:
                self.post_processor = NetflixStylePostProcessor(
                    auto_fix=netflix_config.get("auto_fix", True),
                    strict_mode=netflix_config.get("strict_mode", False),
                    max_chars_per_line=netflix_config.get("max_chars_per_line", 16),
                    max_lines=netflix_config.get("max_lines", 2),
                )
                logger.info("Netflix 風格後處理器已啟用")
            except Exception as e:
                logger.warning(f"無法初始化 Netflix 風格後處理器: {e}，功能已停用")
                self.enable_netflix_style = False
                self.post_processor = None

        # 自適應並發控制器
        self.concurrency_controller = AdaptiveConcurrencyController(initial=3, min_concurrent=2, max_concurrent=10)
        logger.info(f"自適應並發控制器已啟用: 初始並發數={self.concurrency_controller.get_current()}")

    def _detect_ollama_model_family(self, model_name: str) -> str:
        """根據模型名稱偵測 Ollama 模型家族"""
        normalized = self._normalize_model_name(model_name)

        if re.search(r"qwen(?:[-_/\s]?3\.5|35)", normalized):
            return "qwen3.5"
        if re.search(r"qwen[-_/\s]?3\b", normalized):
            return "qwen3"
        if "qwen" in normalized:
            return "qwen"
        if "llama" in normalized:
            return "llama"
        if "gemma" in normalized:
            return "gemma"
        if "mistral" in normalized:
            return "mistral"
        return "default"

    def _normalize_model_name(self, model_name: str) -> str:
        """標準化模型名稱，便於做家族與變體判斷"""
        normalized = model_name.strip().lower()
        return normalized.split("@", maxsplit=1)[0]

    def _is_qwen35_ud_model(self, model_name: str) -> bool:
        """判斷是否為 qwen3.5-ud 變體"""
        if self._detect_ollama_model_family(model_name) != "qwen3.5":
            return False

        normalized = self._normalize_model_name(model_name)
        tokens = [token for token in re.split(r"[^a-z0-9]+", normalized) if token]
        return "ud" in tokens

    @staticmethod
    def _dedupe_preserve_order(values: list[str]) -> list[str]:
        """去除重複項目並保留原始順序"""
        deduped: list[str] = []
        seen = set()

        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            deduped.append(normalized)

        return deduped

    def _get_qwen35_ud_fallback_candidates(self, model_name: str) -> list[str]:
        """取得 qwen3.5-ud 的優先回退候選模型"""
        if not self._is_qwen35_ud_model(model_name):
            return []

        tag = ""
        if ":" in model_name:
            tag = model_name.split(":", maxsplit=1)[1].strip()

        candidates = []
        if tag:
            candidates.append(f"qwen3.5-uncensored:{tag}")

        candidates.extend(["qwen3.5-uncensored:latest", "qwen3.5-uncensored"])
        candidates = [candidate for candidate in candidates if candidate != model_name]
        return self._dedupe_preserve_order(candidates)

    def _get_ollama_model_profile(self, model_name: str) -> dict[str, Any]:
        """取得 Ollama 模型的請求設定"""
        family = self._detect_ollama_model_family(model_name)
        profile_key = "qwen3.5-ud" if self._is_qwen35_ud_model(model_name) else family
        default_profile = self.OLLAMA_MODEL_PROFILES["default"]
        family_profile = self.OLLAMA_MODEL_PROFILES.get(profile_key, {})

        return {
            "family": family,
            "profile": profile_key,
            "keep_alive": family_profile.get("keep_alive", default_profile["keep_alive"]),
            "batch_concurrency_limit": family_profile.get("batch_concurrency_limit"),
            "options": {
                **default_profile["options"],
                **family_profile.get("options", {}),
            },
        }

    def _get_llamacpp_model_profile(self, model_name: str) -> dict[str, Any]:
        """取得 llama.cpp 模型的請求設定"""
        family = self._detect_ollama_model_family(model_name)
        profile_key = "qwen3.5-ud" if self._is_qwen35_ud_model(model_name) else family
        default_profile = self.LLAMACPP_MODEL_PROFILES["default"]
        family_profile = self.LLAMACPP_MODEL_PROFILES.get(profile_key, {})

        extra_body = {
            **default_profile.get("extra_body", {}),
            **family_profile.get("extra_body", {}),
        }
        default_chat_template_kwargs = default_profile.get("extra_body", {}).get("chat_template_kwargs", {})
        family_chat_template_kwargs = family_profile.get("extra_body", {}).get("chat_template_kwargs", {})
        if default_chat_template_kwargs or family_chat_template_kwargs:
            extra_body["chat_template_kwargs"] = {
                **default_chat_template_kwargs,
                **family_chat_template_kwargs,
            }

        return {
            "family": family,
            "profile": profile_key,
            "batch_concurrency_limit": family_profile.get("batch_concurrency_limit"),
            "options": {
                **default_profile["options"],
                **family_profile.get("options", {}),
            },
            "extra_body": extra_body,
        }

    def _get_llamacpp_server_root_url(self) -> str:
        """取得 llama.cpp server 根 URL（不含 /v1 前綴）"""
        base_url = self.base_url.rstrip("/")
        if base_url.endswith("/v1"):
            return base_url[:-3]
        return base_url

    def _build_llamacpp_server_url(self, path: str) -> str:
        """組合 llama.cpp server 管理端 URL"""
        return f"{self._get_llamacpp_server_root_url()}{path}"

    async def _get_llamacpp_server_diagnostics(self, force_refresh: bool = False) -> dict[str, Any]:
        """查詢 llama.cpp server 健康狀態與可用 slots"""
        if self.llm_type != "llamacpp":
            return {}

        now = time.time()
        if (
            not force_refresh
            and self._llamacpp_server_diagnostics is not None
            and now - self._llamacpp_server_diagnostics_timestamp < self._llamacpp_server_diagnostics_ttl
        ):
            return self._llamacpp_server_diagnostics

        diagnostics: dict[str, Any] = {
            "available": False,
            "total_slots": None,
            "slot_n_ctx": None,
            "model_path": "",
            "is_sleeping": False,
            "slots_endpoint_available": None,
        }

        session = self.session
        should_close_session = False

        if session is None:
            timeout = aiohttp.ClientTimeout(total=5, connect=3, sock_connect=3, sock_read=5)
            session = aiohttp.ClientSession(timeout=timeout)
            should_close_session = True

        try:
            health_url = self._build_llamacpp_server_url("/health")
            async with session.get(health_url, timeout=5) as response:
                diagnostics["available"] = response.status == 200
                if response.status != 200:
                    logger.debug(f"llama.cpp /health 狀態異常: {response.status}")
                    return diagnostics

            props_url = self._build_llamacpp_server_url("/props")
            try:
                async with session.get(props_url, timeout=5) as response:
                    if response.status == 200:
                        props = await response.json()
                        if isinstance(props, dict):
                            total_slots = props.get("total_slots")
                            if isinstance(total_slots, int) and total_slots > 0:
                                diagnostics["total_slots"] = total_slots

                            default_settings = props.get("default_generation_settings", {})
                            if isinstance(default_settings, dict):
                                slot_n_ctx = default_settings.get("n_ctx")
                                if isinstance(slot_n_ctx, int) and slot_n_ctx > 0:
                                    diagnostics["slot_n_ctx"] = slot_n_ctx

                            model_path = props.get("model_path", "")
                            if isinstance(model_path, str):
                                diagnostics["model_path"] = model_path

                            diagnostics["is_sleeping"] = bool(props.get("is_sleeping", False))
            except Exception as e:
                logger.debug(f"讀取 llama.cpp /props 失敗，將改用其他端點補足資訊: {e!s}")

            slots_url = self._build_llamacpp_server_url("/slots")
            try:
                async with session.get(slots_url, timeout=5) as response:
                    if response.status == 200:
                        slots_payload = await response.json()
                        diagnostics["slots_endpoint_available"] = True
                        if isinstance(slots_payload, list):
                            if diagnostics["total_slots"] is None and slots_payload:
                                diagnostics["total_slots"] = len(slots_payload)
                            if (
                                diagnostics["slot_n_ctx"] is None
                                and slots_payload
                                and isinstance(slots_payload[0], dict)
                            ):
                                slot_n_ctx = slots_payload[0].get("n_ctx")
                                if isinstance(slot_n_ctx, int) and slot_n_ctx > 0:
                                    diagnostics["slot_n_ctx"] = slot_n_ctx
                    elif response.status == 501:
                        diagnostics["slots_endpoint_available"] = False
                    else:
                        logger.debug(f"llama.cpp /slots 狀態異常: {response.status}")
            except Exception as e:
                logger.debug(f"讀取 llama.cpp /slots 失敗: {e!s}")
        except Exception as e:
            logger.debug(f"探測 llama.cpp server 診斷資訊失敗: {e!s}")
        finally:
            if should_close_session and session is not None:
                await session.close()

        self._llamacpp_server_diagnostics = diagnostics
        self._llamacpp_server_diagnostics_timestamp = time.time()
        return diagnostics

    def _should_apply_qwen35_ud_runtime_guards(self, model_name: str) -> bool:
        """判斷是否應啟用 qwen3.5-ud 成人字幕的額外保護機制。"""
        return (
            self.llm_type in {"ollama", "llamacpp"}
            and self._is_qwen35_ud_model(model_name)
            and getattr(self.prompt_manager, "current_content_type", "") == "adult"
        )

    @classmethod
    def _extract_japanese_name_candidates(cls, text: str) -> list[str]:
        """提取需要保護的日文人名或暱稱。"""
        candidates = [match.group(1) for match in cls.JAPANESE_NAME_PATTERN.finditer(text)]
        if not candidates:
            return []

        # 先保留較長的完整稱呼，避免部分名稱先被替換。
        return sorted(cls._dedupe_preserve_order(candidates), key=len, reverse=True)

    def _protect_japanese_names_in_inputs(
        self, text: str, context_texts: list[str]
    ) -> tuple[str, list[str], dict[str, str]]:
        """將日文人名替換為暫時占位符，避免模型自行翻譯名字。"""
        candidates = self._extract_japanese_name_candidates(text)
        if not candidates:
            return text, context_texts, {}

        protected_text = text
        protected_contexts = list(context_texts)
        restore_map: dict[str, str] = {}

        for index, candidate in enumerate(candidates):
            placeholder = f"[[{self.JAPANESE_NAME_PLACEHOLDER_PREFIX}{index}]]"
            restore_map[placeholder] = candidate
            protected_text = protected_text.replace(candidate, placeholder)
            protected_contexts = [context.replace(candidate, placeholder) for context in protected_contexts]

        logger.debug("qwen3.5-ud 啟用日文名字保護: %s", restore_map)
        return protected_text, protected_contexts, restore_map

    @classmethod
    def _restore_protected_japanese_names(cls, translation: str, restore_map: dict[str, str]) -> str:
        """還原模型輸出中的日文名字占位符。"""
        restored = translation

        for placeholder, original in restore_map.items():
            inner_token = placeholder[2:-2]
            tolerant_pattern = re.compile(
                rf"(?<![A-Z0-9_])(?:\[\[\s*{re.escape(inner_token)}\s*\]\]|\[\s*{re.escape(inner_token)}\s*\]|{re.escape(inner_token)})(?![A-Z0-9_])"
            )
            restored = tolerant_pattern.sub(original, restored)

        return restored

    @classmethod
    def _remove_japanese_retry_exempt_tokens(cls, text: str, source_text: str) -> str:
        """移除日文未翻譯檢測中允許保留的占位符與人名。"""
        cleaned = cls.JAPANESE_PLACEHOLDER_PATTERN.sub("", text)

        for candidate in cls._extract_japanese_name_candidates(source_text):
            cleaned = cleaned.replace(candidate, "")

        return cleaned

    @staticmethod
    def _normalize_text_for_translation_comparison(text: str) -> str:
        """正規化文字，便於比對是否幾乎原樣回傳。"""
        return re.sub(r"[\s、，。．！？!?…・「」『』（）()【】［］\[\]<>《》〈〉〜～\-—_\"'`]+", "", text)

    @classmethod
    def _should_retry_untranslated_japanese(cls, source_text: str, translated_text: str) -> bool:
        """判斷翻譯結果是否仍包含明顯未翻譯的日文。"""
        cleaned_source = cls._remove_japanese_retry_exempt_tokens(source_text, source_text)
        cleaned_translation = cls._remove_japanese_retry_exempt_tokens(translated_text, source_text)

        source_has_cjk = bool(cls.CJK_IDEOGRAPH_PATTERN.search(cleaned_source))
        source_kana = len(cls.JAPANESE_KANA_PATTERN.findall(cleaned_source))
        translation_kana = len(cls.JAPANESE_KANA_PATTERN.findall(cleaned_translation))
        translation_hiragana = len(cls.JAPANESE_HIRAGANA_PATTERN.findall(cleaned_translation))

        if not cleaned_translation.strip():
            return False

        if source_kana == 0 and not source_has_cjk:
            return False

        # 正常的繁中輸出不應殘留任何平假名；這裡先用最穩定的訊號攔截。
        if translation_hiragana >= 1:
            return True

        if source_kana >= 1 and translation_kana >= 1:
            return True

        normalized_source = cls._normalize_text_for_translation_comparison(cleaned_source)
        normalized_translation = cls._normalize_text_for_translation_comparison(cleaned_translation)
        if not normalized_source:
            return False

        if source_kana >= 1 and normalized_translation == normalized_source:
            return True

        return bool(translation_kana >= 1 and normalized_source in normalized_translation)

    @classmethod
    def get_cache_rejection_reason(cls, source_text: str, translated_text: str) -> str | None:
        """判斷翻譯結果是否不適合直接信任或存入快取。"""
        if not translated_text.strip():
            return "empty_translation"

        if cls.LEAKED_JAPANESE_PLACEHOLDER_PATTERN.search(translated_text):
            return "leaked_name_placeholder"

        if cls._should_retry_untranslated_japanese(source_text, translated_text):
            return "untranslated_japanese"

        return None

    @classmethod
    def is_cacheable_translation_result(cls, source_text: str, translated_text: str) -> bool:
        """判斷翻譯結果是否適合寫入或直接讀取快取。"""
        return cls.get_cache_rejection_reason(source_text, translated_text) is None

    def _build_untranslated_japanese_retry_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """建立日文未翻譯時的單次強化重試訊息。"""
        retry_messages = [dict(message) for message in messages]

        for message in retry_messages:
            if message.get("role") == "system":
                base_content = message.get("content", "").rstrip()
                message["content"] = f"{base_content}\n\n{self.UNTRANSLATED_JAPANESE_RETRY_INSTRUCTION}"
                return retry_messages

        retry_messages.insert(
            0,
            {
                "role": "system",
                "content": self.UNTRANSLATED_JAPANESE_RETRY_INSTRUCTION,
            },
        )
        return retry_messages

    async def _execute_translation_request(self, messages: list[dict[str, str]], model_name: str) -> str:
        """根據 provider 執行單次翻譯請求。"""
        if self.llm_type in ("openai", "llamacpp"):
            return await self._translate_with_openai(messages, model_name)
        if self.llm_type == "ollama":
            return await self._translate_with_ollama(messages, model_name)
        if self.llm_type == "google":
            return await self._translate_with_google(messages, model_name)
        raise ValidationError(f"不支援的 LLM 類型: {self.llm_type}")

    def _build_ollama_payload(self, messages: list[dict[str, str]], model_name: str) -> dict[str, Any]:
        """建立 Ollama chat API 請求內容"""
        profile = self._get_ollama_model_profile(model_name)

        return {
            "model": model_name,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": profile["keep_alive"],
            "options": profile["options"],
        }

    def _sanitize_ollama_translation(self, translation: str) -> str:
        """清理 Ollama 回傳中常見的推理與模板殘留"""
        cleaned = translation.strip()
        cleaned = re.sub(r"(?is)<think>[\s\S]*?</think>\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?is)^<\|im_start\|>assistant\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?is)\s*<\|im_end\|>$", "", cleaned).strip()
        cleaned = cleaned.replace("<think>", "").replace("</think>", "").strip()
        return cleaned

    def _extract_llamacpp_structured_translation(self, content: str) -> str:
        """從 llama.cpp schema-constrained JSON 回應提取翻譯文字"""
        cleaned = content.strip()
        if not cleaned:
            return ""

        # 移除可能洩漏的 <think> 區塊（Qwen3.5 已知問題）
        cleaned = re.sub(r"(?is)<think>[\s\S]*?</think>\s*", "", cleaned).strip()

        # 若 JSON 前面有非 JSON 文字（reasoning 洩漏），跳到第一個 {
        json_start = cleaned.find("{")
        if json_start > 0:
            logger.debug(f"llama.cpp 結構化輸出前有 {json_start} 個多餘字元，已跳過")
            cleaned = cleaned[json_start:]

        cleaned = re.sub(r"(?is)^```json\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?is)^```\s*", "", cleaned).strip()
        cleaned = re.sub(r"(?is)\s*```$", "", cleaned).strip()

        try:
            payload = json.loads(cleaned)
        except json.JSONDecodeError:
            return cleaned

        if isinstance(payload, dict):
            translation = payload.get("translation")
            if isinstance(translation, str):
                return translation.strip()

        return cleaned

    def _get_ollama_batch_size(
        self, model_name: str, concurrent_limit: int, adaptive_concurrency: int, pending: int
    ) -> int:
        """根據模型家族調整 Ollama 批次並發數"""
        batch_size = min(concurrent_limit, adaptive_concurrency, pending)
        profile = self._get_ollama_model_profile(model_name)
        model_limit = profile.get("batch_concurrency_limit")

        if model_limit is not None:
            limited_batch_size = min(batch_size, model_limit)
            if limited_batch_size != batch_size:
                logger.info(
                    f"Ollama 模型 {model_name} ({profile['family']}) "
                    f"限制並發數為 {limited_batch_size}，原始計算值: {batch_size}"
                )
            batch_size = limited_batch_size

        return max(1, batch_size)

    async def _get_effective_batch_size(
        self,
        model_name: str,
        concurrent_limit: int,
        adaptive_concurrency: int,
        pending: int,
    ) -> int:
        """根據 provider 與 server 狀態計算實際批次並發數"""
        if self.llm_type == "ollama":
            return self._get_ollama_batch_size(model_name, concurrent_limit, adaptive_concurrency, pending)

        batch_size = min(concurrent_limit, adaptive_concurrency, pending)
        if self.llm_type != "llamacpp":
            return max(1, batch_size)

        profile = self._get_llamacpp_model_profile(model_name)
        model_limit = profile.get("batch_concurrency_limit")
        if model_limit is not None:
            limited_batch_size = min(batch_size, model_limit)
            if limited_batch_size != batch_size:
                logger.info(
                    f"llama.cpp 模型 {model_name} ({profile['family']}) "
                    f"限制並發數為 {limited_batch_size}，原始計算值: {batch_size}"
                )
            batch_size = limited_batch_size

        diagnostics = await self._get_llamacpp_server_diagnostics()
        total_slots = diagnostics.get("total_slots")
        if isinstance(total_slots, int) and total_slots > 0:
            limited_batch_size = min(batch_size, total_slots)
            if limited_batch_size != batch_size:
                logger.info(
                    f"llama.cpp server slots 限制並發數為 {limited_batch_size}，"
                    f"原始計算值: {batch_size}，總 slots: {total_slots}"
                )
            batch_size = limited_batch_size
        elif model_limit is None:
            fallback = self._LLAMACPP_FALLBACK_SLOTS
            limited_batch_size = min(batch_size, fallback)
            if limited_batch_size != batch_size:
                logger.warning(
                    f"llama.cpp server 診斷未取得 total_slots，使用安全預設值 {fallback}，原始計算值: {batch_size}"
                )
            batch_size = limited_batch_size

        return max(1, batch_size)

    def _get_fallback_models(self, model_name: str) -> list[str]:
        """取得當前模型可用的回退模型清單"""
        provider_fallbacks = self.fallback_models.get(self.llm_type, {})
        fallback_options = provider_fallbacks.get(model_name, [])

        if self.llm_type == "ollama" and self._is_qwen35_ud_model(model_name):
            family = self._detect_ollama_model_family(model_name)
            qwen35_ud_fallbacks = self._get_qwen35_ud_fallback_candidates(model_name)
            return self._dedupe_preserve_order(
                qwen35_ud_fallbacks + fallback_options + provider_fallbacks.get(family, [])
            )

        if fallback_options or self.llm_type != "ollama":
            return fallback_options

        family = self._detect_ollama_model_family(model_name)
        return provider_fallbacks.get(family, [])

    def _load_tokenizers(self):
        """載入各 OpenAI 模型的 tokenizer"""
        try:
            # 為不同模型載入適當的 tokenizer
            if "gpt-4" in self.tokenizers:
                return  # 已經載入

            models = {
                "gpt-3.5-turbo": "cl100k_base",  # 適用於 gpt-3.5-turbo 和 gpt-4
                "gpt-4": "cl100k_base",
                "gpt-4-turbo": "cl100k_base",
            }

            for model, encoding_name in models.items():
                try:
                    self.tokenizers[model] = tiktoken.encoding_for_model(model)
                except KeyError:
                    # 如果特定模型未找到，使用基礎編碼
                    self.tokenizers[model] = tiktoken.get_encoding(encoding_name)

            logger.debug(f"已載入 tokenizers: {list(self.tokenizers.keys())}")
        except Exception as e:
            logger.warning(f"載入 tokenizers 時發生錯誤: {e!s}，將使用估算方法")
            self.tokenizers = {}  # 清空，使用備用估算方法

    async def __aenter__(self):
        """使用非同步上下文管理器初始化"""
        if self.llm_type in {"ollama", "llamacpp"}:
            # 本地 provider 共用 aiohttp session 進行健康檢查與管理端探測
            connector = aiohttp.TCPConnector(
                limit=self.conn_limit,
                limit_per_host=self.conn_limit,
                ssl=False,
            )
            self.session = aiohttp.ClientSession(connector=connector, timeout=self.conn_timeout)  # type: ignore[assignment]
            logger.debug(f"初始化 aiohttp.ClientSession for {self.llm_type}，連線限制: {self.conn_limit}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同步上下文管理器清理"""
        # 關閉本地 provider session
        if self.session:
            await self.session.close()
            self.session = None
            logger.debug("關閉 aiohttp.ClientSession")

        # 關閉 OpenAI 客戶端（如果存在）
        if self.openai_client:
            try:
                await self.openai_client.close()
                logger.debug("關閉 AsyncOpenAI 客戶端")
            except Exception as e:
                logger.warning(f"關閉 OpenAI 客戶端時發生錯誤: {e!s}")
            finally:
                self.openai_client = None

        # 關閉 Google 客戶端（如果存在）
        if self.google_client:
            try:
                self.google_client.close()
                logger.debug("關閉 Google GenAI 客戶端")
            except Exception as e:
                logger.warning(f"關閉 Google 客戶端時發生錯誤: {e!s}")
            finally:
                self.google_client = None

    async def _count_tokens(self, messages: list[dict[str, str]], model: str) -> int:
        """使用正確的 tokenizer 計算 token 數量"""
        if not self.tokenizers:
            # 備用估算方法
            return await self._estimate_token_count(messages)

        try:
            # 選擇適當的 tokenizer
            tokenizer = None
            if model in self.tokenizers:
                tokenizer = self.tokenizers[model]
            else:
                # 尋找相容的 tokenizer
                for m in ["gpt-4", "gpt-3.5-turbo"]:
                    if m in self.tokenizers:
                        tokenizer = self.tokenizers[m]
                        break

            if not tokenizer:
                return await self._estimate_token_count(messages)

            # 計算 tokens
            total_tokens = 0
            for message in messages:
                # 每則訊息的基本標記：角色標記 + 內容開始標記
                total_tokens += 4

                # 計算內容的標記
                content = message.get("content", "")
                if content:
                    tokens = tokenizer.encode(content)
                    total_tokens += len(tokens)

            # 加上訊息結束標記
            total_tokens += 2

            return total_tokens

        except Exception as e:
            logger.warning(f"使用 tokenizer 計算 tokens 時發生錯誤: {e!s}，使用估算方法")
            return await self._estimate_token_count(messages)

    async def _estimate_token_count(self, messages: list[dict[str, str]]) -> int:
        """估算請求中的 token 數量 (粗略估計)"""
        try:
            # 基本計數：每則訊息的角色標記和訊息格式標記
            num_messages = len(messages)
            base_tokens = num_messages * 4 + 2

            # 計算所有內容字元
            content_tokens = 0
            for message in messages:
                content = message.get("content", "")

                # 檢測內容語言類型（使用簡單啟發式）
                is_mostly_cjk = self._is_mostly_cjk(content)

                if is_mostly_cjk:
                    # 中日韓（CJK）語言約每 1.5 個字元為 1 個 token
                    content_tokens += int(len(content) / 1.5)
                else:
                    # 英文和其他語言約每 4 個字元為 1 個 token
                    content_tokens += int(len(content) / 4)

            return int(base_tokens + content_tokens)
        except Exception as e:
            logger.error(f"估算 token 數量時發生錯誤: {e!s}")
            # 極為粗略的估計，確保回傳值
            total_chars = sum(len(m.get("content", "")) for m in messages)
            return int(total_chars / 3) + 10

    def _is_mostly_cjk(self, text: str) -> bool:
        """檢測文字是否主要為中日韓文字"""
        if not text:
            return False

        # 簡單啟發式：檢查 CJK 統一表意文字範圍
        cjk_chars = sum(1 for c in text if ord(c) >= 0x4E00 and ord(c) <= 0x9FFF)
        return (cjk_chars / len(text)) > 0.5

    async def _check_rate_limit(self, model: str, tokens: int) -> None:
        """檢查並處理 OpenAI 速率限制"""
        if self.llm_type != "openai":
            return

        # 清理舊的記錄
        current_time = time.time()
        self.request_timestamps = [ts for ts in self.request_timestamps if current_time - ts < 60]
        self.token_usage = [(ts, tokens) for ts, tokens in self.token_usage if current_time - ts < 60]

        # 計算當前速率
        requests_per_minute = len(self.request_timestamps)
        tokens_per_minute = sum(tokens for _, tokens in self.token_usage)

        # 判斷是否需要延遲
        need_delay = False
        delay_reason = ""
        wait_time = 0

        # 請求數接近限制
        if requests_per_minute >= self.max_requests_per_minute * 0.90:
            need_delay = True
            delay_reason = f"請求速率 ({requests_per_minute}/{self.max_requests_per_minute})"
            if self.request_timestamps:  # 防止 IndexError
                wait_time = int(max(wait_time, 60 - (current_time - self.request_timestamps[0]) + 0.5))

        # Token 數接近限制
        if tokens_per_minute >= self.max_tokens_per_minute * 0.90:
            need_delay = True
            delay_reason = f"{delay_reason}，" if delay_reason else ""
            delay_reason += f"token 速率 ({tokens_per_minute}/{self.max_tokens_per_minute})"
            if self.token_usage:  # 防止 IndexError
                wait_time = int(max(wait_time, 60 - (current_time - self.token_usage[0][0]) + 0.5))

        # 如果需要延遲，增加指數退避
        if need_delay:
            # 請求或 token 數接近上限時，使用指數退避而不是固定等待
            # 根據接近限制的程度來調整退避程度
            rate_usage = max(
                requests_per_minute / self.max_requests_per_minute, tokens_per_minute / self.max_tokens_per_minute
            )

            # 當使用率 > 95% 時，增加更長的退避
            if rate_usage > 0.95:
                backoff_factor = 3.0
            elif rate_usage > 0.90:
                backoff_factor = 1.5
            else:
                backoff_factor = 1.0

            wait_time = int(wait_time * backoff_factor)

            logger.warning(f"接近 OpenAI 限制 ({delay_reason})，等待 {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)

    def _classify_error(self, error: Exception) -> tuple[ApiErrorType, Exception]:
        """分類 API 錯誤類型，用於自定義重試策略"""
        error_str = str(error).lower()

        # 連線和逾時類錯誤
        if isinstance(error, (aiohttp.ClientConnectionError, asyncio.TimeoutError)):
            return ApiErrorType.CONNECTION, error

        # OpenAI 特定錯誤
        if "rate limit" in error_str or "rate_limit" in error_str or "too many requests" in error_str:
            return ApiErrorType.RATE_LIMIT, error

        if "timeout" in error_str:
            return ApiErrorType.TIMEOUT, error

        if "unauthorized" in error_str or "authentication" in error_str or "api key" in error_str:
            return ApiErrorType.AUTHENTICATION, error

        if "content filter" in error_str or "content_filter" in error_str or "content policy" in error_str:
            return ApiErrorType.CONTENT_FILTER, error

        if any(s in error_str for s in ["server error", "500", "502", "503", "504"]):
            return ApiErrorType.SERVER, error

        return ApiErrorType.UNKNOWN, error

    def _get_retry_strategy(self, error_type: ApiErrorType) -> dict[str, Any]:
        """根據錯誤類型獲取重試策略"""
        # 基本策略
        base_strategy = {
            "max_tries": 5,
            "max_time": 120,
            "on_backoff": lambda details: logger.debug(
                f"重試 {details['tries']} 次，等待 {details['wait']} 秒，錯誤: {details['exception']}"
            ),
        }

        # 根據錯誤類型自定義策略
        if error_type == ApiErrorType.RATE_LIMIT:
            return {
                **base_strategy,
                "max_tries": 8,
                "max_time": 300,  # 更長時間等待率限制恢復
                "factor": 1.5,  # 更溫和的退避因子
            }
        elif error_type == ApiErrorType.TIMEOUT:
            return {
                **base_strategy,
                "max_tries": 4,
                "max_time": 180,
                "factor": 2.0,  # 更陡峭的退避因子
            }
        elif error_type == ApiErrorType.CONNECTION:
            return {
                **base_strategy,
                "max_tries": 6,
                "jitter": None,  # 去除抖動，使退避更可預測
                "factor": 1.5,
            }
        elif error_type == ApiErrorType.SERVER:
            return {**base_strategy, "max_tries": 4, "factor": 2.0}
        elif error_type == ApiErrorType.AUTHENTICATION:
            return {
                **base_strategy,
                "max_tries": 2,  # 驗證錯誤不太可能通過重試解決
                "max_time": 30,
            }
        elif error_type == ApiErrorType.CONTENT_FILTER:
            return {
                **base_strategy,
                "max_tries": 1,  # 內容過濾錯誤不應重試
                "max_time": 1,
            }
        else:  # UNKNOWN
            return base_strategy

    async def translate_with_retry(
        self,
        text: str,
        context_texts: list[str],
        model_name: str,
        max_tries: int = 3,
        use_fallback: bool = True,
        current_index: int | None = None,
        use_cache: bool = True,
    ) -> str:
        """使用自定義重試和回退策略翻譯文字"""
        original_model = model_name
        tries = 0
        errors = []

        while tries < max_tries:
            tries += 1
            try:
                if use_cache:
                    result = await self.translate_text(text, context_texts, model_name, current_index=current_index)
                else:
                    result = await self.translate_text(
                        text,
                        context_texts,
                        model_name,
                        current_index=current_index,
                        use_cache=False,
                    )

                # 成功後，如果使用了回退模型，記錄
                if model_name != original_model:
                    logger.info(f"使用回退模型 {model_name} 成功翻譯，原模型: {original_model}")

                return result

            except Exception as e:
                error_type, error = self._classify_error(e)
                errors.append((error_type, str(error)))

                logger.warning(f"翻譯失敗 ({error_type.value}): {error!s}, 嘗試: {tries}/{max_tries}")

                # 檢查是否需要嘗試回退模型
                if use_fallback and tries == 1 and self.llm_type in self.fallback_models:
                    fallback_options = self._get_fallback_models(model_name)

                    if fallback_options:
                        fallback_model = fallback_options[0]
                        logger.info(f"切換到回退模型: {fallback_model}")
                        model_name = fallback_model
                        continue

                # 根據錯誤類型決定等待時間
                if error_type == ApiErrorType.RATE_LIMIT:
                    wait_time = 2.0**tries
                    logger.info(f"速率限制錯誤，等待 {wait_time} 秒後重試")
                    await asyncio.sleep(wait_time)
                elif error_type == ApiErrorType.TIMEOUT or error_type == ApiErrorType.CONNECTION:
                    wait_time = min(1.0 * tries, 5.0)
                    await asyncio.sleep(wait_time)
                elif error_type == ApiErrorType.SERVER:
                    wait_time = min(2.0 * tries, 10.0)
                    await asyncio.sleep(wait_time)
                elif error_type == ApiErrorType.AUTHENTICATION or error_type == ApiErrorType.CONTENT_FILTER:
                    # 這些錯誤重試沒有意義
                    break

                if tries >= max_tries:
                    break

        # 所有嘗試都失敗，回傳錯誤訊息
        error_summary = "; ".join([f"{e[0].value}: {e[1]}" for e in errors[:3]])
        logger.error(f"翻譯失敗，所有嘗試和回退都失敗: {error_summary}")
        return f"[翻譯錯誤: {error_summary}]"

    async def translate_text(
        self,
        text: str,
        context_texts: list[str],
        model_name: str,
        current_index: int | None = None,
        use_cache: bool = True,
    ) -> str:
        """翻譯文字，根據 LLM 類型選擇不同的處理方式"""
        if not text.strip():
            return ""

        logger.debug(f"開始翻譯文字: '{text}'，上下文長度: {len(context_texts)}，模型: {model_name}")
        start_time = time.time()
        self.metrics.total_requests += 1
        current_style = getattr(self.prompt_manager, "current_style", "standard") or "standard"
        prompt_version = self.prompt_manager.get_prompt_version(self.llm_type, model_name=model_name)

        # 對 qwen3.5-ud，快取鍵使用壓縮後的上下文，確保與實際 prompt 一致
        effective_context = self.prompt_manager.get_effective_cache_context_texts(
            text, context_texts, self.llm_type, model_name, current_index=current_index
        )

        # 首先嘗試從快取獲取，這步很快不需要非同步
        if use_cache:
            cached_result = self.cache_manager.get_cached_translation(
                text,
                effective_context,
                model_name,
                current_style,
                prompt_version,
                current_index=current_index,
                lookup_source="translation_client",
            )
            if cached_result:
                cache_rejection_reason = self.get_cache_rejection_reason(text, cached_result)
                if cache_rejection_reason is not None:
                    logger.info("忽略不合格快取結果 (%s)，改為重新翻譯: %s", cache_rejection_reason, text)
                else:
                    logger.debug(f"從快取獲取翻譯結果: {cached_result}")
                    self.metrics.cache_hits += 1
                    return cached_result

        protected_text = text
        protected_contexts = context_texts
        protected_name_restore_map: dict[str, str] = {}
        if self._should_apply_qwen35_ud_runtime_guards(model_name):
            protected_text, protected_contexts, protected_name_restore_map = self._protect_japanese_names_in_inputs(
                text,
                context_texts,
            )

        # 獲取適合當前 LLM 類型的提示訊息
        messages = self.prompt_manager.get_optimized_message(
            protected_text, protected_contexts, self.llm_type, model_name, current_index=current_index
        )

        try:
            result = await self._execute_translation_request(messages, model_name)

            if self._should_retry_untranslated_japanese(text, result):
                logger.info("偵測到未翻譯日文輸出，使用強化指令重試一次")
                retry_messages = self._build_untranslated_japanese_retry_messages(messages)
                retry_result = await self._execute_translation_request(retry_messages, model_name)
                if retry_result:
                    result = retry_result

            if protected_name_restore_map:
                result = self._restore_protected_japanese_names(result, protected_name_restore_map)

            # Netflix 風格後處理（如果啟用）
            if self.enable_netflix_style and self.post_processor:
                try:
                    processing_result = self.post_processor.process(result)
                    result = processing_result.text

                    # 記錄警告和自動修正
                    if processing_result.warnings:
                        logger.debug(f"Netflix 風格處理警告: {len(processing_result.warnings)} 個")
                        for warning in processing_result.warnings:
                            logger.debug(f"  [{warning.code}] {warning.message}")

                    if processing_result.auto_fixed > 0:
                        logger.debug(f"Netflix 風格自動修正: {processing_result.auto_fixed} 個問題")

                except Exception as e:
                    logger.warning(f"Netflix 風格後處理失敗，使用原始翻譯: {e}")
                    # result 保持不變，繼續使用原始翻譯結果

            # 清理單行翻譯中的多餘換行符（防護措施）
            result = self._clean_single_line_translation(text, result)

            # 記錄成功指標
            self.metrics.successful_requests += 1
            elapsed_time = time.time() - start_time
            self.metrics.total_response_time += elapsed_time

            # 更新並發控制器（非同步，執行緒安全）
            await self.concurrency_controller.update(elapsed_time)

            logger.debug(f"翻譯成功，耗時: {elapsed_time:.2f} 秒")

            # 存入快取（使用與查詢相同的有效上下文）
            cache_rejection_reason = self.get_cache_rejection_reason(text, result)
            if use_cache and cache_rejection_reason is None:
                self.cache_manager.store_translation(
                    text,
                    result,
                    effective_context,
                    model_name,
                    current_style,
                    prompt_version,
                    current_index=current_index,
                    lookup_source="translation_client_store",
                )
            elif cache_rejection_reason is not None:
                logger.info("略過儲存不合格翻譯至快取 (%s): %s", cache_rejection_reason, text)
            return result

        except Exception as e:
            self.metrics.failed_requests += 1
            elapsed_time = time.time() - start_time
            logger.error(f"翻譯失敗: {e!s}，耗時: {elapsed_time:.2f} 秒")
            raise

    def _clean_single_line_translation(self, original_text: str, translated_text: str) -> str:
        """
        清理單行翻譯中的多餘換行符

        如果原文是單行（沒有換行符），則確保翻譯結果也是單行。
        這是一個防護措施，以防 AI 在翻譯長句時插入不必要的換行符。

        Args:
            original_text: 原文文本
            translated_text: 翻譯後的文本

        Returns:
            清理後的翻譯文本
        """
        import re

        # 檢查原文是否為單行（不包含換行符）
        if "\n" not in original_text:
            # 移除所有換行符和多餘的空白字符
            cleaned = re.sub(r"\s+", " ", translated_text)
            cleaned = cleaned.strip()

            if cleaned != translated_text:
                logger.debug("已清理單行翻譯中的換行符")

            return cleaned

        # 原文是多行，保持原樣
        return translated_text

    async def _translate_with_openai(self, messages: list[dict[str, str]], model_name: str) -> str:
        """使用 OpenAI API 翻譯"""
        # llama.cpp 本地模型不需要速率限制和 token 估算
        current_time = time.time()
        if self.llm_type != "llamacpp":
            estimated_tokens = await self._count_tokens(messages, model_name)
            await self._check_rate_limit(model_name, estimated_tokens)
            self.request_timestamps.append(current_time)

        # 準備 OpenAI 參數
        is_llamacpp = self.llm_type == "llamacpp"

        if is_llamacpp:
            # llama.cpp 本地模型：使用 provider 專屬的本地推理設定
            profile = self._get_llamacpp_model_profile(model_name)
            options = profile.get("options", {})

            openai_params: dict[str, Any] = {
                "model": model_name,
                "messages": messages,
                "temperature": options.get("temperature", 0.1),
                "max_tokens": options.get("max_tokens", 256),
                "response_format": self.LLAMACPP_TRANSLATION_RESPONSE_FORMAT,
                "timeout": 600,
                "extra_body": profile.get("extra_body", {}),
            }
            # 轉發 top_p 參數（如果有設定）
            if "top_p" in options:
                openai_params["top_p"] = options["top_p"]
        else:
            openai_params: dict[str, Any] = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": min(150, 4096),
                "timeout": 30,
            }

        # 添加 response_format 參數（適用於較新的模型）
        if not is_llamacpp and ("gpt-4" in model_name or "gpt-3.5-turbo" in model_name):
            openai_params["response_format"] = {"type": "text"}

        try:
            if not self.openai_client:
                raise TranslationError("OpenAI 客戶端未初始化")
            logger.debug(f"發送 {'llama.cpp' if is_llamacpp else 'OpenAI'} API 請求: {model_name}")
            response = await self.openai_client.chat.completions.create(**openai_params)  # type: ignore[call-overload]
            content = response.choices[0].message.content
            translation: str = content.strip() if content else ""

            if is_llamacpp and translation:
                translation = self._extract_llamacpp_structured_translation(translation)

            # llama.cpp 思考模型處理：若 content 為空，嘗試從原始回應取得
            if is_llamacpp and not translation:
                # llama-server 的思考模型可能將結果放在 reasoning_content
                # 或者 content 包含 <think> 標籤
                raw_msg = response.choices[0].message
                # 嘗試取得 model_extra 中的 reasoning_content（OpenAI SDK 未定義此欄位）
                reasoning = getattr(raw_msg, "reasoning_content", None)
                if not reasoning and hasattr(raw_msg, "model_extra") and raw_msg.model_extra:
                    reasoning = raw_msg.model_extra.get("reasoning_content", "")
                if reasoning and isinstance(reasoning, str):
                    logger.debug("llama.cpp 思考模型：content 為空，從 reasoning_content 提取翻譯")
                    # 先嘗試從 reasoning 中提取結構化 JSON，再退回純文字清理
                    extracted = self._extract_llamacpp_structured_translation(reasoning)
                    translation = extracted or self._sanitize_ollama_translation(reasoning)

            # llama.cpp 回應清理（處理 <think> 標籤等）
            if is_llamacpp and translation:
                translation = self._sanitize_ollama_translation(translation)

            # 記錄實際 token 使用量
            if response.usage:
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
                total_tokens = input_tokens + output_tokens
                self.token_usage.append((current_time, total_tokens))

                # 更新指標
                self.metrics.total_tokens += total_tokens

                # 計算費用（llama.cpp 本地模型免費）
                if not is_llamacpp and model_name in self.pricing:
                    price = self.pricing[model_name]
                    cost = (input_tokens * price["input"]) + (output_tokens * price["output"])
                    self.metrics.total_cost += cost
                    logger.debug(
                        f"OpenAI API 翻譯費用: ${cost:.6f} ({input_tokens} 輸入 + {output_tokens} 輸出 tokens)"
                    )

                provider_label = "llama.cpp" if is_llamacpp else "OpenAI"
                logger.debug(f"{provider_label} API 回應翻譯: {translation} (使用 {total_tokens} tokens)")

            return translation

        except Exception as e:
            provider_label = "llama.cpp" if is_llamacpp else "OpenAI"
            logger.error(f"{provider_label} API 請求失敗: {e!s}")
            raise

    async def _translate_with_ollama(self, messages: list[dict[str, str]], model_name: str) -> str:
        """使用 Ollama API 翻譯"""
        if not self.session:
            raise TranslationError("Ollama 客戶端未初始化，請使用非同步上下文管理器")

        payload = self._build_ollama_payload(messages, model_name)

        api_url = f"{self.base_url}/api/chat"

        try:
            logger.debug(f"發送 Ollama API 請求: {api_url}")
            async with self.session.post(api_url, json=payload, timeout=self.conn_timeout) as response:
                response.raise_for_status()
                result = await response.json()

                # 處理 Ollama /api/chat 回應格式
                # 標準格式: {"message": {"role": "assistant", "content": "..."}, "done": true}
                if "message" in result and isinstance(result["message"], dict):
                    msg = result["message"]
                    translation = msg.get("content", "").strip()
                    # 記錄 thinking 欄位（若模型忽略 think:false 仍返回推理過程）
                    if msg.get("thinking"):
                        logger.debug("Ollama 模型返回了推理過程，已忽略 thinking 欄位")
                elif "choices" in result and len(result["choices"]) > 0:
                    # OpenAI 相容端點 /v1/chat/completions 格式
                    translation = result["choices"][0]["message"]["content"].strip()
                elif "response" in result:
                    # /api/generate 端點的回應格式
                    translation = result["response"].strip()
                else:
                    logger.warning(f"未知的 Ollama API 回應格式: {result}")
                    translation = str(result).strip()

                translation = self._sanitize_ollama_translation(translation)
                logger.debug(f"Ollama API 回應翻譯: {translation}")
                return translation

        except aiohttp.ClientError as e:
            logger.error(f"Ollama API 連線錯誤: {e!s}")
            raise
        except json.JSONDecodeError as e:
            logger.error(f"Ollama API 回應解析錯誤: {e!s}")
            raise
        except Exception as e:
            logger.error(f"Ollama API 請求失敗: {e!s}")
            raise

    async def _translate_with_google(self, messages: list[dict[str, str]], model_name: str) -> str:
        """使用 Google Gemini API 翻譯"""
        if not self.google_client:
            raise TranslationError("Google Gemini 客戶端未初始化")

        # 將 OpenAI 格式的 messages 轉換為 Google Gemini 格式
        # Google Gemini 使用簡單的文字輸入
        prompt_parts = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role == "system":
                prompt_parts.append(f"Instructions: {content}")
            elif role == "user":
                prompt_parts.append(content)

        prompt = "\n\n".join(prompt_parts)

        try:
            logger.debug(f"發送 Google Gemini API 請求: {model_name}")

            # 使用同步方式呼叫（Google SDK 目前主要是同步的）
            response = self.google_client.models.generate_content(
                model=model_name,
                contents=prompt,
                config={
                    "temperature": 0.1,
                    "max_output_tokens": 150,
                },
            )

            if response and response.text:
                translation = response.text.strip()
                logger.debug(f"Google Gemini API 回應翻譯: {translation}")
                return translation
            else:
                logger.warning("Google Gemini API 回應為空或格式異常")
                return ""

        except Exception as e:
            error_msg = str(e).lower()
            if "quota" in error_msg or "rate" in error_msg:
                logger.error(f"Google Gemini API 速率限制: {e!s}")
            elif "api_key" in error_msg or "authentication" in error_msg:
                logger.error(f"Google Gemini API 認證錯誤: {e!s}")
            else:
                logger.error(f"Google Gemini API 請求失敗: {e!s}")
            raise

    async def translate_batch(
        self,
        texts: list[tuple[str, list[str]]],
        model_name: str,
        concurrent_limit: int = 5,
        current_indices: list[int | None] | None = None,
        use_cache: bool = True,
    ) -> list[str]:
        """批量翻譯多個字幕，帶有並發控制"""
        if not texts:
            return []

        results = [""] * len(texts)
        cache_hits = []
        api_requests = []
        current_style = getattr(self.prompt_manager, "current_style", "standard") or "standard"
        prompt_version = self.prompt_manager.get_prompt_version(self.llm_type, model_name=model_name)

        # 首先檢查快取（使用有效上下文確保與 translate_text 的快取鍵一致）
        for i, (text, context) in enumerate(texts):
            current_index = current_indices[i] if current_indices and i < len(current_indices) else None
            if use_cache:
                effective_ctx = self.prompt_manager.get_effective_cache_context_texts(
                    text, context, self.llm_type, model_name, current_index=current_index
                )
                cached = self.cache_manager.get_cached_translation(
                    text,
                    effective_ctx,
                    model_name,
                    current_style,
                    prompt_version,
                    current_index=current_index,
                    lookup_source="translation_client_batch_precheck",
                )
                if cached:
                    cache_rejection_reason = self.get_cache_rejection_reason(text, cached)
                    if cache_rejection_reason is None:
                        cache_hits.append((i, cached))
                        self.metrics.cache_hits += 1
                    else:
                        logger.info("批量預檢忽略不合格快取結果 (%s): %s", cache_rejection_reason, text)
                        api_requests.append((i, text, context, current_index))
                else:
                    api_requests.append((i, text, context, current_index))
            else:
                api_requests.append((i, text, context, current_index))

        # 填入快取命中的結果
        for i, translation in cache_hits:
            results[i] = translation

        # 如果沒有需要 API 請求的內容，直接回傳
        if not api_requests:
            return results

        # 使用動態並發數（受 concurrent_limit 上限限制）
        adaptive_concurrency = self.concurrency_controller.get_current()
        batch_size = await self._get_effective_batch_size(
            model_name,
            concurrent_limit,
            adaptive_concurrency,
            len(api_requests),
        )
        logger.info(
            f"批量翻譯 {len(api_requests)} 個字幕，"
            f"並發數: {batch_size} (動態調整: {adaptive_concurrency}, 上限: {concurrent_limit})"
        )

        # 非同步批次處理
        semaphore = asyncio.Semaphore(batch_size)

        async def process_item(idx, txt, ctx, current_index):
            async with semaphore:
                try:
                    # 使用帶重試功能的翻譯
                    if use_cache:
                        translation = await self.translate_with_retry(txt, ctx, model_name, current_index=current_index)
                    else:
                        translation = await self.translate_with_retry(
                            txt,
                            ctx,
                            model_name,
                            current_index=current_index,
                            use_cache=False,
                        )
                    return idx, translation, None
                except Exception as e:
                    logger.error(f"批量翻譯中的項目 {idx} 失敗: {e!s}")
                    return idx, f"[翻譯錯誤: {e!s}]", e

        # 建立所有任務
        tasks = [process_item(idx, txt, ctx, current_index) for idx, txt, ctx, current_index in api_requests]

        # 等待所有任務完成
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        # 處理結果
        for result in completed:
            if isinstance(result, BaseException):
                logger.error(f"批量翻譯任務異常: {result!s}")
                continue

            if result and isinstance(result, tuple) and len(result) == 3:
                idx, translation, _error = result
                results[idx] = translation

        return results

    def _validate_openai_api_key(self, api_key: str) -> bool:
        """驗證 OpenAI API 金鑰格式

        支援的格式:
        - 舊版金鑰: sk-... (約 51 個字符)
        - 專案金鑰: sk-proj-... (約 80-200 個字符)
        - 服務帳戶金鑰: sk-svcacct-... (可變長度)

        Args:
            api_key: 要驗證的 API 金鑰

        Returns:
            bool: 金鑰格式是否有效
        """
        if not api_key or not isinstance(api_key, str):
            logger.warning("API 金鑰為空或非字串類型")
            return False

        # 移除首尾空白
        api_key = api_key.strip()

        # 檢查是否包含非法字符（只允許字母、數字、連字符、底線）
        if not re.match(r"^[a-zA-Z0-9\-_]+$", api_key):
            logger.warning("API 金鑰包含非法字符")
            return False

        # 檢查金鑰前綴和長度
        if api_key.startswith("sk-proj-"):
            # 新版專案金鑰：通常較長（80-200 字符）
            if len(api_key) < 50:
                logger.warning(f"專案金鑰長度異常短: {len(api_key)} 字符")
                return False
        elif api_key.startswith("sk-svcacct-"):
            # 服務帳戶金鑰
            if len(api_key) < 40:
                logger.warning(f"服務帳戶金鑰長度異常短: {len(api_key)} 字符")
                return False
        elif api_key.startswith("sk-"):
            # 舊版金鑰：約 51 字符
            if len(api_key) < 40 or len(api_key) > 60:
                logger.warning(f"API 金鑰長度異常: {len(api_key)} 字符（預期 40-60）")
                return False
        else:
            logger.warning("API 金鑰不以 'sk-' 開頭")
            return False

        return True

    async def is_api_available(self) -> bool:
        """檢查 API 是否可用"""
        try:
            if self.llm_type == "openai":
                # 簡單檢查 OpenAI API 連線性
                if not self.api_key:
                    logger.warning("OpenAI API 金鑰未提供")
                    return False

                # 驗證 API 金鑰格式
                if not self._validate_openai_api_key(self.api_key):
                    logger.warning("OpenAI API 金鑰格式驗證失敗")
                    return False

                # 嘗試簡單的模型列表請求
                try:
                    if self.openai_client:
                        await self.openai_client.models.list()
                    return True
                except Exception as e:
                    logger.error(f"OpenAI API 連線測試失敗: {e!s}")
                    return False

            elif self.llm_type == "ollama":
                if not self.session:
                    # 如果 session 未初始化，臨時建立一個
                    async with aiohttp.ClientSession() as session:
                        try:
                            api_url = f"{self.base_url}/api/tags"
                            async with session.get(api_url, timeout=5) as response:
                                return response.status == 200
                        except Exception as e:
                            logger.error(f"Ollama API 連線測試失敗: {e!s}")
                            return False
                else:
                    # 使用已有的 session
                    try:
                        api_url = f"{self.base_url}/api/tags"
                        async with self.session.get(api_url, timeout=5) as response:
                            return response.status == 200
                    except Exception as e:
                        logger.error(f"Ollama API 連線測試失敗: {e!s}")
                        return False

            elif self.llm_type == "llamacpp":
                diagnostics = await self._get_llamacpp_server_diagnostics(force_refresh=True)
                return bool(diagnostics.get("available"))

            return False
        except Exception as e:
            logger.error(f"API 可用性檢查失敗: {e!s}")
            return False

    def get_metrics(self) -> dict[str, Any]:
        """取得 API 使用指標"""
        return self.metrics.get_summary()

    def reset_metrics(self) -> None:
        """重置 API 使用指標"""
        self.metrics = ApiMetrics()
        logger.info("已重置 API 使用指標")


# 測試程式碼
if __name__ == "__main__":

    async def test():
        try:
            # 讀取 API 金鑰
            try:
                with open("openapi_api_key.txt") as f:
                    api_key = f.read().strip()
            except FileNotFoundError:
                print("未找到 API 金鑰檔案，使用 Ollama 模式")
                api_key = None

            # 選擇測試模式
            llm_type = "ollama" if not api_key else "openai"
            model = "llama3.2" if llm_type == "ollama" else "gpt-3.5-turbo"

            # 初始化客戶端
            client = TranslationClient(llm_type=llm_type, api_key=api_key)

            # 檢查 API 可用性
            async with client:
                print(f"測試 {llm_type} API 連線...")
                is_available = await client.is_api_available()
                print(f"API 可用性: {is_available}")

                if not is_available:
                    print("API 不可用，測試終止")
                    return

                # 單條翻譯測試
                print("\n測試單條翻譯")
                context = ["前一句", "こんにちは", "後一句"]
                result = await client.translate_with_retry("こんにちは", context, model)
                print(f"翻譯結果: {result}")

                # 批量翻譯測試
                print("\n測試批量翻譯")
                texts = [
                    ("こんにちは", ["前一句", "こんにちは", "後一句"]),
                    ("さようなら", ["前一句", "さようなら", "後一句"]),
                    ("ありがとう", ["前一句", "ありがとう", "後一句"]),
                ]
                batch_results = await client.translate_batch(texts, model)
                for i, res in enumerate(batch_results):
                    print(f"批量翻譯 {i + 1}: {res}")

                # 顯示指標
                print("\nAPI 使用指標:")
                metrics = client.get_metrics()
                for key, value in metrics.items():
                    print(f"{key}: {value}")

        except Exception as e:
            print(f"測試發生錯誤: {e!s}")
            import traceback

            traceback.print_exc()

    # 執行測試
    asyncio.run(test())
