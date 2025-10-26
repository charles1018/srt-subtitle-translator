import os
import asyncio
import logging
import time
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple, Union, Callable
import json
import re
import pysrt
import hashlib
from pathlib import Path
from logging.handlers import TimedRotatingFileHandler
import threading
from queue import Queue

# 嘗試匯入相依模組
try:
    from srt_translator.core.config import ConfigManager, get_config, set_config
except ImportError:
    raise ImportError("請先實現 config_manager.py")

# 從現有模組匯入必要的類和函數
from srt_translator.translation.client import TranslationClient
from srt_translator.core.cache import CacheManager
from srt_translator.core.models import ModelManager
from srt_translator.core.prompt import PromptManager
from srt_translator.file_handling.handler import FileHandler, SubtitleInfo

# 設定日誌
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 確保日誌目錄存在
os.makedirs('logs', exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = TimedRotatingFileHandler(
        filename='logs/services.log',
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

# 服務工廠類 - 統一管理所有服務的創建和訪問
class ServiceFactory:
    """服務工廠類，管理所有服務實例並提供統一的訪問方式"""
    
    # 儲存所有建立的服務實例
    _instances = {}
    
    @classmethod
    def get_translation_service(cls) -> 'TranslationService':
        """獲取翻譯服務實例"""
        return cls._get_service_instance(TranslationService)
    
    @classmethod
    def get_model_service(cls) -> 'ModelService':
        """獲取模型服務實例"""
        return cls._get_service_instance(ModelService)
    
    @classmethod
    def get_cache_service(cls) -> 'CacheService':
        """獲取快取服務實例"""
        return cls._get_service_instance(CacheService)
    
    @classmethod
    def get_file_service(cls) -> 'FileService':
        """獲取檔案服務實例"""
        return cls._get_service_instance(FileService)
    
    @classmethod
    def get_progress_service(cls) -> 'ProgressService':
        """獲取進度追蹤服務實例"""
        return cls._get_service_instance(ProgressService)
        
    @classmethod
    def _get_service_instance(cls, service_class):
        """獲取指定服務類的實例（單例模式）"""
        service_name = service_class.__name__
        if service_name not in cls._instances:
            cls._instances[service_name] = service_class()
        return cls._instances[service_name]
    
    @classmethod
    def reset_services(cls) -> None:
        """重置所有服務實例（主要用於測試）"""
        for service_name in list(cls._instances.keys()):
            if hasattr(cls._instances[service_name], 'cleanup'):
                try:
                    cls._instances[service_name].cleanup()
                except Exception as e:
                    logger.error(f"清理服務 {service_name} 時發生錯誤: {str(e)}")
        cls._instances.clear()

# 翻譯服務 - 處理翻譯相關的功能
class TranslationService:
    """翻譯服務，提供統一的翻譯介面"""
    
    def __init__(self):
        """初始化翻譯服務"""
        self.prompt_manager = None
        self.model_service = None
        self.cache_service = None
        self.file_service = None
        self.config_manager = ConfigManager.get_instance("user")
        
        # 初始化成員
        self._initialize_members()
        
        # 統計資訊
        self.stats = {
            "total_translations": 0,
            "cached_translations": 0,
            "failed_translations": 0,
            "processing_time": 0,
            "start_time": None,
            "end_time": None
        }
        
        # 專有名詞詞典 (用於統一翻譯)
        self.key_terms_dict = {}
        
        logger.info("翻譯服務初始化完成")
    
    def _initialize_members(self) -> None:
        """初始化服務成員"""
        try:
            # 取得其他服務實例
            self.model_service = ServiceFactory.get_model_service()
            self.cache_service = ServiceFactory.get_cache_service()
            self.file_service = ServiceFactory.get_file_service()
            
            # 初始化提示詞管理器
            self.prompt_manager = PromptManager()
        except Exception as e:
            logger.error(f"初始化翻譯服務成員時發生錯誤: {str(e)}")
            raise
    
    async def translate_text(self, text: str, context_texts: List[str], llm_type: str, model_name: str) -> str:
        """翻譯單一文本
        
        參數:
            text: 要翻譯的文本
            context_texts: 上下文文本列表
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            model_name: 模型名稱
            
        回傳:
            翻譯後的文本
        """
        if not text.strip():
            return ""
        
        self.stats["total_translations"] += 1
        
        # 檢查快取
        cached_result = self.cache_service.get_translation(text, context_texts, model_name)
        if cached_result:
            self.stats["cached_translations"] += 1
            return cached_result
        
        start_time = time.time()
        
        try:
            # 獲取模型客戶端
            client = await self.model_service.get_translation_client(llm_type)
            
            # 獲取翻譯提示詞
            messages = self.prompt_manager.get_optimized_message(text, context_texts, llm_type, model_name)
            
            # 使用客戶端執行翻譯
            if hasattr(client, 'translate_with_retry'):
                translation = await client.translate_with_retry(text, context_texts, model_name)
            else:
                translation = await client.translate_text(text, context_texts, model_name)
            
            # 翻譯後處理 - 專有名詞統一與移除標點符號
            translation = self._post_process_translation(text, translation)
            
            # 儲存到快取
            self.cache_service.store_translation(text, translation, context_texts, model_name)
            
            # 更新統計資料
            end_time = time.time()
            self.stats["processing_time"] += (end_time - start_time)
            
            return translation
            
        except Exception as e:
            self.stats["failed_translations"] += 1
            logger.error(f"翻譯文本時發生錯誤: {str(e)}")
            return f"[翻譯錯誤: {str(e)}]"
    
    async def translate_batch(self, texts_with_context: List[Tuple[str, List[str]]], 
                            llm_type: str, model_name: str, concurrent_limit: int = 5) -> List[str]:
        """批量翻譯多個文本
        
        參數:
            texts_with_context: 文本和上下文的列表，格式為 [(text, context_texts), ...]
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            model_name: 模型名稱
            concurrent_limit: 並行請求限制
            
        回傳:
            翻譯結果列表
        """
        if not texts_with_context:
            return []
        
        results = [""] * len(texts_with_context)
        
        # 獲取客戶端
        client = await self.model_service.get_translation_client(llm_type)
        
        # 檢查客戶端是否支持批量翻譯
        if hasattr(client, 'translate_batch'):
            # 使用原生批量翻譯功能
            batch_results = await client.translate_batch(
                texts_with_context, 
                model_name,
                concurrent_limit=concurrent_limit
            )
            
            # 對每個結果進行後處理
            for i, (text, _) in enumerate(texts_with_context):
                if i < len(batch_results) and batch_results[i]:
                    # 翻譯後處理
                    results[i] = self._post_process_translation(text, batch_results[i])
        else:
            # 自行實現批量翻譯
            semaphore = asyncio.Semaphore(concurrent_limit)
            
            async def process_item(idx, text, context):
                async with semaphore:
                    translation = await self.translate_text(text, context, llm_type, model_name)
                    return idx, translation
            
            # 建立任務
            tasks = [process_item(i, text, context) for i, (text, context) in enumerate(texts_with_context)]
            
            # 等待所有任務完成
            completed = await asyncio.gather(*tasks, return_exceptions=True)
            
            # 處理結果
            for result in completed:
                if isinstance(result, Exception):
                    logger.error(f"批量翻譯中的項目發生錯誤: {str(result)}")
                    continue
                
                if isinstance(result, tuple) and len(result) == 2:
                    idx, translation = result
                    results[idx] = translation
        
        return results
    
    async def translate_subtitle_file(self, file_path: str, source_lang: str, target_lang: str, 
                                    model_name: str, parallel_requests: int,
                                    display_mode: str, llm_type: str,
                                    progress_callback: Callable = None,
                                    complete_callback: Callable = None) -> Tuple[bool, str]:
        """翻譯字幕檔案
        
        參數:
            file_path: 字幕檔案路徑
            source_lang: 來源語言
            target_lang: 目標語言
            model_name: 模型名稱
            parallel_requests: 並行請求數
            display_mode: 顯示模式 (如 "雙語對照")
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            progress_callback: 進度回調函數
            complete_callback: 完成回調函數
            
        回傳:
            (成功與否, 輸出路徑或錯誤消息)
        """
        try:
            # 重置統計資訊
            self.stats["start_time"] = time.time()
            self.stats["total_translations"] = 0
            self.stats["cached_translations"] = 0
            self.stats["failed_translations"] = 0
            self.stats["processing_time"] = 0
            
            # 重置專有名詞詞典
            self.key_terms_dict = {}
            
            # 載入字幕檔案
            subs = pysrt.open(file_path, encoding='utf-8')
            total_subtitles = len(subs)
            
            # 設定進度回調
            progress_service = ServiceFactory.get_progress_service()
            progress_service.register_progress_callback(progress_callback)
            progress_service.register_complete_callback(complete_callback)
            progress_service.set_total(total_subtitles)
            
            # 設定上下文窗口大小
            context_window = 5  # 上下文窗口大小 (每側)
            
            # 計算批次大小
            batch_size = min(20, parallel_requests * 2)
            if llm_type == "openai":
                # OpenAI有速率限制，使用較小批次
                batch_size = min(5, parallel_requests)
            
            # 分批翻譯
            for i in range(0, total_subtitles, batch_size):
                batch_indices = list(range(i, min(i + batch_size, total_subtitles)))
                
                # 準備批量翻譯請求
                texts_with_context = []
                for idx in batch_indices:
                    # 取得上下文
                    context_start = max(0, idx - context_window)
                    context_end = min(total_subtitles, idx + context_window + 1)
                    context_texts = [s.text for s in subs[context_start:context_end]]
                    
                    texts_with_context.append((subs[idx].text, context_texts))
                
                # 批量翻譯
                translations = await self.translate_batch(
                    texts_with_context, 
                    llm_type, 
                    model_name, 
                    parallel_requests
                )
                
                # 應用翻譯結果
                for batch_idx, idx in enumerate(batch_indices):
                    if batch_idx < len(translations):
                        # 應用翻譯
                        self._apply_translation(subs[idx], translations[batch_idx], display_mode)
                        
                        # 更新進度
                        progress_service.increment_progress()
            
            # 取得輸出路徑
            output_path = self.file_service.get_output_path(file_path, target_lang)
            if not output_path:
                return False, "無法建立輸出路徑"
            
            # 保存檔案
            subs.save(output_path, encoding='utf-8')
            
            # 更新結束時間
            self.stats["end_time"] = time.time()
            
            # 保存專有名詞詞典
            self._save_key_terms_dictionary(file_path)
            
            # 計算耗時
            elapsed_time = self.get_elapsed_time_str()
            
            # 呼叫完成回調
            if complete_callback:
                complete_callback(f"翻譯完成 | 檔案已成功儲存為: {output_path}", elapsed_time)
            
            return True, output_path
            
        except Exception as e:
            logger.error(f"翻譯字幕檔案時發生錯誤: {str(e)}")
            
            # 更新結束時間
            self.stats["end_time"] = time.time()
            
            # 計算耗時
            elapsed_time = self.get_elapsed_time_str()
            
            # 呼叫完成回調
            if complete_callback:
                complete_callback(f"翻譯過程中發生錯誤: {str(e)}", elapsed_time)
            
            return False, str(e)
    
    def _post_process_translation(self, original_text: str, translated_text: str) -> str:
        """對翻譯結果進行後處理，包括專有名詞統一和移除標點符號
        
        參數:
            original_text: 原始文字
            translated_text: 翻譯文字
            
        回傳:
            後處理後的翻譯文字
        """
        if not translated_text:
            return translated_text
            
        # 1. 處理專有名詞統一
        # 使用正則表達式識別可能的專有名詞（假設專有名詞通常是2-6個漢字的連續序列）
        potential_terms = re.findall(r'[\u4e00-\u9fff]{2,6}', translated_text)
        
        # 對於每個潛在的專有名詞，檢查是否已在詞典中
        for term in potential_terms:
            # 如果該詞已在詞典中，用標準形式替換
            if term in self.key_terms_dict:
                translated_text = translated_text.replace(term, self.key_terms_dict[term])
            # 否則添加到詞典，以當前形式作為標準
            elif len(term) >= 2:  # 只考慮至少兩個字的詞
                self.key_terms_dict[term] = term
        
        # 檢查是否需要保留原始標點符號
        preserve_punctuation = get_config("user", "preserve_punctuation", True)
        if preserve_punctuation:
            return translated_text.strip()
            
        # 2. 移除中文標點符號，用空格替換
        # 定義中文標點符號
        cn_punctuation = r'，。！？；：""''（）【】《》〈〉、…—～·「」『』〔〕'
        # 將標點符號替換為空格
        for punct in cn_punctuation:
            translated_text = translated_text.replace(punct, ' ')
        
        # 替換英文標點符號
        en_punctuation = r',.!?;:"\'()[]<>-_'
        for punct in en_punctuation:
            translated_text = translated_text.replace(punct, ' ')
        
        # 處理連續空格
        translated_text = re.sub(r'\s+', ' ', translated_text)
        
        return translated_text.strip()
    
    def _apply_translation(self, subtitle, translation: str, display_mode: str) -> None:
        """根據顯示模式套用翻譯結果
        
        參數:
            subtitle: 字幕對象
            translation: 翻譯文本
            display_mode: 顯示模式
        """
        if display_mode == "僅顯示翻譯":
            subtitle.text = translation
        elif display_mode == "翻譯在上":
            subtitle.text = f"{translation}\n{subtitle.text}"
        elif display_mode == "原文在上":
            subtitle.text = f"{subtitle.text}\n{translation}"
        elif display_mode == "雙語對照":
            subtitle.text = f"{subtitle.text}\n{translation}"
        else:
            # 預設行為，使用雙語對照
            subtitle.text = f"{subtitle.text}\n{translation}"
    
    def _save_key_terms_dictionary(self, file_path: str) -> None:
        """儲存專有名詞詞典到檔案
        
        參數:
            file_path: 原始檔案路徑，用於生成詞典檔名
        """
        try:
            # 檢查詞典大小，如果太小則不儲存
            if len(self.key_terms_dict) <= 2:
                return
                
            # 構建檔案路徑，使用影片名稱
            base_name = os.path.splitext(os.path.basename(file_path))[0]
            dict_path = os.path.join("data", "terms_dictionaries", f"{base_name}_terms.json")
            
            # 確保目錄存在
            os.makedirs(os.path.dirname(dict_path), exist_ok=True)
            
            # 儲存詞典
            with open(dict_path, 'w', encoding='utf-8') as f:
                json.dump(self.key_terms_dict, f, ensure_ascii=False, indent=2)
                
            logger.info(f"已儲存 {len(self.key_terms_dict)} 個專有名詞到檔案: {dict_path}")
        except Exception as e:
            logger.error(f"儲存專有名詞詞典失敗: {str(e)}")
    
    def get_stats(self) -> Dict[str, Any]:
        """獲取翻譯統計資訊
        
        回傳:
            包含統計資訊的字典
        """
        stats = self.stats.copy()
        
        # 計算命中率
        if stats["total_translations"] > 0:
            stats["cache_hit_rate"] = (stats["cached_translations"] / stats["total_translations"]) * 100
        else:
            stats["cache_hit_rate"] = 0
        
        # 計算成功率
        if stats["total_translations"] > 0:
            stats["success_rate"] = ((stats["total_translations"] - stats["failed_translations"]) / stats["total_translations"]) * 100
        else:
            stats["success_rate"] = 0
        
        # 計算平均處理時間
        if stats["total_translations"] - stats["cached_translations"] > 0:
            stats["average_processing_time"] = stats["processing_time"] / (stats["total_translations"] - stats["cached_translations"])
        else:
            stats["average_processing_time"] = 0
        
        return stats
    
    def get_elapsed_time(self) -> float:
        """獲取翻譯耗時（秒）
        
        回傳:
            翻譯耗時（秒）
        """
        if self.stats["end_time"] is None:
            if self.stats["start_time"] is None:
                return 0
            return time.time() - self.stats["start_time"]
        return self.stats["end_time"] - self.stats["start_time"]
    
    def get_elapsed_time_str(self) -> str:
        """獲取格式化的翻譯耗時
        
        回傳:
            格式化的耗時字串
        """
        seconds = self.get_elapsed_time()
        
        if seconds < 60:
            return f"{int(seconds)} 秒"
        
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        
        if minutes < 60:
            return f"{minutes} 分 {seconds} 秒"
        
        hours = int(minutes // 60)
        minutes = int(minutes % 60)
        return f"{hours} 小時 {minutes} 分 {seconds} 秒"
    
    def cleanup(self) -> None:
        """清理資源"""
        # 目前沒有特殊清理需求
        pass

# 模型服務 - 管理和加載各種模型
class ModelService:
    """模型服務，管理和加載LLM模型"""
    
    def __init__(self):
        """初始化模型服務"""
        self.model_manager = ModelManager()
        self.translation_clients = {}  # 類型 -> 客戶端實例
        self.api_keys = {}  # 類型 -> API 金鑰
        
        # 載入 API 金鑰
        self._load_api_keys()
        
        logger.info("模型服務初始化完成")
    
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
    
    async def get_translation_client(self, llm_type: str) -> TranslationClient:
        """獲取翻譯客戶端實例
        
        參數:
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            
        回傳:
            翻譯客戶端實例
        """
        # 檢查現有客戶端
        if llm_type in self.translation_clients:
            return self.translation_clients[llm_type]
        
        # 建立新客戶端
        api_key = self.api_keys.get(llm_type)
        base_url = get_config("model", f"{llm_type}_url", None)
        cache_db_path = get_config("cache", "db_path", "data/translation_cache.db")
        
        client = TranslationClient(llm_type, base_url=base_url, api_key=api_key, cache_db_path=cache_db_path)
        await client.__aenter__()
        
        # 儲存客戶端實例
        self.translation_clients[llm_type] = client
        logger.info(f"已建立 {llm_type} 翻譯客戶端")
        
        return client
    
    async def get_available_models(self, llm_type: str) -> List[str]:
        """獲取可用的模型列表
        
        參數:
            llm_type: LLM類型 (如 "ollama" 或 "openai")
            
        回傳:
            模型名稱列表
        """
        api_key = self.api_keys.get(llm_type)
        models = await self.model_manager.get_model_list_async(llm_type, api_key)
        return [model.id for model in models]
    
    def get_model_info(self, model_name: str, provider: str = None) -> Dict[str, Any]:
        """獲取模型的詳細資訊
        
        參數:
            model_name: 模型名稱
            provider: 提供者 (如 "ollama" 或 "openai")
            
        回傳:
            模型資訊字典
        """
        return self.model_manager.get_model_info(model_name, provider)
    
    def get_recommended_model(self, task_type: str = "translation", provider: str = None) -> str:
        """根據任務類型獲取推薦模型
        
        參數:
            task_type: 任務類型 (如 "translation" 或 "literary")
            provider: 提供者 (如 "ollama" 或 "openai")
            
        回傳:
            推薦的模型名稱
        """
        model_info = self.model_manager.get_recommended_model(task_type, provider)
        if model_info:
            return model_info.id
        return self.model_manager.get_default_model(provider or "ollama")
    
    async def test_model_connection(self, model_name: str, provider: str) -> Dict[str, Any]:
        """測試與模型的連線
        
        參數:
            model_name: 模型名稱
            provider: 提供者 (如 "ollama" 或 "openai")
            
        回傳:
            測試結果字典
        """
        api_key = self.api_keys.get(provider)
        return await self.model_manager.test_model_connection(model_name, provider, api_key)
    
    async def get_provider_status(self) -> Dict[str, bool]:
        """獲取各提供者的連線狀態
        
        回傳:
            提供者狀態字典
        """
        return await self.model_manager.get_provider_status()
    
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
            with open(key_path, 'w', encoding='utf-8') as f:
                f.write(api_key)
            
            # 更新緩存
            self.api_keys[provider] = api_key
            
            logger.info(f"已儲存 {provider} API 金鑰")
            return True
        except Exception as e:
            logger.error(f"儲存 {provider} API 金鑰時發生錯誤: {str(e)}")
            return False
    
    async def cleanup(self) -> None:
        """清理資源"""
        # 關閉所有翻譯客戶端
        for llm_type, client in self.translation_clients.items():
            try:
                await client.__aexit__(None, None, None)
                logger.info(f"已關閉 {llm_type} 翻譯客戶端")
            except Exception as e:
                logger.error(f"關閉 {llm_type} 翻譯客戶端時發生錯誤: {str(e)}")
        
        self.translation_clients.clear()

# 快取服務 - 管理翻譯結果快取
class CacheService:
    """快取服務，管理翻譯結果的快取"""
    
    def __init__(self):
        """初始化快取服務"""
        cache_config = ConfigManager.get_instance("cache")
        cache_db_path = cache_config.get_value("db_path", "data/translation_cache.db")
        
        self.cache_manager = CacheManager(cache_db_path)
        
        logger.info("快取服務初始化完成")
    
    def get_translation(self, source_text: str, context_texts: List[str], model_name: str) -> Optional[str]:
        """從快取獲取翻譯結果
        
        參數:
            source_text: 原始文本
            context_texts: 上下文文本列表
            model_name: 模型名稱
            
        回傳:
            翻譯結果，若不存在則回傳 None
        """
        return self.cache_manager.get_cached_translation(source_text, context_texts, model_name)
    
    def store_translation(self, source_text: str, target_text: str, context_texts: List[str], model_name: str) -> bool:
        """將翻譯結果儲存到快取
        
        參數:
            source_text: 原始文本
            target_text: 翻譯結果
            context_texts: 上下文文本列表
            model_name: 模型名稱
            
        回傳:
            是否儲存成功
        """
        return self.cache_manager.store_translation(source_text, target_text, context_texts, model_name)
    
    def clear_old_cache(self, days_threshold: int = 30) -> int:
        """清理舊的快取
        
        參數:
            days_threshold: 天數閾值，超過此天數的快取將被刪除
            
        回傳:
            刪除的快取數量
        """
        return self.cache_manager.clear_old_cache(days_threshold)
    
    def clear_cache_by_model(self, model_name: str) -> int:
        """按模型清理快取
        
        參數:
            model_name: 模型名稱
            
        回傳:
            刪除的快取數量
        """
        return self.cache_manager.clear_cache_by_model(model_name)
    
    def get_cache_stats(self) -> Dict[str, Any]:
        """獲取快取統計資訊
        
        回傳:
            包含統計資訊的字典
        """
        return self.cache_manager.get_cache_stats()
    
    def optimize_database(self) -> bool:
        """最佳化快取資料庫
        
        回傳:
            是否最佳化成功
        """
        return self.cache_manager.optimize_database()
    
    def export_cache(self, output_path: str) -> bool:
        """匯出快取到檔案
        
        參數:
            output_path: 輸出檔案路徑
            
        回傳:
            是否匯出成功
        """
        return self.cache_manager.export_cache(output_path)
    
    def import_cache(self, input_path: str) -> Tuple[bool, int]:
        """從檔案匯入快取
        
        參數:
            input_path: 輸入檔案路徑
            
        回傳:
            (是否匯入成功, 匯入的快取數量)
        """
        return self.cache_manager.import_cache(input_path)
    
    def cleanup(self) -> None:
        """清理資源"""
        # 目前沒有特殊清理需求
        pass

# 檔案服務 - 管理檔案操作
class FileService:
    """檔案服務，管理檔案的讀取、處理和保存"""
    
    def __init__(self):
        """初始化檔案服務"""
        self.file_handler = FileHandler()
        
        logger.info("檔案服務初始化完成")
    
    def select_files(self) -> List[str]:
        """通過對話框選擇檔案
        
        回傳:
            選定的檔案路徑列表
        """
        return self.file_handler.select_files()
    
    def select_directory(self) -> str:
        """選擇目錄
        
        回傳:
            選定的目錄路徑
        """
        return self.file_handler.select_directory()
    
    def scan_directory(self, directory: str, recursive: bool = True) -> List[str]:
        """掃描目錄下的字幕檔案
        
        參數:
            directory: 目錄路徑
            recursive: 是否遞迴掃描子目錄
            
        回傳:
            找到的檔案路徑列表
        """
        return self.file_handler.scan_directory(directory, recursive)
    
    def get_subtitle_info(self, file_path: str, force_refresh: bool = False) -> Dict[str, Any]:
        """獲取字幕檔案的資訊
        
        參數:
            file_path: 檔案路徑
            force_refresh: 是否強制重新讀取
            
        回傳:
            字幕檔案資訊字典
        """
        return self.file_handler.get_subtitle_info(file_path, force_refresh)
    
    def get_output_path(self, file_path: str, target_lang: str, progress_callback=None) -> Optional[str]:
        """獲取輸出檔案路徑並處理衝突
        
        參數:
            file_path: 原始檔案路徑
            target_lang: 目標語言
            progress_callback: 進度回調函數
            
        回傳:
            輸出檔案路徑，若失敗則回傳 None
        """
        return self.file_handler.get_output_path(file_path, target_lang, progress_callback)
    
    def set_batch_settings(self, settings: Dict[str, Any]) -> None:
        """設定批次處理設定
        
        參數:
            settings: 批次處理設定字典
        """
        self.file_handler.set_batch_settings(settings)
    
    def get_batch_settings(self) -> Dict[str, Any]:
        """獲取批次處理設定
        
        回傳:
            批次處理設定字典
        """
        return self.file_handler.batch_settings
    
    def convert_subtitle_format(self, input_path: str, target_format: str) -> Optional[str]:
        """轉換字幕檔案格式
        
        參數:
            input_path: 輸入檔案路徑
            target_format: 目標格式
            
        回傳:
            輸出檔案路徑，若失敗則回傳 None
        """
        return self.file_handler.convert_subtitle_format(input_path, target_format)
    
    def extract_subtitle(self, video_path: str, callback=None) -> Optional[str]:
        """從影片檔案中提取字幕
        
        參數:
            video_path: 影片檔案路徑
            callback: 回調函數
            
        回傳:
            字幕檔案路徑，若失敗則回傳 None
        """
        return self.file_handler.extract_subtitle(video_path, callback)
    
    def load_api_key(self, file_path: str = "openapi_api_key.txt") -> str:
        """載入API金鑰
        
        參數:
            file_path: API金鑰檔案路徑
            
        回傳:
            API金鑰
        """
        return self.file_handler.load_api_key(file_path)
    
    def save_api_key(self, api_key: str, file_path: str = "openapi_api_key.txt") -> bool:
        """儲存API金鑰
        
        參數:
            api_key: API金鑰
            file_path: API金鑰檔案路徑
            
        回傳:
            是否儲存成功
        """
        return self.file_handler.save_api_key(api_key, file_path)
    
    def handle_drop(self, event) -> List[str]:
        """處理檔案拖放事件
        
        參數:
            event: 拖放事件
            
        回傳:
            檔案路徑列表
        """
        if hasattr(self.file_handler, 'handle_drop'):
            return self.file_handler.handle_drop(event)
        return []
    
    def cleanup(self) -> None:
        """清理資源"""
        # 目前沒有特殊清理需求
        pass

# 進度追蹤服務 - 管理進度回調和統計
class ProgressService:
    """進度追蹤服務，管理進度回調和統計"""
    
    def __init__(self):
        """初始化進度追蹤服務"""
        self.progress_callback = None
        self.complete_callback = None
        self.total = 0
        self.current = 0
        self.start_time = None
        self.end_time = None
        
        logger.info("進度追蹤服務初始化完成")
    
    def register_progress_callback(self, callback: Callable) -> None:
        """註冊進度回調函數
        
        參數:
            callback: 進度回調函數
        """
        self.progress_callback = callback
    
    def register_complete_callback(self, callback: Callable) -> None:
        """註冊完成回調函數
        
        參數:
            callback: 完成回調函數
        """
        self.complete_callback = callback
    
    def set_total(self, total: int) -> None:
        """設置總進度
        
        參數:
            total: 總數量
        """
        self.total = total
        self.current = 0
        self.start_time = time.time()
        self.end_time = None
    
    def set_progress(self, current: int) -> None:
        """設置當前進度
        
        參數:
            current: 當前數量
        """
        self.current = current
        
        # 呼叫進度回調
        if self.progress_callback:
            self.progress_callback(self.current, self.total)
    
    def increment_progress(self, increment: int = 1) -> None:
        """增加進度
        
        參數:
            increment: 增量
        """
        self.current += increment
        
        # 呼叫進度回調
        if self.progress_callback:
            self.progress_callback(self.current, self.total)
        
        # 檢查是否完成
        if self.current >= self.total:
            self.mark_complete()
    
    def mark_complete(self) -> None:
        """標記為完成"""
        self.end_time = time.time()
        
        # 呼叫完成回調
        if self.complete_callback:
            elapsed_time = self.get_elapsed_time_str()
            self.complete_callback("處理完成", elapsed_time)
    
    def get_progress_percentage(self) -> float:
        """獲取進度百分比
        
        回傳:
            進度百分比 (0-100)
        """
        if self.total <= 0:
            return 0
        return (self.current / self.total) * 100
    
    def get_elapsed_time(self) -> float:
        """獲取耗時（秒）
        
        回傳:
            耗時（秒）
        """
        if self.start_time is None:
            return 0
            
        if self.end_time is None:
            return time.time() - self.start_time
            
        return self.end_time - self.start_time
    
    def get_elapsed_time_str(self) -> str:
        """獲取格式化的耗時
        
        回傳:
            格式化的耗時字串
        """
        seconds = self.get_elapsed_time()
        
        if seconds < 60:
            return f"{int(seconds)} 秒"
        
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        
        if minutes < 60:
            return f"{minutes} 分 {seconds} 秒"
        
        hours = int(minutes // 60)
        minutes = int(minutes % 60)
        return f"{hours} 小時 {minutes} 分 {seconds} 秒"
    
    def get_estimated_remaining_time(self) -> float:
        """獲取估計剩餘時間（秒）
        
        回傳:
            估計剩餘時間（秒）
        """
        if self.current <= 0 or self.total <= 0:
            return 0
            
        elapsed = self.get_elapsed_time()
        rate = self.current / elapsed  # 每秒處理數量
        
        if rate <= 0:
            return 0
            
        remaining = self.total - self.current
        return remaining / rate
    
    def get_estimated_remaining_time_str(self) -> str:
        """獲取格式化的估計剩餘時間
        
        回傳:
            格式化的估計剩餘時間字串
        """
        seconds = self.get_estimated_remaining_time()
        
        if seconds < 60:
            return f"{int(seconds)} 秒"
        
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        
        if minutes < 60:
            return f"{minutes} 分 {seconds} 秒"
        
        hours = int(minutes // 60)
        minutes = int(minutes % 60)
        return f"{hours} 小時 {minutes} 分 {seconds} 秒"
    
    def reset(self) -> None:
        """重置進度"""
        self.total = 0
        self.current = 0
        self.start_time = None
        self.end_time = None
    
    def cleanup(self) -> None:
        """清理資源"""
        self.progress_callback = None
        self.complete_callback = None
        self.reset()

# 翻譯任務 - 封裝單個翻譯任務
class TranslationTask(threading.Thread):
    """封裝單個翻譯任務的執行緒類"""
    
    def __init__(self, file_path: str, source_lang: str, target_lang: str, 
                 model_name: str, parallel_requests: int,
                 display_mode: str, llm_type: str,
                 progress_callback=None, complete_callback=None):
        """初始化翻譯任務
        
        參數:
            file_path: 字幕檔案路徑
            source_lang: 來源語言
            target_lang: 目標語言
            model_name: 模型名稱
            parallel_requests: 並行請求數
            display_mode: 顯示模式
            llm_type: LLM類型
            progress_callback: 進度回調函數
            complete_callback: 完成回調函數
        """
        threading.Thread.__init__(self)
        self.daemon = True  # 設置為守護執行緒，主程式退出時自動結束
        
        self.file_path = file_path
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.model_name = model_name
        self.parallel_requests = parallel_requests
        self.display_mode = display_mode
        self.llm_type = llm_type
        self.progress_callback = progress_callback
        self.complete_callback = complete_callback
        
        self._is_running = True
        self._is_paused = False
        self._pause_condition = threading.Condition()
        
        # 服務實例將在執行緒中初始化
        self.translation_service = None
    
    def run(self):
        """執行翻譯任務"""
        try:
            self._run_async()
        except Exception as e:
            logger.error(f"翻譯任務執行失敗: {str(e)}")
            if self.complete_callback:
                self.complete_callback(f"翻譯失敗: {str(e)}", "0 秒")
    
    def _run_async(self):
        """在新的事件循環中執行非同步翻譯"""
        async def async_run():
            # 初始化服務
            self.translation_service = ServiceFactory.get_translation_service()
            
            # 執行翻譯
            success, result = await self.translation_service.translate_subtitle_file(
                self.file_path,
                self.source_lang,
                self.target_lang,
                self.model_name,
                self.parallel_requests,
                self.display_mode,
                self.llm_type,
                self._progress_wrapper,
                self._complete_wrapper
            )
        
        # 建立新的事件循環
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            loop.run_until_complete(async_run())
        finally:
            loop.close()
    
    def _progress_wrapper(self, current, total, extra_data=None):
        """進度回調包裝器，處理暫停狀態"""
        # 檢查是否暫停
        with self._pause_condition:
            while self._is_paused and self._is_running:
                self._pause_condition.wait()
        
        # 如果已停止則不再更新進度
        if not self._is_running:
            return
        
        # 呼叫原始進度回調
        if self.progress_callback:
            self.progress_callback(current, total, extra_data)
    
    def _complete_wrapper(self, message, elapsed_time):
        """完成回調包裝器"""
        # 呼叫原始完成回調
        if self.complete_callback and self._is_running:
            self.complete_callback(message, elapsed_time)
    
    def stop(self):
        """停止翻譯任務"""
        self._is_running = False
        self.resume()  # 確保暫停的執行緒能夠繼續並檢查停止標誌
    
    def pause(self):
        """暫停翻譯任務"""
        with self._pause_condition:
            self._is_paused = True
    
    def resume(self):
        """恢復翻譯任務"""
        with self._pause_condition:
            self._is_paused = False
            self._pause_condition.notify_all()
    
    def is_paused(self) -> bool:
        """檢查任務是否已暫停"""
        return self._is_paused
    
    def is_alive(self) -> bool:
        """檢查任務是否仍在執行"""
        return super().is_alive() and self._is_running

# 翻譯任務管理器 - 管理多個翻譯任務
class TranslationTaskManager:
    """翻譯任務管理器，管理多個翻譯任務"""
    
    def __init__(self):
        """初始化翻譯任務管理器"""
        self.tasks = {}  # 檔案路徑 -> 任務
        self.total_files = 0
        self.completed_files = 0
        
        # 配置管理器
        self.config_manager = ConfigManager.get_instance("user")
        
        logger.info("翻譯任務管理器初始化完成")
    
    def start_translation(self, files: List[str], 
                        source_lang: str, target_lang: str, 
                        model_name: str, parallel_requests: int,
                        display_mode: str, llm_type: str,
                        progress_callback=None, complete_callback=None) -> bool:
        """開始翻譯多個檔案
        
        參數:
            files: 字幕檔案路徑列表
            source_lang: 來源語言
            target_lang: 目標語言
            model_name: 模型名稱
            parallel_requests: 並行請求數
            display_mode: 顯示模式
            llm_type: LLM類型
            progress_callback: 進度回調函數
            complete_callback: 完成回調函數
            
        回傳:
            是否成功啟動翻譯
        """
        if not files:
            logger.warning("沒有選擇要翻譯的檔案")
            return False
        
        # 重置任務統計
        self.total_files = len(files)
        self.completed_files = 0
        
        # 建立並啟動任務
        for file_path in files:
            task = TranslationTask(
                file_path,
                source_lang,
                target_lang,
                model_name,
                parallel_requests,
                display_mode,
                llm_type,
                progress_callback,
                self._complete_wrapper(file_path, complete_callback)
            )
            
            self.tasks[file_path] = task
            task.start()
            
        logger.info(f"已啟動 {len(files)} 個翻譯任務")
        return True
    
    def _complete_wrapper(self, file_path: str, original_callback):
        """包裝完成回調函數，以便追蹤已完成的檔案數"""
        def wrapper(message, elapsed_time):
            self.completed_files += 1
            
            # 修改消息以包含總進度
            extended_message = f"{message} | 總進度: {self.completed_files}/{self.total_files}"
            
            # 呼叫原始回調
            if original_callback:
                original_callback(extended_message, elapsed_time)
            
            # 移除已完成的任務
            if file_path in self.tasks:
                del self.tasks[file_path]
        
        return wrapper
    
    def stop_all(self) -> None:
        """停止所有翻譯任務"""
        for task in self.tasks.values():
            task.stop()
        
        # 清空任務列表
        self.tasks.clear()
        logger.info("已停止所有翻譯任務")
    
    def pause_all(self) -> None:
        """暫停所有翻譯任務"""
        for task in self.tasks.values():
            task.pause()
        logger.info("已暫停所有翻譯任務")
    
    def resume_all(self) -> None:
        """恢復所有翻譯任務"""
        for task in self.tasks.values():
            task.resume()
        logger.info("已恢復所有翻譯任務")
    
    def is_any_running(self) -> bool:
        """檢查是否有任務正在執行
        
        回傳:
            是否有任務正在執行
        """
        return any(task.is_alive() for task in self.tasks.values())
    
    def is_all_paused(self) -> bool:
        """檢查是否所有任務都已暫停
        
        回傳:
            是否所有任務都已暫停
        """
        if not self.tasks:
            return False
        return all(task.is_paused() for task in self.tasks.values() if task.is_alive())
    
    def get_active_task_count(self) -> int:
        """獲取活躍任務數量
        
        回傳:
            活躍任務數量
        """
        return sum(1 for task in self.tasks.values() if task.is_alive())
    
    def cleanup(self) -> None:
        """清理資源"""
        self.stop_all()

# 測試程式碼
if __name__ == "__main__":
    async def test():
        try:
            # 設定測試模式
            os.environ["TEST_MODE"] = "1"
            
            # 初始化服務
            translation_service = ServiceFactory.get_translation_service()
            model_service = ServiceFactory.get_model_service()
            cache_service = ServiceFactory.get_cache_service()
            file_service = ServiceFactory.get_file_service()
            
            # 測試模型服務
            print("\n=== 測試模型服務 ===")
            status = await model_service.get_provider_status()
            print(f"提供者狀態: {status}")
            
            # 測試翻譯一個簡單文本
            print("\n=== 測試翻譯服務 ===")
            text = "こんにちは、世界"
            context = ["前の文", "こんにちは、世界", "次の文"]
            
            result = await translation_service.translate_text(
                text, context, "ollama", "mistral"
            )
            print(f"翻譯結果: {result}")
            
            # 測試快取服務
            print("\n=== 測試快取服務 ===")
            cache_stats = cache_service.get_cache_stats()
            print(f"快取統計: {cache_stats}")
            
            # 清理服務
            await model_service.cleanup()
            
        except Exception as e:
            print(f"測試失敗: {str(e)}")
            import traceback
            traceback.print_exc()

    # 執行測試
    if os.environ.get("RUN_TEST", "0") == "1":
        asyncio.run(test())
        