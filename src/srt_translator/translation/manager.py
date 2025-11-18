import asyncio
import hashlib
import json
import logging
import os
import pickle
import re
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from typing import Any, Dict, List, Tuple

import pysrt

# 從新模組導入
from srt_translator.core.config import ConfigManager, get_config
from srt_translator.services.factory import ServiceFactory
from srt_translator.utils import (
    TranslationError,
    format_elapsed_time,
    format_exception,
)

# 設定日誌
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 確保日誌目錄存在
os.makedirs('logs', exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = TimedRotatingFileHandler(
        filename='logs/translation_manager.log',
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

@dataclass
class TranslationStats:
    """翻譯統計資訊類別"""
    started_at: float = 0                # 開始時間（時間戳）
    finished_at: float = 0               # 結束時間（時間戳）
    total_subtitles: int = 0             # 總字幕數
    translated_count: int = 0            # 已翻譯數量
    failed_count: int = 0                # 失敗數量
    skipped_count: int = 0               # 跳過數量
    cached_count: int = 0                # 快取命中數量
    total_chars: int = 0                 # 總字元數
    total_wait_time: float = 0           # 總等待時間
    total_processing_time: float = 0     # 總處理時間
    batch_count: int = 0                 # 批次數量
    retry_count: int = 0                 # 重試次數
    errors: List[str] = None             # 錯誤訊息列表

    def __post_init__(self):
        if self.errors is None:
            self.errors = []

    def get_elapsed_time(self) -> float:
        """取得總耗時（秒）"""
        if self.finished_at == 0:
            return time.time() - self.started_at
        return self.finished_at - self.started_at

    def get_formatted_elapsed_time(self) -> str:
        """取得格式化的耗時字串"""
        return format_elapsed_time(self.get_elapsed_time())

    def get_translation_speed(self) -> float:
        """取得翻譯速度（字幕/分鐘）"""
        mins = self.get_elapsed_time() / 60
        if mins == 0:
            return 0
        return self.translated_count / mins

    def get_char_speed(self) -> float:
        """取得翻譯速度（字元/分鐘）"""
        mins = self.get_elapsed_time() / 60
        if mins == 0:
            return 0
        return self.total_chars / mins

    def get_summary(self) -> Dict[str, Any]:
        """取得統計摘要資訊"""
        return {
            "總字幕數": self.total_subtitles,
            "已翻譯": self.translated_count,
            "失敗": self.failed_count,
            "跳過": self.skipped_count,
            "快取命中": self.cached_count,
            "總字元數": self.total_chars,
            "總耗時": self.get_formatted_elapsed_time(),
            "翻譯速度": f"{self.get_translation_speed():.1f} 字幕/分鐘",
            "字元速度": f"{self.get_char_speed():.1f} 字元/分鐘",
            "批次數": self.batch_count,
            "重試次數": self.retry_count
        }

class TranslationManager:
    """翻譯管理器類別，處理字幕檔案的翻譯"""

    def __init__(self, file_path: str, source_lang: str, target_lang: str,
                 model_name: str, parallel_requests: int, progress_callback, complete_callback,
                 display_mode: str, llm_type: str, api_key: str = None):
        """初始化翻譯管理器
        
        參數:
            file_path: 字幕檔案路徑
            source_lang: 來源語言
            target_lang: 目標語言
            model_name: 模型名稱
            parallel_requests: 並行請求數
            progress_callback: 進度回調函數
            complete_callback: 完成回調函數
            display_mode: 顯示模式
            llm_type: LLM類型
            api_key: API金鑰（可選）
        """
        self.file_path = file_path
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.model_name = model_name
        self.parallel_requests = parallel_requests
        self.progress_callback = progress_callback
        self.complete_callback = complete_callback
        self.display_mode = display_mode
        self.llm_type = llm_type
        self.api_key = api_key

        # 初始化服務
        self.translation_service = ServiceFactory.get_translation_service()
        self.file_service = ServiceFactory.get_file_service()
        self.cache_service = ServiceFactory.get_cache_service()
        self.progress_service = ServiceFactory.get_progress_service()

        # 初始化專有名詞詞典
        self._key_terms_dict = {}

        # 控制狀態
        self.running = True
        self.pause_event = asyncio.Event()
        self.pause_event.set()

        # 並發控制
        self.semaphore = asyncio.Semaphore(parallel_requests)

        # 統計資訊
        self.stats = TranslationStats()

        # 恢復狀態
        self.checkpoint_path = self._get_checkpoint_path()
        self.translated_indices = set()  # 已翻譯的索引集合

        # 批次處理設定
        self.min_batch_size = 1
        self.max_batch_size = 20
        self.adaptive_batch_size = parallel_requests
        self.batch_growth_rate = 1.5   # 每次成功後增加的倍率
        self.batch_shrink_rate = 0.5   # 每次失敗後減少的倍率

        # 上下文視窗大小
        self.context_window = get_config("model", "context_window", 3)  # 上下文視窗大小 (每側，從 5 改為 3 以減少 AI 混淆)

        # 重試設定
        self.max_retries = get_config("model", "max_retries", 3)
        self.retry_delay = get_config("model", "retry_delay", 1.0)

        logger.info(f"初始化翻譯管理器: {file_path}, 模型: {model_name}, 顯示模式: {display_mode}")

    def _post_process_translation(self, original_text: str, translated_text: str) -> str:
        """對翻譯結果進行後處理，包括專有名詞統一和移除標點符號
        
        參數:
            original_text: 原始文字
            translated_text: 翻譯文字
            
        回傳:
            後處理後的翻譯文字
        """
        # 1. 處理專有名詞統一
        # 使用正則表達式識別可能的專有名詞（假設專有名詞通常是2-6個漢字的連續序列）
        potential_terms = re.findall(r'[\u4e00-\u9fff]{2,6}', translated_text)

        # 對於每個潛在的專有名詞，檢查是否已在詞典中
        for term in potential_terms:
            # 如果該詞已在詞典中，用標準形式替換
            if term in self._key_terms_dict:
                translated_text = translated_text.replace(term, self._key_terms_dict[term])
            # 否則添加到詞典，以當前形式作為標準
            elif len(term) >= 2:  # 只考慮至少兩個字的詞
                self._key_terms_dict[term] = term

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

    def _save_key_terms_dictionary(self) -> None:
        """儲存專有名詞詞典到檔案"""
        try:
            # 檢查詞典大小，如果太小則不儲存
            if len(self._key_terms_dict) <= 2:
                return

            # 構建檔案路徑，使用影片名稱
            base_name = os.path.splitext(os.path.basename(self.file_path))[0]
            dict_path = os.path.join("data", "terms_dictionaries", f"{base_name}_terms.json")

            # 確保目錄存在
            os.makedirs(os.path.dirname(dict_path), exist_ok=True)

            # 儲存詞典
            with open(dict_path, 'w', encoding='utf-8') as f:
                json.dump(self._key_terms_dict, f, ensure_ascii=False, indent=2)

            logger.info(f"已儲存 {len(self._key_terms_dict)} 個專有名詞到檔案: {dict_path}")
        except Exception as e:
            logger.error(f"儲存專有名詞詞典失敗: {e!s}")

    def _get_checkpoint_path(self) -> str:
        """取得檢查點檔案路徑"""
        # 使用檔案路徑和目標語言建立唯一的檢查點檔名
        checkpoints_dir = get_config("app", "checkpoints_dir", "data/checkpoints")
        file_hash = hashlib.md5(f"{self.file_path}_{self.target_lang}_{self.model_name}".encode()).hexdigest()[:10]
        return os.path.join(checkpoints_dir, f"checkpoint_{file_hash}.pkl")

    def _save_checkpoint(self) -> None:
        """儲存翻譯進度檢查點"""
        try:
            # 確保目錄存在
            os.makedirs(os.path.dirname(self.checkpoint_path), exist_ok=True)

            # 儲存已翻譯索引和統計資訊
            checkpoint_data = {
                "file_path": self.file_path,
                "target_lang": self.target_lang,
                "model_name": self.model_name,
                "translated_indices": list(self.translated_indices),
                "stats": self.stats,
                "timestamp": datetime.now().isoformat(),
                "key_terms_dict": self._key_terms_dict  # 添加專有名詞詞典
            }

            with open(self.checkpoint_path, 'wb') as f:
                pickle.dump(checkpoint_data, f)

            logger.debug(f"已儲存翻譯進度到檢查點: {self.checkpoint_path}")
        except Exception as e:
            logger.error(f"儲存翻譯進度檢查點失敗: {e!s}")

    def _load_checkpoint(self) -> bool:
        """載入翻譯進度檢查點"""
        try:
            if not os.path.exists(self.checkpoint_path):
                return False

            with open(self.checkpoint_path, 'rb') as f:
                checkpoint_data = pickle.load(f)

            # 檢查檢查點是否與目前任務相符
            if (checkpoint_data.get("file_path") == self.file_path and
                checkpoint_data.get("target_lang") == self.target_lang and
                checkpoint_data.get("model_name") == self.model_name):

                # 恢復已翻譯索引
                self.translated_indices = set(checkpoint_data.get("translated_indices", []))

                # 恢復專有名詞詞典
                if "key_terms_dict" in checkpoint_data:
                    self._key_terms_dict = checkpoint_data["key_terms_dict"]

                # 恢復統計資訊（除了時間）
                saved_stats = checkpoint_data.get("stats")
                if saved_stats:
                    self.stats.total_subtitles = saved_stats.total_subtitles
                    self.stats.translated_count = saved_stats.translated_count
                    self.stats.failed_count = saved_stats.failed_count
                    self.stats.skipped_count = saved_stats.skipped_count
                    self.stats.cached_count = saved_stats.cached_count
                    self.stats.total_chars = saved_stats.total_chars
                    self.stats.batch_count = saved_stats.batch_count
                    self.stats.retry_count = saved_stats.retry_count
                    self.stats.errors = saved_stats.errors.copy() if saved_stats.errors else []

                logger.info(f"已從檢查點恢復翻譯進度: {len(self.translated_indices)} 個已翻譯字幕，" +
                           f"{len(self._key_terms_dict)} 個專有名詞")
                return True
            else:
                logger.warning("檢查點與目前任務不符，將重新開始翻譯")
                return False
        except Exception as e:
            logger.error(f"載入翻譯進度檢查點失敗: {e!s}")
            return False

    def _clean_checkpoint(self) -> None:
        """清理檢查點檔案"""
        try:
            if os.path.exists(self.checkpoint_path):
                os.remove(self.checkpoint_path)
                logger.debug(f"已清理檢查點檔案: {self.checkpoint_path}")
        except Exception as e:
            logger.error(f"清理檢查點檔案失敗: {e!s}")

    async def initialize(self) -> None:
        """初始化翻譯管理器"""
        try:
            # 取得翻譯服務（已經由 ServiceFactory 初始化）

            # 載入進度檢查點
            self._load_checkpoint()

            logger.info(f"翻譯管理器初始化完成: {self.llm_type}, 模型: {self.model_name}")
        except Exception as e:
            logger.error(f"初始化翻譯管理器失敗: {e!s}")
            raise TranslationError(f"初始化翻譯管理器失敗: {e!s}")

    async def cleanup(self) -> None:
        """清理資源"""
        # 不需要清理資源，因為服務由 ServiceFactory 管理
        logger.info("翻譯管理器清理完成")

    def pause(self) -> None:
        """暫停翻譯"""
        logger.info("翻譯暫停")
        self.pause_event.clear()

        # 儲存目前進度
        self._save_checkpoint()

    def resume(self) -> None:
        """恢復翻譯"""
        logger.info("翻譯恢復")
        self.pause_event.set()

    def stop(self) -> None:
        """停止翻譯"""
        logger.info("翻譯停止")
        self.running = False
        self.resume()  # 確保暫停事件被清除，以便能夠退出

    def _adjust_batch_size(self, success: bool) -> None:
        """根據批次處理結果動態調整批次大小"""
        if success:
            # 成功時增加批次大小
            new_size = int(self.adaptive_batch_size * self.batch_growth_rate)
            self.adaptive_batch_size = min(new_size, self.max_batch_size)
        else:
            # 失敗時減小批次大小
            new_size = max(int(self.adaptive_batch_size * self.batch_shrink_rate), self.min_batch_size)
            self.adaptive_batch_size = new_size

        logger.debug(f"調整批次大小到: {self.adaptive_batch_size}")

    def _compute_optimal_batch_size(self, total_subs: int) -> int:
        """根據字幕總數和目前效能計算最佳批次大小"""
        # 基礎邏輯：檔案更大時使用更大的批次
        if self.llm_type == 'openai':
            # OpenAI有速率限制，使用較小批次
            base_size = min(5, self.parallel_requests)
        else:
            # Ollama本地執行，可使用較大批次
            if total_subs < 100:
                base_size = min(self.parallel_requests, total_subs)
            elif total_subs < 500:
                base_size = min(self.parallel_requests * 2, total_subs)
            else:
                base_size = min(self.parallel_requests * 3, total_subs)

        # 使用自適應大小（如果存在）
        return min(self.adaptive_batch_size or base_size, base_size)

    async def _get_context_for_subtitle(self, subs: List, index: int) -> List[str]:
        """取得字幕的上下文"""
        context_start = max(0, index - self.context_window)
        context_end = min(len(subs), index + self.context_window + 1)
        return [s.text for s in subs[context_start:context_end]]

    async def _process_subtitle_batch(self, subs: List, batch_indices: List[int]) -> Tuple[int, int, int]:
        """處理一批字幕翻譯
        
        回傳:
            Tuple[成功數, 失敗數, 跳過數]
        """
        if not batch_indices:
            return 0, 0, 0

        # 統計計數
        success_count = 0
        failed_count = 0
        skipped_count = 0

        # 準備批量翻譯請求
        translation_requests = []
        request_map = {}  # 映射 request_idx -> subtitle_idx

        # 建構請求列表，並跳過已翻譯的
        for i, idx in enumerate(batch_indices):
            if idx in self.translated_indices:
                skipped_count += 1
                continue

            sub = subs[idx]
            context = await self._get_context_for_subtitle(subs, idx)
            translation_requests.append((sub.text, context))
            request_map[len(translation_requests) - 1] = idx
            self.stats.total_chars += len(sub.text)

        # 如果所有字幕都已被翻譯，直接回傳
        if not translation_requests:
            return 0, 0, skipped_count

        try:
            # 批量翻譯
            translations = await self.translation_service.translate_batch(
                translation_requests,
                self.llm_type,
                self.model_name,
                self.parallel_requests
            )

            # 處理結果
            for req_idx, translation in enumerate(translations):
                if req_idx not in request_map:
                    continue

                sub_idx = request_map[req_idx]
                sub = subs[sub_idx]

                if not translation or "[翻譯錯誤" in translation:
                    failed_count += 1
                    error_msg = translation if translation else "空白翻譯結果"
                    self.stats.errors.append(f"字幕 {sub_idx}: {error_msg}")
                    continue

                # 進行後處理
                processed_translation = self._post_process_translation(sub.text, translation)

                # 應用翻譯
                self._apply_translation(sub, processed_translation)
                self.translated_indices.add(sub_idx)
                success_count += 1

                # 更新進度
                self.stats.translated_count += 1
                if self.progress_callback:
                    self.progress_callback(self.stats.translated_count, self.stats.total_subtitles)

            # 更新自適應批次大小
            self._adjust_batch_size(failed_count == 0)
            return success_count, failed_count, skipped_count

        except Exception as e:
            logger.error(f"批量翻譯失敗: {e!s}")
            # 調整批次大小
            self._adjust_batch_size(False)

            # 降級到單個字幕處理
            tasks = []
            for i, (text, context) in enumerate(translation_requests):
                sub_idx = request_map[i]
                sub = subs[sub_idx]
                tasks.append(self._translate_single_subtitle(sub, sub_idx, subs))

            # 等待所有任務完成
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 處理結果
            for result in results:
                if isinstance(result, Exception):
                    logger.error(f"字幕翻譯任務異常: {result!s}")
                    failed_count += 1
                    self.stats.errors.append(f"任務異常: {result!s}")
                    continue

                if result == True:  # 成功翻譯
                    success_count += 1
                elif result == False:  # 翻譯失敗
                    failed_count += 1

            return success_count, failed_count, skipped_count

    async def _translate_single_subtitle(self, sub, index: int, all_subs: List) -> bool:
        """翻譯單個字幕
        
        回傳:
            bool: 是否成功翻譯
        """
        if not sub.text.strip():
            self.translated_indices.add(index)
            return True

        try:
            # 取得上下文
            context = await self._get_context_for_subtitle(all_subs, index)

            # 使用重試機制
            async with self.semaphore:
                # 等待暫停事件
                await self.pause_event.wait()
                if not self.running:
                    return False

                # 嘗試翻譯
                for retry in range(self.max_retries + 1):
                    try:
                        if retry > 0:
                            self.stats.retry_count += 1
                            logger.info(f"重試翻譯字幕 {index} (第{retry}次)")
                            await asyncio.sleep(self.retry_delay * retry)

                        # 使用翻譯服務
                        translation = await self.translation_service.translate_text(
                            sub.text, context, self.llm_type, self.model_name
                        )

                        # 檢查翻譯結果
                        if not translation or "[翻譯錯誤" in translation:
                            if retry < self.max_retries:
                                continue
                            error_msg = translation if translation else "空白翻譯結果"
                            self.stats.errors.append(f"字幕 {index}: {error_msg}")
                            self.stats.failed_count += 1
                            return False

                        # 進行後處理 - 專有名詞統一與移除標點符號
                        processed_translation = self._post_process_translation(sub.text, translation)

                        # 應用翻譯
                        self._apply_translation(sub, processed_translation)
                        self.translated_indices.add(index)

                        # 更新統計和進度
                        self.stats.translated_count += 1
                        if self.progress_callback:
                            self.progress_callback(self.stats.translated_count, self.stats.total_subtitles)
                        return True

                    except Exception as e:
                        if retry < self.max_retries:
                            logger.warning(f"字幕 {index} 翻譯失敗，將重試: {e!s}")
                            continue
                        logger.error(f"字幕 {index} 翻譯失敗: {e!s}")
                        self.stats.errors.append(f"字幕 {index}: {e!s}")
                        self.stats.failed_count += 1
                        return False

        except Exception as e:
            logger.error(f"處理字幕 {index} 時發生異常: {e!s}")
            self.stats.errors.append(f"字幕 {index}: {e!s}")
            self.stats.failed_count += 1
            return False

        return False  # 不應到達這裡

    def _apply_translation(self, subtitle, translation: str) -> None:
        """根據顯示模式套用翻譯結果"""
        if self.display_mode == "僅顯示翻譯":
            subtitle.text = translation
        elif self.display_mode == "翻譯在上":
            subtitle.text = f"{translation}\n{subtitle.text}"
        elif self.display_mode == "原文在上" or self.display_mode == "雙語對照":
            subtitle.text = f"{subtitle.text}\n{translation}"
        else:
            # 預設行為，使用雙語對照
            subtitle.text = f"{subtitle.text}\n{translation}"

    async def translate_subtitles(self) -> None:
        """翻譯字幕檔案"""
        try:
            # 記錄開始時間
            self.stats.started_at = time.time()

            # 開啟SRT檔案
            subs = pysrt.open(self.file_path, encoding='utf-8')
            self.stats.total_subtitles = len(subs)

            # 確定未處理的字幕索引
            pending_indices = [i for i in range(len(subs)) if i not in self.translated_indices]

            # 計算初始批次大小
            batch_size = self._compute_optimal_batch_size(len(pending_indices))

            logger.info(f"開始翻譯檔案: {self.file_path}")
            logger.info(f"總字幕數: {self.stats.total_subtitles}, 待翻譯: {len(pending_indices)}")
            logger.info(f"初始批次大小: {batch_size}, 並行請求數: {self.parallel_requests}")
            logger.info(f"顯示模式: {self.display_mode}, LLM類型: {self.llm_type}, 模型: {self.model_name}")

            # 分批翻譯
            for i in range(0, len(pending_indices), batch_size):
                if not self.running:
                    logger.info("翻譯被使用者停止")
                    break

                # 等待暫停事件
                await self.pause_event.wait()

                # 提取本批次待處理的索引
                batch_indices = pending_indices[i:i + batch_size]

                # 處理該批次
                self.stats.batch_count += 1
                batch_start = time.time()

                logger.info(f"處理批次 {self.stats.batch_count}: {len(batch_indices)} 個字幕")
                success, failed, skipped = await self._process_subtitle_batch(subs, batch_indices)

                batch_time = time.time() - batch_start
                self.stats.total_processing_time += batch_time

                logger.info(f"批次 {self.stats.batch_count} 完成: 成功={success}, 失敗={failed}, 跳過={skipped}, 耗時={batch_time:.2f}秒")

                # 每批次後儲存進度
                if self.running:
                    self._save_checkpoint()

                # 動態調整批次大小
                if i + batch_size < len(pending_indices):
                    batch_size = self._compute_optimal_batch_size(len(pending_indices) - (i + batch_size))

            # 翻譯完成後儲存檔案
            if self.running:
                # 記錄完成時間
                self.stats.finished_at = time.time()
                elapsed_str = self.stats.get_formatted_elapsed_time()

                logger.info(f"翻譯完成，總耗時: {elapsed_str}")
                logger.info(f"翻譯統計: {json.dumps(self.stats.get_summary(), ensure_ascii=False)}")

                # 儲存專有名詞詞典
                self._save_key_terms_dictionary()

                # 取得輸出路徑並儲存檔案
                output_path = self.file_service.get_output_path(self.file_path, self.target_lang,
                                                               self.progress_callback)
                if output_path:
                    subs.save(output_path, encoding='utf-8')

                    if self.complete_callback:
                        self.complete_callback(f"翻譯完成 | 檔案已成功儲存為: {output_path}", elapsed_str)
                    logger.info(f"檔案已儲存為: {output_path}")

                    # 清理檢查點
                    self._clean_checkpoint()
                else:
                    if self.complete_callback:
                        self.complete_callback(f"已跳過檔案: {self.file_path}", elapsed_str)
                    logger.info(f"檔案已跳過: {self.file_path}")

        except Exception as e:
            logger.error(f"翻譯過程中發生異常: {e!s}", exc_info=True)
            self.stats.finished_at = time.time()
            elapsed_str = self.stats.get_formatted_elapsed_time()

            if self.complete_callback:
                self.complete_callback(f"翻譯過程中發生錯誤: {e!s}", elapsed_str)

            raise TranslationError(f"翻譯過程中發生錯誤: {e!s}")


class TranslationThread(threading.Thread):
    """翻譯執行緒"""
    def __init__(self, file_path, source_lang, target_lang, model_name, parallel_requests,
                 display_mode, llm_type, progress_callback=None, complete_callback=None, api_key=None):
        """初始化翻譯執行緒
        
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
            api_key: API金鑰（可選）
        """
        threading.Thread.__init__(self)
        self.daemon = True  # 設置為守護執行緒，主程式退出時自動結束
        self.manager = None
        self.file_path = file_path
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.model_name = model_name
        self.parallel_requests = parallel_requests
        self.display_mode = display_mode
        self.llm_type = llm_type
        self.progress_callback = progress_callback
        self.complete_callback = complete_callback
        self.api_key = api_key

        self._is_running = True
        self._is_paused = False
        self._pause_condition = threading.Condition()

        logger.info(f"初始化翻譯執行緒: {file_path}")

    def run(self):
        """執行翻譯執行緒"""
        try:
            self._run_async()
        except Exception as e:
            logger.error(f"翻譯執行緒運行時發生錯誤: {format_exception(e)}")
            if self.complete_callback:
                self.complete_callback(f"翻譯失敗: {e!s}", "0 秒")

    def _run_async(self):
        """在新的事件循環中執行非同步翻譯"""
        async def async_run():
            # 初始化翻譯管理器
            self.manager = TranslationManager(
                self.file_path,
                self.source_lang,
                self.target_lang,
                self.model_name,
                self.parallel_requests,
                self._progress_wrapper,
                self._complete_wrapper,
                self.display_mode,
                self.llm_type,
                self.api_key
            )

            # 初始化管理器
            await self.manager.initialize()

            try:
                # 執行翻譯
                await self.manager.translate_subtitles()
            except Exception as e:
                logger.error(f"翻譯執行失敗: {e!s}", exc_info=True)
                raise
            finally:
                # 清理資源
                await self.manager.cleanup()

        # 建立新的事件循環
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        try:
            loop.run_until_complete(async_run())
        except Exception as e:
            logger.error(f"執行事件循環時發生錯誤: {format_exception(e)}")
            raise
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
        # 如果有管理器，也停止管理器
        if self.manager:
            self.manager.stop()
        # 恢復暫停的執行緒以檢查停止標誌
        self.resume()

    def pause(self):
        """暫停翻譯任務"""
        with self._pause_condition:
            self._is_paused = True
            # 如果有管理器，也暫停管理器
            if self.manager:
                self.manager.pause()

    def resume(self):
        """恢復翻譯任務"""
        with self._pause_condition:
            self._is_paused = False
            self._pause_condition.notify_all()
            # 如果有管理器，也恢復管理器
            if self.manager:
                self.manager.resume()

    def is_paused(self) -> bool:
        """檢查任務是否已暫停"""
        return self._is_paused

    def is_alive(self) -> bool:
        """檢查任務是否仍在執行"""
        return super().is_alive() and self._is_running

    def get_statistics(self) -> Dict[str, Any]:
        """取得翻譯統計資訊"""
        if self.manager and hasattr(self.manager, 'stats'):
            return self.manager.stats.get_summary()
        return {}


# 用於管理多個翻譯任務的任務管理器
class TranslationTaskManager:
    """翻譯任務管理器，管理多個翻譯任務"""

    def __init__(self):
        """初始化翻譯任務管理器"""
        self.tasks = {}  # 檔案路徑 -> 任務
        self.total_files = 0
        self.completed_files = 0

        # 配置管理器
        self.config_manager = ConfigManager.get_instance("user")

        # 服務
        self.translation_service = ServiceFactory.get_translation_service()

        logger.info("初始化翻譯任務管理器")

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

        # 獲取 API 金鑰
        api_key = None
        if llm_type == "openai":
            model_service = ServiceFactory.get_model_service()
            api_key = model_service.api_keys.get("openai")

        # 建立並啟動任務
        for file_path in files:
            task = TranslationThread(
                file_path,
                source_lang,
                target_lang,
                model_name,
                parallel_requests,
                display_mode,
                llm_type,
                progress_callback,
                self._complete_wrapper(file_path, complete_callback),
                api_key
            )

            self.tasks[file_path] = task
            task.start()

        logger.info(f"已啟動 {len(files)} 個翻譯任務")
        return True

    def _complete_wrapper(self, file_path: str, original_callback):
        """包裝完成回調函數，以便追蹤已完成的檔案數"""
        def wrapper(message, elapsed_time):
            """內部包裝函數，在執行原始回調前更新完成計數"""
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
        for task in list(self.tasks.values()):
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


# 測試程式碼
if __name__ == "__main__":
    # 設定控制台日誌以便於測試
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    def progress(current, total, extra_data=None):
        """回調函數，打印翻譯進度

        參數:
            current: 當前完成的字幕數
            total: 總字幕數
            extra_data: 額外的進度信息
        """
        print(f"進度: {current}/{total}")

    def complete(message, elapsed_time):
        """回調函數，打印翻譯完成信息和耗時

        參數:
            message: 完成消息
            elapsed_time: 耗時（秒）
        """
        print(f"{message} | 耗時: {elapsed_time}")

    import sys
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
    else:
        test_file = "test.srt"  # 預設測試檔案

    # 使用任務管理器測試
    async def test_async():
        # 初始化服務
        translation_service = ServiceFactory.get_translation_service()

        # 建立任務管理器
        manager = TranslationTaskManager()

        # 啟動翻譯
        manager.start_translation(
            [test_file],
            "日文",
            "繁體中文",
            "llama3",
            2,
            "雙語對照",
            "ollama",
            progress,
            complete
        )

        # 等待所有任務完成
        while manager.is_any_running():
            await asyncio.sleep(1)

        print("所有任務已完成")

    # 執行測試
    if __name__ == "__main__":
        asyncio.run(test_async())
