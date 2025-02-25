# ollama_client.py
import aiohttp
import asyncio
from typing import List
import backoff
import logging
from cache import CacheManager
from prompt import PromptManager

# 設置日誌
logging.basicConfig(level=logging.DEBUG, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.cache_manager = CacheManager()
        self.prompt_manager = PromptManager()
        self.session = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        logger.debug("初始化 aiohttp.ClientSession")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
            logger.debug("關閉 aiohttp.ClientSession")

    @backoff.on_exception(backoff.expo,
                         (aiohttp.ClientError, asyncio.TimeoutError),
                         max_tries=3,
                         max_time=60,
                         on_backoff=lambda details: logger.debug(f"重試 {details['tries']} 次，等待 {details['wait']} 秒"))
    async def translate_text(self, text: str, context_texts: List[str], model_name: str) -> str:
        """翻譯文本，包含重試和緩存機制"""
        logger.debug(f"開始翻譯文本: '{text}'，上下文: {context_texts[:2]}...，模型: {model_name}")
        
        cached_result = self.cache_manager.get_cached_translation(text, context_texts, model_name)
        if cached_result:
            logger.debug(f"從緩存獲取翻譯結果: {cached_result}")
            return cached_result

        payload = {
            "model": model_name,
            "messages": self.prompt_manager.get_full_message(text, context_texts),
            "stream": False,
            "temperature": 0.1
        }

        logger.debug(f"發送 API 請求: {self.base_url}/v1/chat/completions")
        async with self.session.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            response.raise_for_status()
            result = await response.json()
            translation = result['choices'][0]['message']['content'].strip()
            logger.debug(f"API 回應翻譯: {translation}")
            
            self.cache_manager.store_translation(text, translation, context_texts, model_name)
            return translation

# 測試代碼
if __name__ == "__main__":
    async def test():
        async with OllamaClient() as client:
            context = ["前一句", "こんにちは", "後一句"]
            result = await client.translate_text("こんにちは", context, "huihui_ai/aya-expanse-abliterated:latest")
            print(f"翻譯結果: {result}")

    asyncio.run(test())