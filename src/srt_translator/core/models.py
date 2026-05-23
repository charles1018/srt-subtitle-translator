import asyncio
import logging
import os
import re
import threading
import time
from dataclasses import dataclass, field
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

import aiohttp

# 載入環境變數（優先從 .env 檔案）
try:
    from dotenv import load_dotenv

    # 嘗試從專案根目錄載入 .env
    env_path = Path(__file__).resolve().parents[3] / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()  # 嘗試從當前目錄載入
    DOTENV_AVAILABLE = True
except ImportError:
    DOTENV_AVAILABLE = False

# 嘗試匯入所有可能的 LLM 客戶端
try:
    import openai
    from openai import OpenAI

    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    from google import genai

    GOOGLE_AVAILABLE = True
except ImportError:
    GOOGLE_AVAILABLE = False

# 從配置管理器導入
from srt_translator.core.config import ConfigManager

# 設定日誌
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 確保日誌目錄存在
os.makedirs("logs", exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = TimedRotatingFileHandler(
        filename="logs/model_manager.log", when="midnight", interval=1, backupCount=7, encoding="utf-8"
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)


@dataclass
class ModelInfo:
    """模型資訊資料類別"""

    id: str  # 模型 ID/名稱
    provider: str  # 提供者（如 openai、google、llamacpp）
    name: str = ""  # 顯示名稱(如不同於 ID)
    description: str = ""  # 模型描述
    context_length: int = 4096  # 上下文長度
    pricing: str = "未知"  # 價格描述
    recommended_for: str = "一般翻譯"  # 推薦用途
    parallel: int = 10  # 建議並行數量
    tags: list[str] = field(default_factory=list)  # 模型標籤
    capabilities: dict[str, float] = field(default_factory=dict)  # 能力評分(0-1)
    available: bool = True  # 是否可用

    def to_dict(self) -> dict[str, Any]:
        """轉換為字典格式"""
        return {
            "id": self.id,
            "name": self.name or self.id,
            "provider": self.provider,
            "description": self.description,
            "context_length": self.context_length,
            "pricing": self.pricing,
            "recommended_for": self.recommended_for,
            "parallel": self.parallel,
            "tags": self.tags,
            "capabilities": self.capabilities,
            "available": self.available,
        }


class ModelManager:
    """模型管理器，負責管理、載入和監控不同的大型語言模型"""

    # 類變數，用於實現單例模式
    _instance = None
    _lock = threading.Lock()

    @classmethod
    def get_instance(cls, config_file: str | None = None) -> "ModelManager":
        """獲取模型管理器的單例實例

        參數:
            config_file: 配置檔案路徑，若為None則使用預設路徑

        回傳:
            模型管理器實例
        """
        with cls._lock:
            if cls._instance is None:
                cls._instance = ModelManager(config_file)
            return cls._instance

    def __init__(self, config_file: str | None = None):
        """初始化模型管理器

        參數:
            config_file: 配置檔案路徑
        """
        # 獲取配置管理器實例
        if config_file:
            self.config_manager = ConfigManager.get_instance("model", config_path=config_file)
        else:
            self.config_manager = ConfigManager.get_instance("model")
        self.config_file = config_file or self.config_manager.get_config_path()

        # 從配置載入模型設定
        self.config = self._load_config()

        # llama.cpp 設定
        self.llamacpp_url = self.config.get("llamacpp_url", "http://localhost:8080")
        self.default_llamacpp_model: str = str(self.config.get("default_llamacpp_model", "local-model"))

        # 常見模型模式，用於過濾
        self.model_patterns = self.config.get(
            "model_patterns",
            [
                "llama",
                "mixtral",
                "aya",
                "yi",
                "qwen",
                "solar",
                "mistral",
                "openchat",
                "neural",
                "phi",
                "stable",
                "dolphin",
                "vicuna",
                "zephyr",
                "gemma",
                "deepseek",
            ],
        )

        # 快取設定
        self.cached_models: dict[str, list[ModelInfo]] = {}
        self.cache_time: dict[str, float] = {}
        self.cache_expiry = self.config.get("cache_expiry", 600)  # 10 分鐘快取過期

        # 用於測試 API 的逾時設定
        self.connect_timeout = self.config.get("connect_timeout", 5)
        self.request_timeout = self.config.get("request_timeout", 10)

        # 非同步 HTTP 客戶端
        self.session: aiohttp.ClientSession | None = None
        self._session_lock: asyncio.Lock | None = None

        # API 金鑰集合
        self.api_keys: dict[str, str] = {}

        # 初始化模型資訊庫
        self._init_model_info_database()

        # 載入 API 金鑰
        self._load_api_keys()

        logger.info(f"ModelManager 初始化完成，預設 llama.cpp 模型: {self.default_llamacpp_model}")

    def _load_config(self) -> dict[str, Any]:
        """從配置管理器載入設定"""
        return self.config_manager.get_config()

    def _save_config(self) -> bool:
        """儲存設定到配置管理器"""
        for key, value in self.config.items():
            self.config_manager.set_value(key, value, auto_save=False)
        return self.config_manager.save_config()

    def _load_api_keys(self) -> None:
        """載入各種服務的 API 金鑰

        支援的環境變數：
        - OPENAI_API_KEY: OpenAI API 金鑰
        - GOOGLE_API_KEY 或 GEMINI_API_KEY: Google Gemini API 金鑰

        安全注意事項：
        - 建議使用 .env 檔案管理 API 金鑰
        - 確保 .env 檔案已加入 .gitignore
        """
        # 載入 OpenAI API 金鑰
        try:
            openai_key = os.environ.get("OPENAI_API_KEY", "").strip()

            if openai_key:
                self.api_keys["openai"] = openai_key
                logger.info("已從環境變數 / .env 載入 OpenAI API 金鑰")
            else:
                logger.debug("未設定 OpenAI API 金鑰")
        except Exception as e:
            logger.error(f"載入 OpenAI API 金鑰時發生錯誤: {e!s}")

        # 載入 Google Gemini API 金鑰
        try:
            # 支援兩種環境變數名稱
            google_key = os.environ.get("GOOGLE_API_KEY", "").strip()
            if not google_key:
                google_key = os.environ.get("GEMINI_API_KEY", "").strip()

            if google_key:
                self.api_keys["google"] = google_key
                logger.info("已從環境變數 / .env 載入 Google API 金鑰")
        except Exception as e:
            logger.error(f"載入 Google API 金鑰時發生錯誤: {e!s}")

    def _init_model_info_database(self) -> None:
        """初始化模型資訊資料庫"""
        self.model_database: dict[str, ModelInfo] = {}

        # OpenAI 模型資訊
        openai_models = {
            "gpt-4o": ModelInfo(
                id="gpt-4o",
                provider="openai",
                name="GPT-4o",
                description="OpenAI 最新最強大的模型，速度快且精確度高",
                context_length=128000,
                pricing="高",
                recommended_for="專業翻譯，需要最高品質",
                parallel=25,
                tags=["advanced", "fast", "accurate"],
                capabilities={"translation": 0.98, "multilingual": 0.99, "context_handling": 0.98},
            ),
            "gpt-4-turbo": ModelInfo(
                id="gpt-4-turbo",
                provider="openai",
                name="GPT-4 Turbo",
                description="強大的翻譯模型，適合需要高品質翻譯的場合",
                context_length=128000,
                pricing="高",
                recommended_for="專業翻譯，需要高品質",
                parallel=20,
                tags=["advanced", "accurate"],
                capabilities={"translation": 0.96, "multilingual": 0.95, "context_handling": 0.96},
            ),
            "gpt-4": ModelInfo(
                id="gpt-4",
                provider="openai",
                name="GPT-4",
                description="強大而穩定的翻譯模型",
                context_length=8192,
                pricing="高",
                recommended_for="專業翻譯，需要高品質",
                parallel=15,
                tags=["advanced", "stable"],
                capabilities={"translation": 0.94, "multilingual": 0.93, "context_handling": 0.95},
            ),
            "gpt-3.5-turbo-16k": ModelInfo(
                id="gpt-3.5-turbo-16k",
                provider="openai",
                name="GPT-3.5 Turbo (16K)",
                description="具有較大上下文視窗的經濟型模型",
                context_length=16384,
                pricing="中",
                recommended_for="包含較多上下文的一般翻譯",
                parallel=30,
                tags=["balanced", "extended_context"],
                capabilities={"translation": 0.88, "multilingual": 0.86, "context_handling": 0.90},
            ),
            "gpt-3.5-turbo": ModelInfo(
                id="gpt-3.5-turbo",
                provider="openai",
                name="GPT-3.5 Turbo",
                description="平衡經濟性和翻譯品質的模型",
                context_length=4096,
                pricing="低",
                recommended_for="日常翻譯，最具成本效益",
                parallel=35,
                tags=["balanced", "economic"],
                capabilities={"translation": 0.85, "multilingual": 0.84, "context_handling": 0.82},
            ),
        }

        # Google Gemini 模型資訊
        google_models = {
            # Gemini 3 系列（最新，2025年11月發布）
            "gemini-3-pro": ModelInfo(
                id="gemini-3-pro",
                provider="google",
                name="Gemini 3 Pro",
                description="Google 最新旗艦模型，推理優先設計，適合複雜翻譯任務",
                context_length=1048576,
                pricing="高",
                recommended_for="專業翻譯、文學翻譯、需要最高品質",
                parallel=15,
                tags=["advanced", "accurate", "reasoning", "multilingual"],
                capabilities={"translation": 0.98, "multilingual": 0.99, "context_handling": 0.97},
            ),
            "gemini-3-flash": ModelInfo(
                id="gemini-3-flash",
                provider="google",
                name="Gemini 3 Flash",
                description="Google 最新快速模型，強大的多模態理解和推理能力",
                context_length=1048576,
                pricing="中",
                recommended_for="一般翻譯任務，平衡速度與品質",
                parallel=25,
                tags=["fast", "balanced", "reasoning", "multilingual"],
                capabilities={"translation": 0.95, "multilingual": 0.96, "context_handling": 0.94},
            ),
            # Gemini 2.5 系列
            "gemini-2.5-pro": ModelInfo(
                id="gemini-2.5-pro",
                provider="google",
                name="Gemini 2.5 Pro",
                description="Google 進階專業模型，適合高品質翻譯",
                context_length=1048576,
                pricing="高",
                recommended_for="專業翻譯、需要高品質輸出",
                parallel=15,
                tags=["advanced", "accurate", "multilingual"],
                capabilities={"translation": 0.97, "multilingual": 0.98, "context_handling": 0.96},
            ),
            "gemini-2.5-flash": ModelInfo(
                id="gemini-2.5-flash",
                provider="google",
                name="Gemini 2.5 Flash",
                description="Google 快速模型，平衡速度與品質",
                context_length=1048576,
                pricing="中",
                recommended_for="一般翻譯任務，需要良好的速度和品質",
                parallel=25,
                tags=["balanced", "fast", "multilingual"],
                capabilities={"translation": 0.93, "multilingual": 0.94, "context_handling": 0.92},
            ),
            "gemini-2.5-flash-lite": ModelInfo(
                id="gemini-2.5-flash-lite",
                provider="google",
                name="Gemini 2.5 Flash Lite",
                description="Google 輕量快速模型，優化速度和成本效益",
                context_length=1048576,
                pricing="低",
                recommended_for="大批量翻譯任務，速度快且成本低",
                parallel=30,
                tags=["fast", "economic", "lite", "multilingual"],
                capabilities={"translation": 0.90, "multilingual": 0.91, "context_handling": 0.88},
            ),
            # Gemini 2.0 系列（將於 2026年3月退役）
            "gemini-2.0-flash": ModelInfo(
                id="gemini-2.0-flash",
                provider="google",
                name="Gemini 2.0 Flash",
                description="Google 2.0 快速模型（將於 2026年3月退役）",
                context_length=1048576,
                pricing="低",
                recommended_for="大批量翻譯任務，速度快且成本低",
                parallel=30,
                tags=["fast", "economic", "multilingual", "legacy"],
                capabilities={"translation": 0.90, "multilingual": 0.92, "context_handling": 0.88},
            ),
        }

        # llama.cpp 本地模型資訊（騰訊 Hunyuan-MT2 翻譯專用模型）
        # id 刻意使用 GGUF 檔名，使未指定 -m 時推薦結果能觸發 hunyuan-mt prompt 策略；
        # llama-server 會忽略 API 的 model 欄位、改用實際載入的模型，故名稱僅影響 prompt 策略。
        llamacpp_models = {
            "Hy-MT2-7B-Q4_K_M": ModelInfo(
                id="Hy-MT2-7B-Q4_K_M",
                provider="llamacpp",
                name="Hunyuan-MT2 7B (Q4_K_M)",
                description="騰訊 Hunyuan-MT2 翻譯專用模型 7B，支援 33 語言；8GB VRAM 可全載入，品質優於 1.8B",
                context_length=262144,
                pricing="免費(本機執行)",
                recommended_for="高品質日英中字幕翻譯（本地首選，速度快、語意理解佳）",
                parallel=3,
                tags=["free", "local", "translation", "multilingual", "chinese"],
                capabilities={"translation": 0.95, "multilingual": 0.93, "context_handling": 0.6, "chinese": 0.93},
            ),
            "Hy-MT2-1.8B-Q8_0": ModelInfo(
                id="Hy-MT2-1.8B-Q8_0",
                provider="llamacpp",
                name="Hunyuan-MT2 1.8B (Q8_0)",
                description="騰訊 Hunyuan-MT2 翻譯專用模型 1.8B，極輕量、速度最快；品質略遜 7B",
                context_length=262144,
                pricing="免費(本機執行)",
                recommended_for="低資源環境的快速字幕翻譯",
                parallel=3,
                tags=["free", "local", "translation", "multilingual", "chinese", "fast"],
                capabilities={"translation": 0.88, "multilingual": 0.86, "context_handling": 0.55, "chinese": 0.88},
            ),
        }

        # 合併所有模型資訊到資料庫
        for model in openai_models.values():
            self.model_database[f"openai:{model.id}"] = model

        for model in google_models.values():
            self.model_database[f"google:{model.id}"] = model

        for model in llamacpp_models.values():
            self.model_database[f"llamacpp:{model.id}"] = model

    def _get_session_lock(self) -> asyncio.Lock:
        """取得當前 event loop 可安全使用的 session lock。"""
        current_loop = asyncio.get_running_loop()
        lock = self._session_lock
        lock_loop = getattr(lock, "_loop", None) if lock is not None else None

        if lock is None or (lock_loop is not None and lock_loop is not current_loop):
            lock = asyncio.Lock()
            self._session_lock = lock

        return lock

    async def _init_async_session(self) -> None:
        """初始化非同步 HTTP 客戶端"""
        session_lock = self._get_session_lock()
        async with session_lock:
            current_loop = asyncio.get_running_loop()
            # 若 session 綁定的 event loop 已關閉，先清除舊 session
            if self.session is not None:
                session_loop = getattr(self.session, "_loop", None)
                if getattr(self.session, "closed", False):
                    self.session = None
                    logger.debug("偵測到已關閉的 HTTP 客戶端 session，將重新建立")
                elif session_loop is not None and session_loop.is_closed():
                    self.session = None
                    logger.debug("偵測到 HTTP 客戶端 session 的 event loop 已關閉，將重新建立")
                elif session_loop is not None and session_loop is not current_loop:
                    self.session = None
                    logger.debug("偵測到 HTTP 客戶端 session 屬於不同 event loop，將重新建立")
            if self.session is None:
                timeout = aiohttp.ClientTimeout(
                    total=self.request_timeout,
                    connect=self.connect_timeout,
                    sock_connect=self.connect_timeout,
                    sock_read=self.request_timeout,
                )
                self.session = aiohttp.ClientSession(timeout=timeout)
                logger.debug("已初始化非同步 HTTP 客戶端")

    async def _close_async_session(self) -> None:
        """關閉非同步 HTTP 客戶端"""
        session_lock = self._get_session_lock()
        async with session_lock:
            if self.session:
                try:
                    await self.session.close()
                except RuntimeError as e:
                    logger.debug(f"關閉跨 event loop 的 HTTP 客戶端 session 時略過例外: {e!s}")
                self.session = None
                logger.debug("已關閉非同步 HTTP 客戶端")

    async def get_model_list_async(self, llm_type: str, api_key: str | None = None) -> list[ModelInfo]:
        """非同步獲取模型列表

        參數:
            llm_type: LLM類型 (如 "llamacpp"、"openai" 或 "google")
            api_key: API金鑰 (可選)

        回傳:
            ModelInfo物件列表
        """
        await self._init_async_session()

        try:
            # 檢查快取是否有效
            if llm_type in self.cached_models:
                elapsed = time.time() - self.cache_time.get(llm_type, 0)
                if elapsed < self.cache_expiry:
                    return self.cached_models[llm_type]

            # 如果沒有提供API金鑰，使用已存的金鑰
            if api_key is None:
                api_key = self.api_keys.get(llm_type)

            # 根據不同 LLM 類型獲取模型列表
            if llm_type == "openai":
                models = await self._get_openai_models_async(api_key or "")
            elif llm_type == "llamacpp":
                models = await self._get_llamacpp_models_async()
            elif llm_type == "google" and GOOGLE_AVAILABLE:
                models = await self._get_google_models_async(api_key or "")
            else:
                logger.warning(f"不支援的 LLM 類型: {llm_type}，返回空列表")
                models = []

            # 更新快取
            self.cached_models[llm_type] = models
            self.cache_time[llm_type] = time.time()

            return models

        except Exception as e:
            logger.error(f"獲取模型列表失敗: {e!s}")
            # 如果之前有快取，使用過期快取
            if llm_type in self.cached_models:
                logger.info("使用過期快取的模型列表")
                return self.cached_models[llm_type]

            # 返回預設模型
            if llm_type == "openai":
                default_model = self._create_default_openai_model()
                return [default_model]
            elif llm_type == "llamacpp":
                return self._get_llamacpp_fallback_models()
            return []

    def get_model_list(self, llm_type: str, api_key: str | None = None) -> list[str]:
        """同步獲取模型列表(字串列表版本，向後相容)

        參數:
            llm_type: LLM類型 (如 "llamacpp"、"openai" 或 "google")
            api_key: API金鑰 (可選)

        回傳:
            模型名稱字串列表
        """
        # 確保在正確的事件循環中執行
        try:
            loop = asyncio.get_event_loop()
            if loop.is_closed():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

        try:
            model_infos = loop.run_until_complete(self.get_model_list_async(llm_type, api_key))
            # 轉換為字串列表，保持向後相容
            return [model.id for model in model_infos]
        finally:
            # 只在我們創建的新循環中關閉
            if loop.is_running():
                pass  # 不關閉正在運行的循環
            elif not loop.is_closed():
                loop.close()

    def _create_default_openai_model(self) -> ModelInfo:
        """建立預設 OpenAI 模型"""
        key = "openai:gpt-3.5-turbo"
        if key in self.model_database:
            model = self.model_database[key]
        else:
            model = ModelInfo(
                id="gpt-3.5-turbo",
                provider="openai",
                name="GPT-3.5 Turbo",
                description="OpenAI 的經濟型模型",
                pricing="低",
                recommended_for="一般翻譯任務",
            )
        return model

    async def _get_google_models_async(self, api_key: str) -> list[ModelInfo]:
        """非同步獲取 Google Gemini 模型列表

        參數:
            api_key: Google API金鑰

        回傳:
            Google Gemini ModelInfo物件列表
        """
        if not GOOGLE_AVAILABLE or not api_key:
            return []

        try:
            # 建立 Google Gemini 模型列表
            google_models = [
                # Gemini 3 系列（最新，2025年11月發布）
                ModelInfo(
                    id="gemini-3-pro",
                    provider="google",
                    name="Gemini 3 Pro",
                    description="Google 最新旗艦模型，推理優先設計，適合複雜翻譯任務",
                    context_length=1048576,
                    pricing="高",
                    recommended_for="專業翻譯、文學翻譯、需要最高品質",
                    parallel=15,
                    tags=["advanced", "accurate", "reasoning", "multilingual"],
                    capabilities={"translation": 0.98, "multilingual": 0.99, "context_handling": 0.97},
                ),
                ModelInfo(
                    id="gemini-3-flash",
                    provider="google",
                    name="Gemini 3 Flash",
                    description="Google 最新快速模型，強大的多模態理解和推理能力",
                    context_length=1048576,
                    pricing="中",
                    recommended_for="一般翻譯任務，平衡速度與品質",
                    parallel=25,
                    tags=["fast", "balanced", "reasoning", "multilingual"],
                    capabilities={"translation": 0.95, "multilingual": 0.96, "context_handling": 0.94},
                ),
                # Gemini 2.5 系列
                ModelInfo(
                    id="gemini-2.5-pro",
                    provider="google",
                    name="Gemini 2.5 Pro",
                    description="Google 進階專業模型，適合高品質翻譯",
                    context_length=1048576,
                    pricing="高",
                    recommended_for="專業翻譯、需要高品質輸出",
                    parallel=15,
                    tags=["advanced", "accurate", "multilingual"],
                    capabilities={"translation": 0.97, "multilingual": 0.98, "context_handling": 0.96},
                ),
                ModelInfo(
                    id="gemini-2.5-flash",
                    provider="google",
                    name="Gemini 2.5 Flash",
                    description="Google 快速模型，平衡速度與品質",
                    context_length=1048576,
                    pricing="中",
                    recommended_for="一般翻譯任務，需要良好的速度和品質",
                    parallel=25,
                    tags=["balanced", "fast", "multilingual"],
                    capabilities={"translation": 0.93, "multilingual": 0.94, "context_handling": 0.92},
                ),
                ModelInfo(
                    id="gemini-2.5-flash-lite",
                    provider="google",
                    name="Gemini 2.5 Flash Lite",
                    description="Google 輕量快速模型，優化速度和成本效益",
                    context_length=1048576,
                    pricing="低",
                    recommended_for="大批量翻譯任務，速度快且成本低",
                    parallel=30,
                    tags=["fast", "economic", "lite", "multilingual"],
                    capabilities={"translation": 0.90, "multilingual": 0.91, "context_handling": 0.88},
                ),
                # Gemini 2.0 系列（將於 2026年3月退役）
                ModelInfo(
                    id="gemini-2.0-flash",
                    provider="google",
                    name="Gemini 2.0 Flash",
                    description="Google 2.0 快速模型（將於 2026年3月退役）",
                    context_length=1048576,
                    pricing="低",
                    recommended_for="大批量翻譯任務，速度快且成本低",
                    parallel=30,
                    tags=["fast", "economic", "multilingual", "legacy"],
                    capabilities={"translation": 0.90, "multilingual": 0.92, "context_handling": 0.88},
                ),
            ]

            # 驗證 API 金鑰是否有效
            try:
                with genai.Client(api_key=api_key) as client:
                    # 使用簡單的請求驗證 API 金鑰
                    response = client.models.generate_content(model="gemini-2.5-flash", contents="Hi")
                    if response.text:
                        # 呼叫成功，API 金鑰有效
                        for model in google_models:
                            model.available = True
                        logger.info("Google API 金鑰驗證成功")
            except Exception as e:
                logger.warning(f"Google API 金鑰驗證失敗: {e!s}")
                # 標記所有模型為不可用
                for model in google_models:
                    model.available = False

            return google_models
        except Exception as e:
            logger.error(f"獲取 Google 模型列表失敗: {e!s}")
            return []

    def get_default_model(self, llm_type: str) -> str:
        """返回預設模型，針對翻譯進行最佳化

        參數:
            llm_type: LLM類型 (如 "openai"、"google" 或 "llamacpp")

        回傳:
            預設模型名稱
        """
        provider_defaults = {
            "openai": "gpt-3.5-turbo",  # 最經濟的選擇
            "google": "gemini-2.0-flash",  # 最快速且經濟的選擇
            "llamacpp": "local-model",  # llama-server 載入的模型
        }
        return provider_defaults.get(llm_type, self.default_llamacpp_model)

    def get_model_info(self, model_name: str, provider: str | None = None) -> dict[str, Any]:
        """獲取模型的詳細資訊

        參數:
            model_name: 模型名稱
            provider: 提供者 (如 "llamacpp"、"openai" 或 "google")

        回傳:
            模型資訊字典
        """
        # 如果提供了 provider，使用組合鍵查詢
        if provider:
            key = f"{provider}:{model_name}"
            if key in self.model_database:
                return self.model_database[key].to_dict()

        # 直接查詢模型資料庫
        for _key, model in self.model_database.items():
            if model.id == model_name:
                return model.to_dict()

        # 嘗試在 OpenAI 預設模型中查找
        openai_models = {
            "gpt-4o": {
                "description": "OpenAI 最強大的翻譯模型，速度快且精確",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要最高品質",
                "parallel": 20,
            },
            "gpt-4-turbo": {
                "description": "強大的翻譯模型，適合需要高品質翻譯的場合",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要高品質",
                "parallel": 15,
            },
            "gpt-4": {
                "description": "強大而穩定的翻譯模型",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要高品質",
                "parallel": 10,
            },
            "gpt-3.5-turbo-16k": {
                "description": "具有較大上下文視窗的翻譯模型",
                "pricing": "中",
                "recommended_for": "包含較多上下文的翻譯",
                "parallel": 25,
            },
            "gpt-3.5-turbo": {
                "description": "平衡經濟性和翻譯品質的模型",
                "pricing": "低",
                "recommended_for": "日常翻譯，最具成本效益",
                "parallel": 30,
            },
        }
        if model_name in openai_models:
            return {"id": model_name, "name": model_name, "provider": "openai", **openai_models[model_name]}
        return {}

    def get_recommended_model(
        self, task_type: str = "translation", provider: str | None = None
    ) -> ModelInfo | None:
        """根據任務類型獲取推薦模型

        參數:
            task_type: 任務類型 (如 "translation", "literary", "technical", "subtitle")
            provider: 提供者 (如 "llamacpp"、"openai" 或 "google")

        回傳:
            推薦的模型資訊，若無適合的則回傳 None
        """
        available_providers = (
            [provider] if provider else self.config.get("default_providers", ["llamacpp", "openai"])
        )

        # 定義不同任務的能力權重
        task_weights = {
            "translation": {"translation": 0.7, "multilingual": 0.2, "context_handling": 0.1},
            "literary": {  # 文學翻譯
                "translation": 0.5,
                "multilingual": 0.2,
                "context_handling": 0.3,
            },
            "technical": {  # 技術文件翻譯
                "translation": 0.6,
                "multilingual": 0.1,
                "context_handling": 0.3,
            },
            "subtitle": {  # 字幕翻譯
                "translation": 0.5,
                "multilingual": 0.3,
                "context_handling": 0.2,
            },
        }

        weights = task_weights.get(task_type, task_weights["translation"])

        # 獲取所有可用模型
        all_models = []
        for provider_name in available_providers:
            for _key, model in self.model_database.items():
                if model.provider == provider_name and model.available:
                    all_models.append(model)

        if not all_models:
            return None

        # 計算每個模型的得分
        scored_models: list[tuple[ModelInfo, float]] = []
        for model in all_models:
            score: float = 0.0
            for capability, weight in weights.items():
                if capability in model.capabilities:
                    score += model.capabilities[capability] * weight

            scored_models.append((model, score))

        # 按得分排序
        scored_models.sort(key=lambda x: x[1], reverse=True)

        # 返回得分最高的模型
        if scored_models:
            return scored_models[0][0]
        return None

    async def _test_openai_connection(self, model_name: str, api_key: str) -> tuple[bool, str]:
        """測試 OpenAI 模型連線

        參數:
            model_name: 模型名稱
            api_key: API 金鑰

        回傳:
            (是否成功, 訊息)
        """
        if not api_key:
            return False, "未提供 API 金鑰"

        if not OPENAI_AVAILABLE:
            return False, "未安裝 OpenAI 客戶端函式庫"

        try:
            client = OpenAI(api_key=api_key)
            response = client.chat.completions.create(
                model=model_name, messages=[{"role": "user", "content": "Hello"}], max_tokens=5
            )

            if response and response.choices and len(response.choices) > 0:
                return True, "模型回應正常"
            else:
                return False, "模型回應格式異常"

        except openai.RateLimitError:
            return False, "達到 API 速率限制，請稍後再試"
        except openai.AuthenticationError:
            return False, "API 金鑰無效或認證失敗"
        except openai.BadRequestError as e:
            if "does not exist" in str(e):
                return False, f"模型 {model_name} 不存在或不可用"
            return False, f"請求錯誤: {e!s}"
        except Exception as e:
            return False, f"測試連線時發生錯誤: {e!s}"

    async def _test_google_connection(self, model_name: str, api_key: str) -> tuple[bool, str]:
        """測試 Google Gemini 模型連線

        參數:
            model_name: 模型名稱
            api_key: API 金鑰

        回傳:
            (是否成功, 訊息)
        """
        if not GOOGLE_AVAILABLE:
            return False, "未安裝 Google GenAI 客戶端程式庫"

        if not api_key:
            return False, "未提供 API 金鑰"

        try:
            with genai.Client(api_key=api_key) as client:
                response = client.models.generate_content(model=model_name, contents="Hello")

                if response and response.text:
                    return True, "模型回應正常"
                else:
                    return False, "模型回應格式異常"

        except Exception as e:
            error_msg = str(e).lower()
            if "authentication" in error_msg or "invalid api key" in error_msg or "api_key" in error_msg:
                return False, "API 金鑰無效或認證失敗"
            elif "rate limit" in error_msg or "quota" in error_msg:
                return False, "達到 API 速率限制，請稍後再試"
            elif "not found" in error_msg or "no such model" in error_msg:
                return False, f"模型 {model_name} 不存在或不可用"
            else:
                return False, f"測試連線時發生錯誤: {e!s}"

    async def _test_llamacpp_connection(self, model_name: str) -> tuple[bool, str]:
        """測試 llama.cpp server 與目前載入模型的可用性。"""
        try:
            await self._init_async_session()
            assert self.session is not None

            base_url = self.llamacpp_url.rstrip("/")
            if base_url.endswith("/v1"):
                base_url = base_url[:-3]

            payload = {
                "model": model_name,
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 5,
                "temperature": 0,
            }
            url = f"{base_url}/v1/chat/completions"

            async with self.session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=15)) as response:
                if response.status == 200:
                    return True, "模型回應正常"

                detail = (await response.text()).strip()
                if detail:
                    return False, f"模型回應失敗: {response.status} - {detail}"
                return False, f"模型回應失敗: {response.status}"

        except asyncio.TimeoutError:
            return False, "連線逾時，請確認 llama-server 已啟動、模型已載入完成，或提高 request_timeout"
        except Exception as e:
            return False, f"連線失敗: {e!s}"

    async def test_model_connection(
        self, model_name: str, provider: str, api_key: str | None = None
    ) -> dict[str, Any]:
        """測試與指定模型的連線

        參數:
            model_name: 模型名稱
            provider: 提供者 (如 "openai"、"google" 或 "llamacpp")
            api_key: API 金鑰 (可選)

        回傳:
            測試結果字典，包含 success 和 message 欄位
        """
        if provider == "openai":
            key = api_key or self.api_keys.get("openai", "")
            success, message = await self._test_openai_connection(model_name, key)
            return {"success": success, "message": message}
        elif provider == "google":
            key = api_key or self.api_keys.get("google", "")
            success, message = await self._test_google_connection(model_name, key)
            return {"success": success, "message": message}
        elif provider == "llamacpp":
            success, message = await self._test_llamacpp_connection(model_name)
            return {"success": success, "message": message}
        else:
            return {"success": False, "message": f"不支援的提供者: {provider}"}

    async def get_provider_status(self) -> dict[str, bool]:
        """獲取各提供者的連線狀態

        回傳:
            包含各提供者狀態的字典
        """
        status = {"openai": False, "google": False, "llamacpp": False}

        # 其他提供者需要 API 金鑰，檢查是否有有效金鑰和客戶端庫
        status["openai"] = OPENAI_AVAILABLE and bool(self.api_keys.get("openai"))
        status["google"] = GOOGLE_AVAILABLE and bool(self.api_keys.get("google"))
        try:
            success, _message = await self._test_llamacpp_connection(self.default_llamacpp_model)
            status["llamacpp"] = success
        except Exception:
            status["llamacpp"] = False

        return status

    async def __aenter__(self):
        """非同步上下文管理器入口"""
        await self._init_async_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同步上下文管理器退出"""
        await self._close_async_session()

    async def _get_llamacpp_models_async(self) -> list[ModelInfo]:
        """非同步獲取 llama.cpp server 載入的模型

        透過 /props、/slots 與 /v1/models 端點查詢 llama-server 目前狀態。

        回傳:
            ModelInfo 物件列表（通常只有一個模型）
        """
        try:
            await self._init_async_session()

            base_url = self.llamacpp_url.rstrip("/")
            if base_url.endswith("/v1"):
                base_url = base_url[:-3]

            async def fetch_json(endpoint: str) -> Any | None:
                url = f"{base_url}{endpoint}"
                logger.debug(f"嘗試從 {url} 讀取 llama.cpp 狀態")
                assert self.session is not None
                async with self.session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as response:
                    if response.status != 200:
                        logger.debug(f"llama.cpp {endpoint} 返回狀態碼: {response.status}")
                        return None
                    return await response.json()

            props = await fetch_json("/props")
            slots = await fetch_json("/slots")
            result = await fetch_json("/v1/models")

            props_data = props if isinstance(props, dict) else {}
            slots_data = slots if isinstance(slots, list) else []
            models = result.get("data", []) if isinstance(result, dict) else []

            total_slots = props_data.get("total_slots")
            if not isinstance(total_slots, int) or total_slots <= 0:
                total_slots = len(slots_data) if slots_data else 1

            default_generation_settings = props_data.get("default_generation_settings", {})
            slot_n_ctx = (
                default_generation_settings.get("n_ctx")
                if isinstance(default_generation_settings, dict)
                else None
            )
            if (not isinstance(slot_n_ctx, int) or slot_n_ctx <= 0) and slots_data and isinstance(slots_data[0], dict):
                slot_n_ctx = slots_data[0].get("n_ctx")
            if not isinstance(slot_n_ctx, int) or slot_n_ctx <= 0:
                slot_n_ctx = 4096

            build_info = props_data.get("build_info", "")
            if isinstance(build_info, str) and build_info:
                logger.info(f"llama.cpp server 版本: {build_info}")

            model_path = props_data.get("model_path", "")
            if not models and model_path:
                models = [{"id": Path(model_path).name, "meta": {}}]

            if not models:
                logger.warning("llama-server 未回報任何模型資訊")
                return self._get_llamacpp_fallback_models()

            model_info_list = []
            for model_data in models:
                model_id = str(model_data.get("id") or Path(model_path).name or "unknown")
                display_source = model_path if isinstance(model_path, str) and model_path else model_id
                display_name = Path(display_source).stem if "/" in display_source or "\\" in display_source else display_source

                meta = model_data.get("meta", {})
                n_params = meta.get("n_params", 0) if isinstance(meta, dict) else 0
                n_ctx_train = meta.get("n_ctx_train", slot_n_ctx) if isinstance(meta, dict) else slot_n_ctx

                param_str = ""
                if isinstance(n_params, int) and n_params > 0:
                    if n_params >= 1_000_000_000:
                        param_str = f"{n_params / 1_000_000_000:.1f}B"
                    elif n_params >= 1_000_000:
                        param_str = f"{n_params / 1_000_000:.0f}M"

                description_parts = []
                if param_str:
                    description_parts.append(f"{param_str} 參數")
                if total_slots > 0:
                    description_parts.append(f"{total_slots} 個並行槽")

                description = "llama.cpp 本地模型"
                if description_parts:
                    description += f"（{'，'.join(description_parts)}）"

                model_info = ModelInfo(
                    id=model_id,
                    provider="llamacpp",
                    name=display_name,
                    description=description,
                    context_length=slot_n_ctx,
                    pricing="免費(本機執行)",
                    recommended_for="本地高速推理翻譯",
                    parallel=total_slots,
                    tags=["free", "local", "llamacpp"],
                    capabilities={
                        "translation": 0.85,
                        "multilingual": 0.80,
                        "context_handling": 0.85 if isinstance(n_ctx_train, int) and n_ctx_train >= 32768 else 0.80,
                    },
                )
                model_info_list.append(model_info)

            logger.info(f"檢測到 {len(model_info_list)} 個 llama.cpp 模型（server slots: {total_slots}）")
            return model_info_list

        except Exception as e:
            logger.error(f"獲取 llama.cpp 模型列表失敗: {e!s}")
            return self._get_llamacpp_fallback_models()

    def _get_llamacpp_fallback_models(self) -> list[ModelInfo]:
        """當 llama-server 無法連線時返回提示模型"""
        return [
            ModelInfo(
                id="llama-server-offline",
                provider="llamacpp",
                name="llama-server (未連線)",
                description=(
                    "請先啟動 llama-server："
                    "llama-server -m <model.gguf> --jinja --parallel 1 -c 1024 --cache-ram 4096"
                    "；Qwen3.5 建議加 --reasoning-format deepseek，"
                    "Gemma 4 建議改用 --reasoning off --reasoning-format none"
                ),
                context_length=1024,
                pricing="免費(本機執行)",
                recommended_for="本地高速推理翻譯",
                parallel=1,
                tags=["free", "local", "llamacpp"],
                capabilities={"translation": 0.0, "multilingual": 0.0, "context_handling": 0.0},
                available=False,
            )
        ]

    def _format_model_name(self, model_id: str) -> str:
        """格式化模型名稱，使其更易讀

        參數:
            model_id: 模型ID

        回傳:
            格式化後的模型名稱
        """
        try:
            # 移除版本號和標籤
            name = re.sub(r"[:@].+", "", model_id)

            # 處理常見縮寫
            name = name.replace("-", " ").replace("_", " ")

            # 分割路徑，只取最後部分
            parts = name.split("/")
            name = parts[-1]

            # 首字母大寫
            words = name.split()
            capitalized = []
            for word in words:
                # 處理駝峰命名
                camel_parts = re.findall(r"[A-Z][a-z]*|[a-z]+", word)
                camel_parts = [p.capitalize() for p in camel_parts]
                capitalized.append(" ".join(camel_parts))

            return " ".join(capitalized)
        except Exception:
            return model_id

    async def _get_openai_models_async(self, api_key: str) -> list[ModelInfo]:
        """非同步獲取 OpenAI 模型列表

        參數:
            api_key: OpenAI API金鑰

        回傳:
            OpenAI ModelInfo物件列表
        """
        if not api_key:
            logger.warning("未提供 OpenAI API 金鑰")
            # 返回預設模型
            default_model = self._create_default_openai_model()
            return [default_model]

        if not OPENAI_AVAILABLE:
            logger.warning("未安裝 OpenAI 客戶端函式庫")
            default_model = self._create_default_openai_model()
            return [default_model]

        try:
            # 使用同步客戶端 - 未來可改為非同步
            client = OpenAI(api_key=api_key)
            models_response = client.models.list()

            # 優先推薦適合翻譯的模型
            translation_priority = {
                "gpt-4o": 1,
                "gpt-4-turbo": 2,
                "gpt-4": 3,
                "gpt-3.5-turbo-16k": 4,
                "gpt-3.5-turbo": 5,
                "gpt-4-vision-preview": 999,
            }

            # 過濾模型
            model_list = []
            for model in models_response:
                # 只包含 GPT 系列，且排除日期版本(如 gpt-3.5-turbo-0301)
                if "gpt" in model.id and not re.search(r"-\d{4}$", model.id):
                    key = f"openai:{model.id}"
                    if key in self.model_database:
                        model_info = self.model_database[key]
                    else:
                        # 建立新的模型資訊
                        model_info = ModelInfo(
                            id=model.id,
                            provider="openai",
                            name=self._format_model_name(model.id),
                            description="OpenAI 模型",
                            pricing="中",
                            recommended_for="一般翻譯任務",
                            parallel=10,
                        )

                    model_list.append(model_info)

            # 按翻譯優先級排序
            model_list.sort(key=lambda x: translation_priority.get(x.id, 900))

            # 確保列表中有最常用的模型
            essential_models = ["gpt-3.5-turbo", "gpt-4"]
            for model_id in essential_models:
                if not any(m.id == model_id for m in model_list):
                    key = f"openai:{model_id}"
                    if key in self.model_database:
                        model_info = self.model_database[key]
                    else:
                        model_info = ModelInfo(
                            id=model_id,
                            provider="openai",
                            name=self._format_model_name(model_id),
                            description="OpenAI 模型",
                            pricing="中" if "gpt-4" in model_id else "低",
                            recommended_for="一般翻譯任務",
                        )
                    model_list.append(model_info)

            logger.info(f"檢測到 {len(model_list)} 個 OpenAI 模型")
            return model_list

        except Exception as e:
            logger.error(f"獲取 OpenAI 模型列表失敗: {e!s}")
            # 返回預設模型
            default_model = self._create_default_openai_model()
            return [default_model]

    def update_config(self, new_config: dict[str, Any]) -> bool:
        """更新模型管理器配置

        參數:
            new_config: 新的配置項字典

        回傳:
            是否更新成功
        """
        try:
            # 更新配置
            for key, value in new_config.items():
                if key in self.config:
                    self.config[key] = value

            # 儲存配置
            save_result = self._save_config()

            # 如果更新了重要設定，清除快取
            important_keys = ["llamacpp_url", "default_llamacpp_model", "model_patterns"]
            if any(key in new_config for key in important_keys):
                self.cached_models.clear()
                self.cache_time.clear()

            logger.info("已更新模型管理器配置")
            return save_result
        except Exception as e:
            logger.error(f"更新模型管理器配置時發生錯誤: {e!s}")
            return False


# 提供便捷的全域函數
def get_model_info(model_name: str, provider: str | None = None) -> dict[str, Any]:
    """全域函數：獲取模型資訊

    參數:
        model_name: 模型名稱
        provider: 提供者 (如 "llamacpp" 或 "openai")

    回傳:
        模型資訊字典
    """
    manager = ModelManager.get_instance()
    return manager.get_model_info(model_name, provider)


def get_recommended_model(task_type: str = "translation", provider: str | None = None) -> str:
    """全域函數：根據任務類型獲取推薦模型

    參數:
        task_type: 任務類型 (如 "translation" 或 "literary")
        provider: 提供者 (如 "llamacpp" 或 "openai")

    回傳:
        推薦的模型名稱
    """
    manager = ModelManager.get_instance()
    model_info = manager.get_recommended_model(task_type, provider)
    if model_info:
        return model_info.id
    return manager.get_default_model(provider or "llamacpp")


async def test_model_connection(model_name: str, provider: str, api_key: str | None = None) -> dict[str, Any]:
    """全域函數：測試與模型的連線

    參數:
        model_name: 模型名稱
        provider: 提供者 (如 "llamacpp", "openai" 或 "google")
        api_key: API 金鑰 (可選)

    回傳:
        測試結果字典
    """
    manager = ModelManager.get_instance()
    try:
        return await manager.test_model_connection(model_name, provider, api_key)
    finally:
        await manager._close_async_session()
