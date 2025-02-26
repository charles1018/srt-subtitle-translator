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
        
        # OpenAI 客戶端優化
        if llm_type == 'openai':
            self.openai_client = AsyncOpenAI(
                api_key=api_key,
                timeout=aiohttp.ClientTimeout(total=60, connect=10, sock_connect=10, sock_read=30)
            )
            self.request_timestamps = []  # 用於追蹤 API 請求時間
            self.max_requests_per_minute = 3000  # OpenAI API 默認限制
            self.max_tokens_per_minute = 90000   # OpenAI API 默認限制
            self.token_usage = []  # 用於追蹤 token 使用量
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
        """檢查並處理 OpenAI 速率限制"""
        if self.llm_type != 'openai':
            return

        # 清理舊的時間戳記錄
        current_time = time.time()
        self.request_timestamps = [ts for ts in self.request_timestamps if current_time - ts < 60]
        self.token_usage = [(ts, tokens) for ts, tokens in self.token_usage if current_time - ts < 60]
        
        # 計算當前速率
        requests_per_minute = len(self.request_timestamps)
        tokens_per_minute = sum(tokens for _, tokens in self.token_usage)
        
        # 如果接近限制，等待適當時間
        if requests_per_minute >= self.max_requests_per_minute * 0.95:
            wait_time = 60 - (current_time - self.request_timestamps[0]) + 0.1
            logger.warning(f"接近 OpenAI 請求速率限制 ({requests_per_minute}/{self.max_requests_per_minute})，等待 {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)
            
        if tokens_per_minute >= self.max_tokens_per_minute * 0.95:
            wait_time = 60 - (current_time - self.token_usage[0][0]) + 0.1
            logger.warning(f"接近 OpenAI token 速率限制 ({tokens_per_minute}/{self.max_tokens_per_minute})，等待 {wait_time:.2f} 秒")
            await asyncio.sleep(wait_time)

    async def _estimate_token_count(self, messages: List[dict]) -> int:
        """估算請求中的 token 數量 (粗略估計)"""
        total_chars = sum(len(m.get('content', '')) for m in messages)
        # 粗略估計: 英文平均 4 字符/token，非英文 2 字符/token
        return total_chars // 3  # 大部分是中日文，所以用 3 作為平均值

    @backoff.on_exception(
        backoff.expo,
        (aiohttp.ClientError, asyncio.TimeoutError),
        max_tries=5,  # 增加重試次數
        max_time=120,  # 增加總重試時間
        on_backoff=lambda details: logger.debug(f"重試 {details['tries']} 次，等待 {details['wait']} 秒")
    )
    async def translate_text(self, text: str, context_texts: List[str], model_name: str) -> str:
        """翻譯文本，根據 LLM 類型選擇不同的處理方式"""
        logger.debug(f"開始翻譯文本: '{text}'，上下文: {context_texts[:2]}...，模型: {model_name}")
        
        # 首先嘗試從緩存獲取，這步很快不需要異步
        cached_result = self.cache_manager.get_cached_translation(text, context_texts, model_name)
        if cached_result:
            logger.debug(f"從緩存獲取翻譯結果: {cached_result}")
            return cached_result

        # 獲取適合當前 LLM 類型的提示訊息
        messages = self.prompt_manager.get_optimized_message(text, context_texts, self.llm_type, model_name)
        
        if self.llm_type == 'openai':
            # 檢查速率限制
            await self._check_rate_limit()
            
            # 估算 token 數量
            estimated_tokens = await self._estimate_token_count(messages)
            
            # 記錄此次請求的時間戳
            current_time = time.time()
            self.request_timestamps.append(current_time)
            
            # 準備 OpenAI 參數
            openai_params = {
                "model": model_name,
                "messages": messages,
                "temperature": 0.1,
                "max_tokens": min(150, 4096),  # 限制回應長度，SRT 字幕通常不會很長
                "timeout": 30,  # 設置超時
            }
            
            # 添加 response_format 參數（適用於較新的模型）
            if "gpt-4" in model_name or "gpt-3.5-turbo" in model_name:
                openai_params["response_format"] = {"type": "text"}
            
            try:
                logger.debug(f"發送 OpenAI API 請求: {self.base_url}/chat/completions")
                response = await self.openai_client.chat.completions.create(**openai_params)
                translation = response.choices[0].message.content.strip()
                
                # 記錄實際 token 使用量
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
                total_tokens = input_tokens + output_tokens
                self.token_usage.append((current_time, total_tokens))
                
                logger.debug(f"OpenAI API 回應翻譯: {translation} (使用 {total_tokens} tokens)")
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
                logger.debug(f"Ollama API 回應翻譯: {translation}")

        # 儲存到緩存
        self.cache_manager.store_translation(text, translation, context_texts, model_name)
        return translation

    async def translate_batch(self, texts: List[Tuple[str, List[str]]], model_name: str) -> List[str]:
        """批量翻譯多個字幕 (僅 OpenAI 使用)"""
        if self.llm_type != 'openai' or not texts:
            return [await self.translate_text(text, context, model_name) for text, context in texts]
            
        results = []
        cache_hits = []
        api_requests = []
        
        # 首先檢查緩存
        for i, (text, context) in enumerate(texts):
            cached = self.cache_manager.get_cached_translation(text, context, model_name)
            if cached:
                cache_hits.append((i, cached))
            else:
                api_requests.append((i, text, context))
        
        # 填入緩存命中的結果
        results = [None] * len(texts)
        for i, translation in cache_hits:
            results[i] = translation
            
        # 進行實際 API 請求
        if api_requests:
            batch_size = min(5, len(api_requests))  # 最多一次處理 5 個請求
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