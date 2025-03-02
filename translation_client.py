# translation_client.py
import aiohttp
import asyncio
import time
from typing import List, Optional, Dict, Tuple
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
        self.llm_type = llm_type
        self.base_url = base_url if llm_type == 'ollama' else "https://api.openai.com/v1"
        self.cache_manager = CacheManager()
        self.prompt_manager = PromptManager()
        self.session = None
        self.api_key = api_key
        
        if llm_type == 'openai':
            self.openai_client = AsyncOpenAI(
                api_key=api_key,
                timeout=aiohttp.ClientTimeout(total=60, connect=10, sock_connect=10, sock_read=30)
            )
            self.request_timestamps = []
            self.max_requests_per_minute = 3000
            self.max_tokens_per_minute = 90000
            self.token_usage = []
        else:
            self.openai_client = None

    async def __aenter__(self):
        if self.llm_type == 'ollama':
            self.session = aiohttp.ClientSession()
            logger.debug("初始化 aiohttp.ClientSession for Ollama")
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session and self.llm_type == 'ollama':
            await self.session.close()
            logger.debug("關閉 aiohttp.ClientSession")

    async def _check_rate_limit(self):
        # ... 原有代碼保持不變 ...

    async def _estimate_token_count(self, messages: List[dict]) -> int:
        # ... 原有代碼保持不變 ...

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=5,
        max_time=120,
        on_backoff=lambda details: logger.debug(f"重試 {details['tries']} 次，等待 {details['wait']} 秒")
    )
    async def translate_text(self, text: str, context_texts: List[str], model_name: str) -> str:
        """翻譯文本，根據 LLM 類型選擇不同的處理方式，並應用後處理"""
        logger.debug(f"開始翻譯文本: '{text}'，上下文: {context_texts[:2]}...，模型: {model_name}")
        
        cached_result = self.cache_manager.get_cached_translation(text, context_texts, model_name)
        if cached_result:
            logger.debug(f"從緩存獲取翻譯結果: {cached_result}")
            return cached_result

        messages = self.prompt_manager.get_optimized_message(text, context_texts, self.llm_type, model_name)
        
        if self.llm_type == 'openai':
            await self._check_rate_limit()
            estimated_tokens = await self._estimate_token_count(messages)
            current_time = time.time()
            self.request_timestamps.append(current_time)
            
            openai_params = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": min(150, 4096),
                "timeout": 30,
            }
            if "gpt-4" in model_name or "gpt-3.5-turbo" in model_name:
                openai_params["response_format"] = {"type": "text"}
            
            try:
                logger.debug(f"發送 OpenAI API 請求: {self.base_url}/chat/completions")
                response = await self.openai_client.chat.completions.create(**openai_params)
                translation = response.choices[0].message.content.strip()
                # 應用後處理
                translation = self.prompt_manager.post_process_translation(translation)
                
                self.token_usage.append((current_time, response.usage.prompt_tokens + response.usage.completion_tokens))
                logger.debug(f"OpenAI API 回應翻譯: {translation}")
            except Exception as e:
                logger.error(f"OpenAI API 請求失敗: {str(e)}")
                raise
                
        elif self.llm_type == 'ollama':
            payload = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.1
            }
            
            logger.debug(f"發送 Ollama API 請求: {self.base_url}/v1/chat/completions")
            async with self.session.post(
                f"{self.base_url}/v1/chat/completions",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                result = await response.json()
                translation = result['choices'][0]['message']['content'].strip()
                # 應用後處理
                translation = self.prompt_manager.post_process_translation(translation)
                logger.debug(f"Ollama API 回應翻譯: {translation}")

        self.cache_manager.store_translation(text, translation, context_texts, model_name)
        return translation

    async def translate_batch(self, texts: List[Tuple[str, List[str]]], model_name: str) -> List[str]:
        """批量翻譯多個字幕 (僅 OpenAI 使用)"""
        if self.llm_type != 'openai' or not texts:
            return [await self.translate_text(text, context, model_name) for text, context in texts]
            
        results = []
        cache_hits = []
        api_requests = []
        
        for i, (text, context) in enumerate(texts):
            cached = self.cache_manager.get_cached_translation(text, context, model_name)
            if cached:
                cache_hits.append((i, cached))
            else:
                api_requests.append((i, text, context))
        
        results = [None] * len(texts)
        for i, translation in cache_hits:
            results[i] = translation
            
        if api_requests:
            batch_size = min(5, len(api_requests))
            for i in range(0, len(api_requests), batch_size):
                batch = api_requests[i:i+batch_size]
                tasks = []
                
                for req_idx, text, context in batch:
                    task = asyncio.create_task(self.translate_text(text, context, model_name))
                    tasks.append((req_idx, task))
                    
                for req_idx, task in tasks:
                    try:
                        translation = await task
                        results[req_idx] = translation
                    except Exception as e:
                        logger.error(f"批量翻譯中的單條請求失敗: {str(e)}")
                        results[req_idx] = f"[翻譯錯誤: {str(e)}]"
        
        return results

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