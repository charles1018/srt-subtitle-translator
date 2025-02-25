# translation_client.py
import aiohttp
import asyncio
from typing import List
import backoff
import logging
from logging.handlers import TimedRotatingFileHandler
from cache import CacheManager
from prompt import PromptManager
from openai import AsyncOpenAI

# 設置日誌輪替
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

handler = TimedRotatingFileHandler(
    filename='srt_translator.log',
    when='midnight',
    interval=1,
    backupCount=7,
    encoding='utf-8'
)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

class TranslationClient:
    def __init__(self, llm_type: str, base_url: str = "http://localhost:11434", api_key: str = None):
        self.llm_type = llm_type  # 'ollama' 或 'openai'
        self.base_url = base_url if llm_type == 'ollama' else "https://api.openai.com/v1"
        self.cache_manager = CacheManager()
        self.prompt_manager = PromptManager()
        self.session = None
        self.api_key = api_key
        self.openai_client = AsyncOpenAI(api_key=api_key) if llm_type == 'openai' else None

    async def __aenter__(self):
        if self.llm_type == 'ollama':
            self.session = aiohttp.ClientSession()
            logger.debug("初始化 aiohttp.ClientSession for Ollama")
        # OpenAI 使用 AsyncOpenAI，不需額外 session
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and self.llm_type == 'ollama':
            await self.session.close()
            logger.debug("關閉 aiohttp.ClientSession")

    @backoff.on_exception(backoff.expo,
                         (aiohttp.ClientError, asyncio.TimeoutError),
                         max_tries=3,
                         max_time=60,
                         on_backoff=lambda details: logger.debug(f"重試 {details['tries']} 次，等待 {details['wait']} 秒"))
    async def translate_text(self, text: str, context_texts: List[str], model_name: str) -> str:
        """翻譯文本，根據 LLM 類型選擇 Ollama 或 OpenAI"""
        logger.debug(f"開始翻譯文本: '{text}'，上下文: {context_texts[:2]}...，模型: {model_name}")
        
        cached_result = self.cache_manager.get_cached_translation(text, context_texts, model_name)
        if cached_result:
            logger.debug(f"從緩存獲取翻譯結果: {cached_result}")
            return cached_result

        payload = {
            "model": model_name,
            "messages": self.prompt_manager.get_full_message(text, context_texts),
            "temperature": 0.1
        }

        if self.llm_type == 'ollama':
            logger.debug(f"發送 Ollama API 請求: {self.base_url}/v1/chat/completions")
            async with self.session.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                result = await response.json()
                translation = result['choices'][0]['message']['content'].strip()
        elif self.llm_type == 'openai':
            logger.debug(f"發送 OpenAI API 請求: {self.base_url}/chat/completions")
            response = await self.openai_client.chat.completions.create(**payload)
            translation = response.choices[0].message.content.strip()

        logger.debug(f"API 回應翻譯: {translation}")
        self.cache_manager.store_translation(text, translation, context_texts, model_name)
        return translation

# 測試代碼
if __name__ == "__main__":
    async def test():
        with open("openapi_api_key.txt", "r") as f:
            api_key = f.read().strip()
        client = TranslationClient(llm_type='openai', api_key=api_key)
        async with client:
            context = ["前一句", "こんにちは", "後一句"]
            result = await client.translate_text("こんにちは", context, "gpt-3.5-turbo")
            print(f"翻譯結果: {result}")

    asyncio.run(test())