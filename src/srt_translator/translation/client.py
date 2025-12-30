import asyncio
import json
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
import tiktoken

# 嘗試導入 OpenAI 客戶端
try:
    from openai import AsyncOpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

# 從本地模組導入
from srt_translator.core.cache import CacheManager
from srt_translator.core.prompt import PromptManager
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

    def get_summary(self) -> Dict[str, Any]:
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

    async def get_stats(self) -> Dict[str, Any]:
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
    def __init__(
        self,
        llm_type: str,
        base_url: str = "http://localhost:11434",
        api_key: str = None,
        cache_db_path: str = "data/translation_cache.db",
        netflix_style_config: Optional[Dict[str, Any]] = None,
    ):
        """
        初始化翻譯客戶端

        參數:
            llm_type: LLM 類型 ('ollama' 或 'openai')
            base_url: API 基礎 URL
            api_key: API 金鑰 (用於 OpenAI)
            cache_db_path: 快取資料庫路徑
            netflix_style_config: Netflix 風格配置（可選）
                - enabled: 是否啟用 Netflix 風格後處理（預設: False）
                - auto_fix: 是否自動修正格式問題（預設: True）
                - strict_mode: 是否使用嚴格模式（預設: False）
                - max_chars_per_line: 每行最大字符數（預設: 16）
                - max_lines: 最多行數（預設: 2）
        """
        self.llm_type = llm_type
        self.base_url = base_url if llm_type == "ollama" else "https://api.openai.com/v1"
        self.cache_manager = CacheManager(cache_db_path)
        self.prompt_manager = PromptManager()
        self.session = None
        self.api_key = api_key
        self.metrics = ApiMetrics()

        # 連線池設定
        self.conn_limit = 10  # 最大連線數
        self.conn_timeout = aiohttp.ClientTimeout(
            total=60,  # 總逾時
            connect=10,  # 連線逾時
            sock_connect=10,  # Socket 連線逾時
            sock_read=30,  # Socket 讀取逾時
        )

        # 回退機制設定
        self.fallback_models = {
            "openai": {"gpt-4": ["gpt-3.5-turbo"], "gpt-4-turbo": ["gpt-4", "gpt-3.5-turbo"], "gpt-3.5-turbo": []},
            "ollama": {"llama3": ["mistral"], "mixtral": ["mistral", "tinyllama"], "mistral": ["tinyllama"]},
        }

        # OpenAI 客戶端最佳化
        if llm_type == "openai":
            if not OPENAI_AVAILABLE:
                logger.error("未安裝 OpenAI 客戶端函式庫，OpenAI 模式不可用")
                raise ImportError("請安裝 OpenAI Python 套件: pip install openai")

            self.openai_client = AsyncOpenAI(api_key=api_key, timeout=self.conn_timeout)

            # 為各模型載入適當的 tokenizer
            self.tokenizers = {}
            self._load_tokenizers()

            # 速率限制追蹤
            self.request_timestamps = []  # 用於追蹤 API 請求時間
            self.max_requests_per_minute = 3500  # OpenAI API 預設限制
            self.max_tokens_per_minute = 180000  # OpenAI API 預設限制
            self.token_usage = []  # 用於追蹤 token 使用量

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
        if self.llm_type == "ollama":
            # 使用 TCP 連接器以自定義連線限制
            connector = aiohttp.TCPConnector(
                limit=self.conn_limit,
                limit_per_host=self.conn_limit,
                ssl=False,  # Ollama 通常是本機執行，不需要 SSL
            )
            self.session = aiohttp.ClientSession(connector=connector, timeout=self.conn_timeout)
            logger.debug(f"初始化 aiohttp.ClientSession for Ollama，連線限制: {self.conn_limit}")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同步上下文管理器清理"""
        # 關閉 Ollama session
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

    async def _count_tokens(self, messages: List[Dict[str, str]], model: str) -> int:
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

    async def _estimate_token_count(self, messages: List[Dict[str, str]]) -> int:
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
                    content_tokens += len(content) // 1.5
                else:
                    # 英文和其他語言約每 4 個字元為 1 個 token
                    content_tokens += len(content) // 4

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
                wait_time = max(wait_time, 60 - (current_time - self.request_timestamps[0]) + 0.5)

        # Token 數接近限制
        if tokens_per_minute >= self.max_tokens_per_minute * 0.90:
            need_delay = True
            delay_reason = f"{delay_reason}，" if delay_reason else ""
            delay_reason += f"token 速率 ({tokens_per_minute}/{self.max_tokens_per_minute})"
            if self.token_usage:  # 防止 IndexError
                wait_time = max(wait_time, 60 - (current_time - self.token_usage[0][0]) + 0.5)

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

            wait_time = wait_time * backoff_factor

            logger.warning(f"接近 OpenAI 限制 ({delay_reason})，等待 {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)

    def _classify_error(self, error: Exception) -> Tuple[ApiErrorType, Exception]:
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

    def _get_retry_strategy(self, error_type: ApiErrorType) -> Dict[str, Any]:
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
        self, text: str, context_texts: List[str], model_name: str, max_tries: int = 3, use_fallback: bool = True
    ) -> str:
        """使用自定義重試和回退策略翻譯文字"""
        original_model = model_name
        tries = 0
        errors = []

        while tries < max_tries:
            tries += 1
            try:
                result = await self.translate_text(text, context_texts, model_name)

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
                    fallback_options = self.fallback_models[self.llm_type].get(model_name, [])

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

    async def translate_text(self, text: str, context_texts: List[str], model_name: str) -> str:
        """翻譯文字，根據 LLM 類型選擇不同的處理方式"""
        if not text.strip():
            return ""

        logger.debug(f"開始翻譯文字: '{text}'，上下文長度: {len(context_texts)}，模型: {model_name}")
        start_time = time.time()
        self.metrics.total_requests += 1

        # 首先嘗試從快取獲取，這步很快不需要非同步
        cached_result = self.cache_manager.get_cached_translation(text, context_texts, model_name)
        if cached_result:
            logger.debug(f"從快取獲取翻譯結果: {cached_result}")
            self.metrics.cache_hits += 1
            return cached_result

        # 獲取適合當前 LLM 類型的提示訊息
        messages = self.prompt_manager.get_optimized_message(text, context_texts, self.llm_type, model_name)

        try:
            if self.llm_type == "openai":
                result = await self._translate_with_openai(messages, model_name)
            elif self.llm_type == "ollama":
                result = await self._translate_with_ollama(messages, model_name)
            else:
                raise ValueError(f"不支援的 LLM 類型: {self.llm_type}")

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

            # 存入快取
            self.cache_manager.store_translation(text, result, context_texts, model_name)
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

    async def _translate_with_openai(self, messages: List[Dict[str, str]], model_name: str) -> str:
        """使用 OpenAI API 翻譯"""
        # 估算 token 數量
        estimated_tokens = await self._count_tokens(messages, model_name)

        # 檢查速率限制
        await self._check_rate_limit(model_name, estimated_tokens)

        # 記錄此次請求的時間戳
        current_time = time.time()
        self.request_timestamps.append(current_time)

        # 準備 OpenAI 參數
        openai_params = {
            "model": model_name,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": min(150, 4096),  # 限制回應長度，SRT 字幕通常不會很長
            "timeout": 30,  # 設定逾時
        }

        # 添加 response_format 參數（適用於較新的模型）
        if "gpt-4" in model_name or "gpt-3.5-turbo" in model_name:
            openai_params["response_format"] = {"type": "text"}

        try:
            logger.debug(f"發送 OpenAI API 請求: {model_name}")
            response = await self.openai_client.chat.completions.create(**openai_params)
            translation = response.choices[0].message.content.strip()

            # 記錄實際 token 使用量
            input_tokens = response.usage.prompt_tokens
            output_tokens = response.usage.completion_tokens
            total_tokens = input_tokens + output_tokens
            self.token_usage.append((current_time, total_tokens))

            # 更新指標
            self.metrics.total_tokens += total_tokens

            # 計算費用
            # 注意：self.pricing 中儲存的是「每 token」的價格（已經從「每千 token」轉換）
            # 因此計算時不需要再除以 1000
            if model_name in self.pricing:
                price = self.pricing[model_name]
                cost = (input_tokens * price["input"]) + (output_tokens * price["output"])
                self.metrics.total_cost += cost
                logger.debug(f"OpenAI API 翻譯費用: ${cost:.6f} ({input_tokens} 輸入 + {output_tokens} 輸出 tokens)")

            logger.debug(f"OpenAI API 回應翻譯: {translation} (使用 {total_tokens} tokens)")
            return translation

        except Exception as e:
            logger.error(f"OpenAI API 請求失敗: {e!s}")
            raise

    async def _translate_with_ollama(self, messages: List[Dict[str, str]], model_name: str) -> str:
        """使用 Ollama API 翻譯"""
        if not self.session:
            raise RuntimeError("Ollama 客戶端未初始化，請使用非同步上下文管理器")

        payload = {"model": model_name, "messages": messages, "temperature": 0.1, "stream": False}

        api_url = f"{self.base_url}/api/chat"

        try:
            logger.debug(f"發送 Ollama API 請求: {api_url}")
            async with self.session.post(api_url, json=payload, timeout=self.conn_timeout) as response:
                response.raise_for_status()
                result = await response.json()

                # 處理不同的 Ollama API 回應格式
                if "choices" in result and len(result["choices"]) > 0:
                    # 標準 OpenAI 格式
                    translation = result["choices"][0]["message"]["content"].strip()
                elif "response" in result:
                    # 舊版 Ollama 格式
                    translation = result["response"].strip()
                else:
                    logger.warning(f"未知的 Ollama API 回應格式: {result}")
                    # 嘗試從結果中提取任何文字內容
                    translation = str(result).strip()

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

    async def translate_batch(
        self, texts: List[Tuple[str, List[str]]], model_name: str, concurrent_limit: int = 5
    ) -> List[str]:
        """批量翻譯多個字幕，帶有並發控制"""
        if not texts:
            return []

        results = [""] * len(texts)
        cache_hits = []
        api_requests = []

        # 首先檢查快取
        for i, (text, context) in enumerate(texts):
            cached = self.cache_manager.get_cached_translation(text, context, model_name)
            if cached:
                cache_hits.append((i, cached))
                self.metrics.cache_hits += 1
            else:
                api_requests.append((i, text, context))

        # 填入快取命中的結果
        for i, translation in cache_hits:
            results[i] = translation

        # 如果沒有需要 API 請求的內容，直接回傳
        if not api_requests:
            return results

        # 使用動態並發數（受 concurrent_limit 上限限制）
        adaptive_concurrency = self.concurrency_controller.get_current()
        batch_size = min(concurrent_limit, adaptive_concurrency, len(api_requests))
        logger.info(
            f"批量翻譯 {len(api_requests)} 個字幕，"
            f"並發數: {batch_size} (動態調整: {adaptive_concurrency}, 上限: {concurrent_limit})"
        )

        # 非同步批次處理
        semaphore = asyncio.Semaphore(batch_size)

        async def process_item(idx, txt, ctx):
            async with semaphore:
                try:
                    # 使用帶重試功能的翻譯
                    translation = await self.translate_with_retry(txt, ctx, model_name)
                    return idx, translation, None
                except Exception as e:
                    logger.error(f"批量翻譯中的項目 {idx} 失敗: {e!s}")
                    return idx, f"[翻譯錯誤: {e!s}]", e

        # 建立所有任務
        tasks = [process_item(idx, txt, ctx) for idx, txt, ctx in api_requests]

        # 等待所有任務完成
        completed = await asyncio.gather(*tasks, return_exceptions=True)

        # 處理結果
        for result in completed:
            if isinstance(result, Exception):
                logger.error(f"批量翻譯任務異常: {result!s}")
                continue

            if result and len(result) == 3:
                idx, translation, error = result
                results[idx] = translation

        return results

    async def is_api_available(self) -> bool:
        """檢查 API 是否可用"""
        try:
            if self.llm_type == "openai":
                # 簡單檢查 OpenAI API 連線性
                if not self.api_key:
                    logger.warning("OpenAI API 金鑰未提供")
                    return False

                # 簡單驗證 API 金鑰格式
                if not self.api_key.startswith("sk-") or len(self.api_key) < 20:
                    logger.warning("OpenAI API 金鑰格式不正確")
                    return False

                # 嘗試簡單的模型列表請求
                try:
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

            return False
        except Exception as e:
            logger.error(f"API 可用性檢查失敗: {e!s}")
            return False

    def get_metrics(self) -> Dict[str, Any]:
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
            model = "llama3" if llm_type == "ollama" else "gpt-3.5-turbo"

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
