import json
import os
import aiohttp
import asyncio
import urllib.request
from typing import List, Dict, Optional, Any, Union, Tuple, Set
import time
import logging
import re
from logging.handlers import TimedRotatingFileHandler
from dataclasses import dataclass, field
import threading

# 嘗試匯入所有可能的 LLM 客戶端
try:
    import openai
    from openai import OpenAI, AsyncOpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False

try:
    import anthropic
    ANTHROPIC_AVAILABLE = True
except ImportError:
    ANTHROPIC_AVAILABLE = False

# 從配置管理器導入
from srt_translator.core.config import ConfigManager, get_config, set_config
from srt_translator.utils import AppError, ModelError, format_exception, safe_execute

# 設定日誌
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 確保日誌目錄存在
os.makedirs('logs', exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = TimedRotatingFileHandler(
        filename='logs/model_manager.log',
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

@dataclass
class ModelInfo:
    """模型資訊資料類別"""
    id: str  # 模型 ID/名稱
    provider: str  # 提供者(ollama, openai 等)
    name: str = ""  # 顯示名稱(如不同於 ID)
    description: str = ""  # 模型描述
    context_length: int = 4096  # 上下文長度
    pricing: str = "未知"  # 價格描述
    recommended_for: str = "一般翻譯"  # 推薦用途
    parallel: int = 10  # 建議並行數量
    tags: List[str] = field(default_factory=list)  # 模型標籤
    capabilities: Dict[str, float] = field(default_factory=dict)  # 能力評分(0-1)
    available: bool = True  # 是否可用
    
    def to_dict(self) -> Dict[str, Any]:
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
            "available": self.available
        }
    
    async def test_model_connection(self, model_name: str, provider: str, api_key: str = None) -> Dict[str, Any]:
        """測試與模型的連線
        
        參數:
            model_name: 模型名稱
            provider: 提供者 (如 "ollama", "openai" 或 "anthropic")
            api_key: API 金鑰 (可選)
            
        回傳:
            測試結果字典，包含成功與否、回應時間和錯誤訊息
        """
        result = {
            "success": False,
            "message": "",
            "response_time": None,
            "error": None
        }
        
        try:
            start_time = time.time()
            
            # 如果沒有提供 API 金鑰，使用已存的金鑰
            if api_key is None:
                api_key = self.api_keys.get(provider)
            
            if provider == "ollama":
                success, message = await self._test_ollama_connection(model_name)
            elif provider == "openai":
                success, message = await self._test_openai_connection(model_name, api_key)
            elif provider == "anthropic":
                success, message = await self._test_anthropic_connection(model_name, api_key)
            else:
                success = False
                message = f"不支援的提供者: {provider}"
                
            end_time = time.time()
            result["success"] = success
            result["message"] = message
            
            if success:
                result["response_time"] = round(end_time - start_time, 2)
                
            return result
        except Exception as e:
            logger.error(f"測試模型連線時發生錯誤: {str(e)}")
            result["success"] = False
            result["message"] = f"測試過程中發生錯誤: {str(e)}"
            result["error"] = str(e)
            return result
    
    async def _test_ollama_connection(self, model_name: str) -> Tuple[bool, str]:
        """測試 Ollama 模型連線
        
        參數:
            model_name: 模型名稱
            
        回傳:
            (是否成功, 訊息)
        """
        if not self.session:
            await self._init_async_session()
            
        try:
            # 建構一個簡單的請求
            payload = {
                "model": model_name,
                "prompt": "你好",
                "stream": False
            }
            
            url = f"{self.base_url}/api/generate"
            async with self.session.post(url, json=payload, timeout=10) as response:
                if response.status != 200:
                    return False, f"API 返回非 200 狀態碼: {response.status}"
                    
                result = await response.json()
                if 'response' in result and result['response']:
                    return True, "模型回應正常"
                else:
                    return False, "模型回應格式異常"
                    
        except aiohttp.ClientConnectorError:
            return False, "無法連線到 Ollama 伺服器，請確保 Ollama 正在執行"
        except asyncio.TimeoutError:
            return False, "連線逾時，Ollama 伺服器回應時間過長"
        except Exception as e:
            return False, f"測試連線時發生錯誤: {str(e)}"
    
    def set_default_ollama_model(self, model_name: str) -> bool:
        """設置預設的 Ollama 模型
        
        參數:
            model_name: 模型名稱
            
        回傳:
            是否設置成功
        """
        try:
            self.default_ollama_model = model_name
            self.config["default_ollama_model"] = model_name
            
            # 清除 Ollama 模型快取
            if "ollama" in self.cached_models:
                del self.cached_models["ollama"]
                if "ollama" in self.cache_time:
                    del self.cache_time["ollama"]
            
            # 儲存配置
            save_result = self._save_config()
            
            logger.info(f"已設置預設 Ollama 模型為: {model_name}")
            return save_result
        except Exception as e:
            logger.error(f"設置預設 Ollama 模型時發生錯誤: {str(e)}")
            return False
    
    def cleanup(self) -> None:
        """釋放資源，通常在應用程式關閉時呼叫"""
        # 使用新的 event_loop 來執行非同步清理方法
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self._close_async_session())
        finally:
            loop.close()
            
        # 清除快取
        self.cached_models.clear()
        self.cache_time.clear()
        
        logger.info("模型管理器資源已釋放")

class ModelManager:
    """模型管理器，負責管理、載入和監控不同的大型語言模型"""
    
    # 類變數，用於實現單例模式
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(cls, config_file: str = None) -> 'ModelManager':
        """獲取模型管理器的單例實例
        
        參數:
            config_file: 配置檔案路徑，若為None則使用預設路徑
            
        回傳:
            模型管理器實例
        """
        with cls._lock:
            if cls._instance is None:
                # 如果沒有指定config_file，從配置獲取
                if config_file is None:
                    config_file = get_config("model", "config_file", "config/model_config.json")
                
                cls._instance = ModelManager(config_file)
            return cls._instance
    
    def __init__(self, config_file: str = "config/model_config.json"):
        """初始化模型管理器
        
        參數:
            config_file: 配置檔案路徑
        """
        self.config_file = config_file
        
        # 獲取配置管理器實例
        self.config_manager = ConfigManager.get_instance("model")
        
        # 從配置載入模型設定
        self.config = self._load_config()
        
        # Ollama 設定
        self.base_url = self.config.get("ollama_url", "http://localhost:11434")
        self.default_ollama_model = self.config.get("default_ollama_model", "llama3")
        
        # 常見模型模式，用於過濾
        self.model_patterns = self.config.get("model_patterns", [
            'llama', 'mixtral', 'aya', 'yi', 'qwen', 'solar',
            'mistral', 'openchat', 'neural', 'phi', 'stable',
            'dolphin', 'vicuna', 'zephyr', 'gemma', 'deepseek'
        ])
        
        # 快取設定
        self.cached_models: Dict[str, List[ModelInfo]] = {}
        self.cache_time: Dict[str, float] = {}
        self.cache_expiry = self.config.get("cache_expiry", 600)  # 10 分鐘快取過期
        
        # 用於測試 API 的逾時設定
        self.connect_timeout = self.config.get("connect_timeout", 5)
        self.request_timeout = self.config.get("request_timeout", 10)
        
        # 非同步 HTTP 客戶端
        self.session = None
        self._session_lock = asyncio.Lock()
        
        # API 金鑰集合
        self.api_keys = {}
        
        # 初始化模型資訊庫
        self._init_model_info_database()
        
        # 載入 API 金鑰
        self._load_api_keys()
        
        logger.info(f"ModelManager 初始化完成，預設 Ollama 模型: {self.default_ollama_model}")
    
    def _load_config(self) -> Dict[str, Any]:
        """從配置管理器載入設定"""
        return self.config_manager.get_config()
    
    def _save_config(self) -> bool:
        """儲存設定到配置管理器"""
        for key, value in self.config.items():
            self.config_manager.set_value(key, value, auto_save=False)
        return self.config_manager.save_config()
    
    def _load_api_keys(self) -> None:
        """載入各種服務的 API 金鑰"""
        # 載入 OpenAI API 金鑰
        try:
            openai_key_path = get_config("app", "openai_key_path", "openapi_api_key.txt")
            if os.path.exists(openai_key_path):
                with open(openai_key_path, 'r', encoding='utf-8') as f:
                    self.api_keys["openai"] = f.read().strip()
                logger.info("已載入 OpenAI API 金鑰")
            else:
                logger.warning(f"OpenAI API 金鑰檔案不存在: {openai_key_path}")
        except Exception as e:
            logger.error(f"載入 OpenAI API 金鑰時發生錯誤: {str(e)}")
        
        # 載入 Anthropic API 金鑰 (如果配置了)
        try:
            anthropic_key_path = get_config("app", "anthropic_key_path", "anthropic_api_key.txt")
            if os.path.exists(anthropic_key_path):
                with open(anthropic_key_path, 'r', encoding='utf-8') as f:
                    self.api_keys["anthropic"] = f.read().strip()
                logger.info("已載入 Anthropic API 金鑰")
        except Exception as e:
            logger.error(f"載入 Anthropic API 金鑰時發生錯誤: {str(e)}")
    
    def _init_model_info_database(self) -> None:
        """初始化模型資訊資料庫"""
        self.model_database: Dict[str, ModelInfo] = {}
        
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
                capabilities={
                    "translation": 0.98,
                    "multilingual": 0.99,
                    "context_handling": 0.98
                }
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
                capabilities={
                    "translation": 0.96,
                    "multilingual": 0.95,
                    "context_handling": 0.96
                }
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
                capabilities={
                    "translation": 0.94,
                    "multilingual": 0.93,
                    "context_handling": 0.95
                }
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
                capabilities={
                    "translation": 0.88,
                    "multilingual": 0.86,
                    "context_handling": 0.90
                }
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
                capabilities={
                    "translation": 0.85,
                    "multilingual": 0.84,
                    "context_handling": 0.82
                }
            )
        }
        
        # Ollama 常用模型資訊
        ollama_models = {
            "llama3": ModelInfo(
                id="llama3",
                provider="ollama",
                name="Llama 3",
                description="Meta 的最新開源大語言模型，適合多語言翻譯",
                context_length=8192,
                pricing="免費(本機執行)",
                recommended_for="一般翻譯任務，具有良好的多語言能力",
                parallel=2,
                tags=["free", "local", "multilingual"],
                capabilities={
                    "translation": 0.82,
                    "multilingual": 0.78,
                    "context_handling": 0.80
                }
            ),
            "mixtral": ModelInfo(
                id="mixtral",
                provider="ollama",
                name="Mixtral",
                description="Mistral AI 的混合專家模型，具有優秀的多語言能力",
                context_length=32768,
                pricing="免費(本機執行)",
                recommended_for="需要處理長上下文的翻譯任務",
                parallel=1,
                tags=["free", "local", "extended_context"],
                capabilities={
                    "translation": 0.84,
                    "multilingual": 0.80,
                    "context_handling": 0.88
                }
            ),
            "mistral": ModelInfo(
                id="mistral",
                provider="ollama",
                name="Mistral",
                description="輕量級高效能模型，適合快速翻譯",
                context_length=8192,
                pricing="免費(本機執行)",
                recommended_for="需要快速處理的翻譯任務",
                parallel=2,
                tags=["free", "local", "fast"],
                capabilities={
                    "translation": 0.78,
                    "multilingual": 0.75,
                    "context_handling": 0.76
                }
            ),
            "qwen": ModelInfo(
                id="qwen",
                provider="ollama",
                name="Qwen",
                description="阿里雲開發的模型，對中文支援較好",
                context_length=8192,
                pricing="免費(本機執行)",
                recommended_for="中文翻譯任務",
                parallel=2,
                tags=["free", "local", "chinese"],
                capabilities={
                    "translation": 0.80,
                    "multilingual": 0.75,
                    "context_handling": 0.78,
                    "chinese": 0.90
                }
            ),
            "deepseek": ModelInfo(
                id="deepseek",
                provider="ollama",
                name="DeepSeek",
                description="專注於深度理解的模型，適合文學翻譯",
                context_length=8192,
                pricing="免費(本機執行)",
                recommended_for="文學或專業領域翻譯",
                parallel=1,
                tags=["free", "local", "specialized"],
                capabilities={
                    "translation": 0.83,
                    "multilingual": 0.76,
                    "context_handling": 0.85
                }
            )
        }
        
        # Anthropic 模型資訊
        anthropic_models = {
            "claude-3-opus-20240229": ModelInfo(
                id="claude-3-opus-20240229",
                provider="anthropic",
                name="Claude 3 Opus",
                description="Anthropic 最強大的模型，適合高品質翻譯",
                context_length=200000,
                pricing="高",
                recommended_for="專業翻譯、文學翻譯",
                parallel=10,
                tags=["advanced", "accurate"],
                capabilities={
                    "translation": 0.98,
                    "multilingual": 0.97,
                    "context_handling": 0.99
                }
            ),
            "claude-3-sonnet-20240229": ModelInfo(
                id="claude-3-sonnet-20240229",
                provider="anthropic",
                name="Claude 3 Sonnet",
                description="Anthropic 平衡型模型，效能和速度的良好平衡",
                context_length=200000,
                pricing="中",
                recommended_for="一般翻譯任務",
                parallel=15,
                tags=["balanced", "fast"],
                capabilities={
                    "translation": 0.93,
                    "multilingual": 0.92,
                    "context_handling": 0.94
                }
            ),
            "claude-3-haiku-20240307": ModelInfo(
                id="claude-3-haiku-20240307",
                provider="anthropic",
                name="Claude 3 Haiku",
                description="Anthropic 最快速的模型，適合大量翻譯任務",
                context_length=200000,
                pricing="低",
                recommended_for="大批量翻譯任務",
                parallel=25,
                tags=["fast", "economic"],
                capabilities={
                    "translation": 0.88,
                    "multilingual": 0.86,
                    "context_handling": 0.87
                }
            )
        }
        
        # 合併所有模型資訊到資料庫
        for model in openai_models.values():
            self.model_database[f"openai:{model.id}"] = model
        
        for model in ollama_models.values():
            self.model_database[f"ollama:{model.id}"] = model
            
        for model in anthropic_models.values():
            self.model_database[f"anthropic:{model.id}"] = model
    
    async def _init_async_session(self) -> None:
        """初始化非同步 HTTP 客戶端"""
        async with self._session_lock:
            if self.session is None:
                timeout = aiohttp.ClientTimeout(
                    total=self.request_timeout,
                    connect=self.connect_timeout,
                    sock_connect=self.connect_timeout,
                    sock_read=self.request_timeout
                )
                self.session = aiohttp.ClientSession(timeout=timeout)
                logger.debug("已初始化非同步 HTTP 客戶端")

    async def _close_async_session(self) -> None:
        """關閉非同步 HTTP 客戶端"""
        async with self._session_lock:
            if self.session:
                await self.session.close()
                self.session = None
                logger.debug("已關閉非同步 HTTP 客戶端")

    async def get_model_list_async(self, llm_type: str, api_key: str = None) -> List[ModelInfo]:
        """非同步獲取模型列表
        
        參數:
            llm_type: LLM類型 (如 "ollama" 或 "openai")
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
            if llm_type == "ollama":
                models = await self._get_ollama_models_async()
            elif llm_type == "openai":
                models = await self._get_openai_models_async(api_key)
            elif llm_type == "anthropic" and ANTHROPIC_AVAILABLE:
                models = await self._get_anthropic_models_async(api_key)
            else:
                logger.warning(f"不支援的 LLM 類型: {llm_type}，返回空列表")
                models = []
            
            # 更新快取
            self.cached_models[llm_type] = models
            self.cache_time[llm_type] = time.time()
            
            return models
            
        except Exception as e:
            logger.error(f"獲取模型列表失敗: {str(e)}")
            # 如果之前有快取，使用過期快取
            if llm_type in self.cached_models:
                logger.info(f"使用過期快取的模型列表")
                return self.cached_models[llm_type]
            
            # 返回預設模型
            if llm_type == "ollama":
                default_model = self._create_default_ollama_model()
                return [default_model]
            elif llm_type == "openai":
                default_model = self._create_default_openai_model()
                return [default_model]
            elif llm_type == "anthropic":
                default_model = self._create_default_anthropic_model()
                return [default_model]
            
            return []
    
    def get_model_list(self, llm_type: str, api_key: str = None) -> List[str]:
        """同步獲取模型列表(字串列表版本，向後相容)
        
        參數:
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            api_key: API金鑰 (可選)
            
        回傳:
            模型名稱字串列表
        """
        # 使用新的 event_loop 來執行非同步方法
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            model_infos = loop.run_until_complete(self.get_model_list_async(llm_type, api_key))
            # 轉換為字串列表，保持向後相容
            return [model.id for model in model_infos]
        finally:
            loop.close()
    
    def _create_default_ollama_model(self) -> ModelInfo:
        """建立預設 Ollama 模型"""
        key = f"ollama:{self.default_ollama_model}"
        if key in self.model_database:
            model = self.model_database[key]
        else:
            model = ModelInfo(
                id=self.default_ollama_model,
                provider="ollama",
                name=self.default_ollama_model.capitalize(),
                description="預設 Ollama 模型",
                pricing="免費(本機執行)",
                recommended_for="一般翻譯任務"
            )
        return model
    
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
                recommended_for="一般翻譯任務"
            )
        return model
        
    def _create_default_anthropic_model(self) -> ModelInfo:
        """建立預設 Anthropic 模型"""
        key = "anthropic:claude-3-haiku-20240307"
        if key in self.model_database:
            model = self.model_database[key]
        else:
            model = ModelInfo(
                id="claude-3-haiku-20240307",
                provider="anthropic",
                name="Claude 3 Haiku",
                description="Anthropic 的快速模型",
                pricing="低",
                recommended_for="一般翻譯任務"
            )
        return model

    async def _get_anthropic_models_async(self, api_key: str) -> List[ModelInfo]:
        """非同步獲取 Anthropic 模型列表
        
        參數:
            api_key: Anthropic API金鑰
            
        回傳:
            Anthropic ModelInfo物件列表
        """
        if not ANTHROPIC_AVAILABLE or not api_key:
            return []
            
        try:
            # Anthropic 沒有列出模型的 API，使用預定義模型
            anthropic_models = [
                ModelInfo(
                    id="claude-3-opus-20240229",
                    provider="anthropic",
                    name="Claude 3 Opus",
                    description="Anthropic 最強大的模型，適合高品質翻譯",
                    context_length=200000,
                    pricing="高",
                    recommended_for="專業翻譯、文學翻譯",
                    parallel=10,
                    tags=["advanced", "accurate"],
                    capabilities={
                        "translation": 0.98,
                        "multilingual": 0.97,
                        "context_handling": 0.99
                    }
                ),
                ModelInfo(
                    id="claude-3-sonnet-20240229",
                    provider="anthropic",
                    name="Claude 3 Sonnet",
                    description="Anthropic 平衡型模型，效能和速度的良好平衡",
                    context_length=200000,
                    pricing="中",
                    recommended_for="一般翻譯任務",
                    parallel=15,
                    tags=["balanced", "fast"],
                    capabilities={
                        "translation": 0.93,
                        "multilingual": 0.92,
                        "context_handling": 0.94
                    }
                ),
                ModelInfo(
                    id="claude-3-haiku-20240307",
                    provider="anthropic",
                    name="Claude 3 Haiku",
                    description="Anthropic 最快速的模型，適合大量翻譯任務",
                    context_length=200000,
                    pricing="低",
                    recommended_for="大批量翻譯任務",
                    parallel=25,
                    tags=["fast", "economic"],
                    capabilities={
                        "translation": 0.88,
                        "multilingual": 0.86,
                        "context_handling": 0.87
                    }
                )
            ]
            
            # 驗證 API 金鑰是否有效
            client = anthropic.Anthropic(api_key=api_key)
            try:
                # 簡單呼叫以驗證 API 金鑰
                response = client.messages.create(
                    model="claude-3-haiku-20240307",
                    max_tokens=10,
                    messages=[{"role": "user", "content": "Hi"}]
                )
                # 呼叫成功，API 金鑰有效
                for model in anthropic_models:
                    model.available = True
            except Exception as e:
                logger.warning(f"Anthropic API 金鑰驗證失敗: {str(e)}")
                # 標記所有模型為不可用
                for model in anthropic_models:
                    model.available = False
            
            return anthropic_models
        except Exception as e:
            logger.error(f"獲取 Anthropic 模型列表失敗: {str(e)}")
            return []

    def get_default_model(self, llm_type: str) -> str:
        """返回預設模型，針對翻譯進行最佳化
        
        參數:
            llm_type: LLM類型 (如 "ollama", "openai" 或 "anthropic")
            
        回傳:
            預設模型名稱
        """
        if llm_type == "openai":
            return "gpt-3.5-turbo"  # 最經濟的選擇
        elif llm_type == "anthropic":
            return "claude-3-haiku-20240307"  # 最快速的選擇
        return self.default_ollama_model
    
    def get_model_info(self, model_name: str, provider: str = None) -> Dict[str, Any]:
        """獲取模型的詳細資訊
        
        參數:
            model_name: 模型名稱
            provider: 提供者 (如 "ollama" 或 "openai")
            
        回傳:
            模型資訊字典
        """
        # 如果提供了 provider，使用組合鍵查詢
        if provider:
            key = f"{provider}:{model_name}"
            if key in self.model_database:
                return self.model_database[key].to_dict()
        
        # 直接查詢模型資料庫
        for key, model in self.model_database.items():
            if model.id == model_name:
                return model.to_dict()
        
        # 嘗試在 OpenAI 預設模型中查找
        openai_models = {
            "gpt-4o": {
                "description": "OpenAI 最強大的翻譯模型，速度快且精確",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要最高品質",
                "parallel": 20
            },
            "gpt-4-turbo": {
                "description": "強大的翻譯模型，適合需要高品質翻譯的場合",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要高品質",
                "parallel": 15
            },
            "gpt-4": {
                "description": "強大而穩定的翻譯模型",
                "pricing": "高",
                "recommended_for": "專業翻譯，需要高品質",
                "parallel": 10
            },
            "gpt-3.5-turbo-16k": {
                "description": "具有較大上下文視窗的翻譯模型",
                "pricing": "中",
                "recommended_for": "包含較多上下文的翻譯",
                "parallel": 25
            },
            "gpt-3.5-turbo": {
                "description": "平衡經濟性和翻譯品質的模型",
                "pricing": "低",
                "recommended_for": "日常翻譯，最具成本效益",
                "parallel": 30
            }
        }
        if model_name in openai_models:
            return {
                "id": model_name,
                "name": model_name,
                "provider": "openai",
                **openai_models[model_name]
            }
        return {}

    def get_recommended_model(self, task_type: str = "translation", provider: str = None) -> Optional[ModelInfo]:
        """根據任務類型獲取推薦模型
        
        參數:
            task_type: 任務類型 (如 "translation", "literary", "technical", "subtitle")
            provider: 提供者 (如 "ollama", "openai" 或 "anthropic")
            
        回傳:
            推薦的模型資訊，若無適合的則回傳 None
        """
        available_providers = [provider] if provider else self.config.get("default_providers", ["ollama", "openai", "anthropic"])
        
        # 定義不同任務的能力權重
        task_weights = {
            "translation": {
                "translation": 0.7,
                "multilingual": 0.2,
                "context_handling": 0.1
            },
            "literary": {  # 文學翻譯
                "translation": 0.5,
                "multilingual": 0.2,
                "context_handling": 0.3
            },
            "technical": {  # 技術文件翻譯
                "translation": 0.6,
                "multilingual": 0.1,
                "context_handling": 0.3
            },
            "subtitle": {  # 字幕翻譯
                "translation": 0.5,
                "multilingual": 0.3,
                "context_handling": 0.2
            }
        }
        
        weights = task_weights.get(task_type, task_weights["translation"])
        
        # 獲取所有可用模型
        all_models = []
        for provider_name in available_providers:
            for key, model in self.model_database.items():
                if model.provider == provider_name and model.available:
                    all_models.append(model)
        
        if not all_models:
            return None
        
        # 計算每個模型的得分
        scored_models = []
        for model in all_models:
            score = 0
            for capability, weight in weights.items():
                if capability in model.capabilities:
                    score += model.capabilities[capability] * weight
            
            # 根據提供者調整得分
            if model.provider == "ollama":
                # Ollama 是本機執行，在沒有指定提供者時降低評分以優先使用雲端服務
                if provider is None:
                    score *= 0.85
                
            scored_models.append((model, score))
            
        # 按得分排序
        scored_models.sort(key=lambda x: x[1], reverse=True)
        
        # 返回得分最高的模型
        if scored_models:
            return scored_models[0][0]
        return None
    
    async def _test_openai_connection(self, model_name: str, api_key: str) -> Tuple[bool, str]:
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
                model=model_name,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5
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
            return False, f"請求錯誤: {str(e)}"
        except Exception as e:
            return False, f"測試連線時發生錯誤: {str(e)}"
    
    async def _test_anthropic_connection(self, model_name: str, api_key: str) -> Tuple[bool, str]:
        """測試 Anthropic 模型連線
        
        參數:
            model_name: 模型名稱
            api_key: API 金鑰
            
        回傳:
            (是否成功, 訊息)
        """
        if not ANTHROPIC_AVAILABLE:
            return False, "未安裝 Anthropic 客戶端程式庫"
            
        if not api_key:
            return False, "未提供 API 金鑰"
            
        try:
            client = anthropic.Anthropic(api_key=api_key)
            response = client.messages.create(
                model=model_name,
                max_tokens=10,
                messages=[{"role": "user", "content": "Hello"}]
            )
            
            if response and response.content:
                return True, "模型回應正常"
            else:
                return False, "模型回應格式異常"
                
        except Exception as e:
            error_msg = str(e).lower()
            if "authentication" in error_msg or "invalid api key" in error_msg:
                return False, "API 金鑰無效或認證失敗"
            elif "rate limit" in error_msg:
                return False, "達到 API 速率限制，請稍後再試"
            elif "not found" in error_msg or "no such model" in error_msg:
                return False, f"模型 {model_name} 不存在或不可用"
            else:
                return False, f"測試連線時發生錯誤: {str(e)}"
    
    async def get_provider_status(self) -> Dict[str, bool]:
        """獲取各提供者的連線狀態
        
        回傳:
            包含各提供者狀態的字典
        """
        status = {
            "ollama": False,
            "openai": False,
            "anthropic": False
        }
        
        # 檢查 Ollama 連線
        try:
            if not self.session:
                await self._init_async_session()
                
            url = f"{self.base_url}/api/version"
            async with self.session.get(url, timeout=2) as response:
                status["ollama"] = response.status == 200
        except Exception:
            status["ollama"] = False
            
        # 其他提供者需要 API 金鑰，檢查是否有有效金鑰和客戶端庫
        status["openai"] = OPENAI_AVAILABLE and bool(self.api_keys.get("openai"))
        status["anthropic"] = ANTHROPIC_AVAILABLE and bool(self.api_keys.get("anthropic"))
        
        return status
    
    async def __aenter__(self):
        """非同步上下文管理器入口"""
        await self._init_async_session()
        return self
        
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同步上下文管理器退出"""
        await self._close_async_session()
    
    async def _get_ollama_models_async(self) -> List[ModelInfo]:
        """非同步獲取 Ollama 模型列表
        
        回傳:
            Ollama ModelInfo物件列表
        """
        try:
            if not self.session:
                await self._init_async_session()
                
            models = set()
            
            # 嘗試使用不同的 API 端點獲取模型列表
            endpoints = [
                "/api/tags",
                "/api/models"
            ]
            
            for endpoint in endpoints:
                try:
                    url = f"{self.base_url}{endpoint}"
                    logger.debug(f"嘗試從 {url} 獲取 Ollama 模型")
                    
                    async with self.session.get(url, timeout=self.request_timeout) as response:
                        if response.status != 200:
                            logger.warning(f"API 端點 {endpoint} 返回非 200 狀態碼: {response.status}")
                            continue
                            
                        result = await response.json()
                        
                        # 處理不同的回應格式
                        if 'models' in result and isinstance(result['models'], list):
                            for model in result['models']:
                                if isinstance(model, dict) and 'name' in model:
                                    models.add(model['name'])
                        elif 'models' in result and isinstance(result['models'], dict):
                            for model_name in result['models'].keys():
                                models.add(model_name)
                        elif isinstance(result, list):
                            for item in result:
                                if isinstance(item, dict) and 'name' in item:
                                    models.add(item['name'])
                        
                        # 如果成功獲取了模型，跳出循環
                        if len(models) > 0:
                            break
                            
                except Exception as e:
                    logger.warning(f"從端點 {endpoint} 獲取模型失敗: {str(e)}")
                    continue
            
            # 如果沒有找到模型，嘗試使用系統自帶的模型列表
            if len(models) == 0:
                default_models = ["llama3", "mistral", "mixtral", "phi3"]
                for model in default_models:
                    models.add(model)
                    
                logger.warning(f"無法從 API 獲取模型，使用預設模型列表: {default_models}")
            
            # 添加預設模型
            models.add(self.default_ollama_model)
            
            # 過濾和排序
            model_set = set(models)
            if len(model_set) > 20:  # 只有當模型數量過多時才過濾
                filtered_models = set()
                for pattern in self.model_patterns:
                    for model in model_set:
                        if pattern in model.lower():
                            filtered_models.add(model)
                
                # 如果過濾後仍有足夠多的模型，使用過濾後的集合
                if len(filtered_models) >= 3:
                    model_set = filtered_models
            
            # 建立 ModelInfo 物件列表
            model_info_list = []
            for model_id in sorted(model_set):
                # 檢查是否有預定義的模型資訊
                key = f"ollama:{model_id}"
                if key in self.model_database:
                    model_info = self.model_database[key]
                else:
                    # 建立新的模型資訊
                    model_info = ModelInfo(
                        id=model_id,
                        provider="ollama",
                        name=self._format_model_name(model_id),
                        description="Ollama 模型",
                        pricing="免費(本機執行)",
                        recommended_for="一般翻譯任務",
                        parallel=2,
                        tags=["free", "local"],
                        capabilities={
                            "translation": 0.75,
                            "multilingual": 0.7,
                            "context_handling": 0.7
                        }
                    )
                
                model_info_list.append(model_info)
            
            # 確保預設模型在首位
            default_model_id = self.default_ollama_model
            model_info_list.sort(key=lambda x: 0 if x.id == default_model_id else 1)
            
            logger.info(f"檢測到 {len(model_info_list)} 個 Ollama 模型")
            return model_info_list
            
        except Exception as e:
            logger.error(f"獲取 Ollama 模型列表失敗: {str(e)}")
            # 返回預設模型
            default_model = self._create_default_ollama_model()
            return [default_model]
    
    def save_api_key(self, provider: str, api_key: str) -> bool:
        """儲存 API 金鑰
        
        參數:
            provider: 提供者 (如 "openai" 或 "anthropic")
            api_key: API 金鑰
            
        回傳:
            是否儲存成功
        """
        try:
            key_path = get_config("app", f"{provider}_key_path", f"{provider}_api_key.txt")
            
            # 確保目錄存在
            os.makedirs(os.path.dirname(key_path), exist_ok=True)
            
            with open(key_path, 'w', encoding='utf-8') as f:
                f.write(api_key)
            
            # 更新緩存
            self.api_keys[provider] = api_key
            
            # 清除模型快取，強制重新檢測
            if provider in self.cached_models:
                del self.cached_models[provider]
                if provider in self.cache_time:
                    del self.cache_time[provider]
            
            logger.info(f"已儲存 {provider} API 金鑰")
            return True
        except Exception as e:
            logger.error(f"儲存 {provider} API 金鑰時發生錯誤: {str(e)}")
            return False
    
    def _format_model_name(self, model_id: str) -> str:
        """格式化模型名稱，使其更易讀
        
        參數:
            model_id: 模型ID
            
        回傳:
            格式化後的模型名稱
        """
        try:
            # 移除版本號和標籤
            name = re.sub(r'[:@].+', '', model_id)
            
            # 處理常見縮寫
            name = name.replace('-', ' ').replace('_', ' ')
            
            # 分割路徑，只取最後部分
            parts = name.split('/')
            name = parts[-1]
            
            # 首字母大寫
            words = name.split()
            capitalized = []
            for word in words:
                # 處理駝峰命名
                camel_parts = re.findall(r'[A-Z][a-z]*|[a-z]+', word)
                camel_parts = [p.capitalize() for p in camel_parts]
                capitalized.append(' '.join(camel_parts))
            
            return ' '.join(capitalized)
        except Exception:
            return model_id
    
    async def _get_openai_models_async(self, api_key: str) -> List[ModelInfo]:
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
                "gpt-4-vision-preview": 999
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
                            parallel=10
                        )
                    
                    model_list.append(model_info)
            
            # 按翻譯優先級排序
            model_list.sort(key=lambda x: translation_priority.get(x.id, 900))
            
            # 確保列表中有最常用的模型
            default_models = ["gpt-3.5-turbo", "gpt-4"]
            for default_model in default_models:
                if not any(m.id == default_model for m in model_list):
                    key = f"openai:{default_model}"
                    if key in self.model_database:
                        model_info = self.model_database[key]
                    else:
                        model_info = ModelInfo(
                            id=default_model,
                            provider="openai",
                            name=self._format_model_name(default_model),
                            description="OpenAI 模型",
                            pricing="中" if "gpt-4" in default_model else "低",
                            recommended_for="一般翻譯任務"
                        )
                    model_list.append(model_info)
            
            logger.info(f"檢測到 {len(model_list)} 個 OpenAI 模型")
            return model_list
            
        except Exception as e:
            logger.error(f"獲取 OpenAI 模型列表失敗: {str(e)}")
            # 返回預設模型
            default_model = self._create_default_openai_model()
            return [default_model]

    def update_config(self, new_config: Dict[str, Any]) -> bool:
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
            important_keys = ["ollama_url", "default_ollama_model", "model_patterns"]
            if any(key in new_config for key in important_keys):
                self.cached_models.clear()
                self.cache_time.clear()
            
            logger.info("已更新模型管理器配置")
            return save_result
        except Exception as e:
            logger.error(f"更新模型管理器配置時發生錯誤: {str(e)}")
            return False

# 提供便捷的全域函數
def get_model_info(model_name: str, provider: str = None) -> Dict[str, Any]:
    """全域函數：獲取模型資訊
    
    參數:
        model_name: 模型名稱
        provider: 提供者 (如 "ollama" 或 "openai")
        
    回傳:
        模型資訊字典
    """
    manager = ModelManager.get_instance()
    return manager.get_model_info(model_name, provider)

def get_recommended_model(task_type: str = "translation", provider: str = None) -> str:
    """全域函數：根據任務類型獲取推薦模型
    
    參數:
        task_type: 任務類型 (如 "translation" 或 "literary")
        provider: 提供者 (如 "ollama" 或 "openai")
        
    回傳:
        推薦的模型名稱
    """
    manager = ModelManager.get_instance()
    model_info = manager.get_recommended_model(task_type, provider)
    if model_info:
        return model_info.id
    return manager.get_default_model(provider or "ollama")

async def test_model_connection(model_name: str, provider: str, api_key: str = None) -> Dict[str, Any]:
    """全域函數：測試與模型的連線
    
    參數:
        model_name: 模型名稱
        provider: 提供者 (如 "ollama", "openai" 或 "anthropic")
        api_key: API 金鑰 (可選)
        
    回傳:
        測試結果字典
    """
    manager = ModelManager.get_instance()
    return await manager.test_model_connection(model_name, provider, api_key)

# 測試程式碼
if __name__ == "__main__":
    async def test_async():
        try:
            # 讀取 API 金鑰
            try:
                with open("openapi_api_key.txt", "r") as f:
                    api_key = f.read().strip()
            except FileNotFoundError:
                print("未找到 API 金鑰檔案，使用 Ollama 模式")
                api_key = None
                
            # 使用非同步上下文管理器
            async with ModelManager.get_instance() as manager:
                # 檢查各提供者狀態
                print("檢查提供者狀態...")
                status = await manager.get_provider_status()
                for provider, available in status.items():
                    print(f"{provider}: {'可用' if available else '不可用'}")
                
                # 獲取 Ollama 模型
                print("\n獲取 Ollama 模型...")
                ollama_models = await manager.get_model_list_async("ollama")
                print(f"找到 {len(ollama_models)} 個 Ollama 模型:")
                for model in ollama_models[:5]:  # 只顯示前 5 個
                    print(f"- {model.name} ({model.id})")
                
                # 獲取 OpenAI 模型
                if api_key:
                    print("\n獲取 OpenAI 模型...")
                    openai_models = await manager.get_model_list_async("openai", api_key)
                    print(f"找到 {len(openai_models)} 個 OpenAI 模型:")
                    for model in openai_models[:5]:  # 只顯示前 5 個
                        print(f"- {model.name} ({model.id})")
                
                # 測試模型連線
                if ollama_models:
                    print("\n測試 Ollama 模型連線...")
                    test_model = ollama_models[0].id
                    result = await manager.test_model_connection(test_model, "ollama")
                    if result["success"]:
                        print(f"連線成功! 回應時間: {result['response_time']}秒")
                    else:
                        print(f"連線失敗: {result['message']}")
                
                # 獲取推薦模型
                print("\n獲取推薦模型...")
                for task in ["translation", "literary", "technical", "subtitle"]:
                    model = manager.get_recommended_model(task)
                    if model:
                        print(f"推薦用於{task}的模型: {model.name} ({model.provider})")
        
        except Exception as e:
            print(f"測試過程中發生錯誤: {str(e)}")
            import traceback
            traceback.print_exc()

    # 執行測試
    asyncio.run(test_async())