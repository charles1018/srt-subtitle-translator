# translation_manager.py
import asyncio
import threading
import pysrt
from typing import Optional
import logging
from logging.handlers import TimedRotatingFileHandler
from translation_client import TranslationClient
from file_handler import FileHandler
import time

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

class TranslationManager:
    def __init__(self, file_path: str, source_lang: str, target_lang: str, 
                 model_name: str, parallel_requests: int, progress_callback, complete_callback, 
                 display_mode: str, llm_type: str, api_key: str = None):
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
        self.file_handler = FileHandler()
        self.ollama_client = None
        self.semaphore = asyncio.Semaphore(parallel_requests)
        self.running = True
        self.pause_event = asyncio.Event()
        self.pause_event.set()
        self.start_time = None  # 記錄開始時間

    async def initialize(self):
        """初始化翻譯管理器"""
        self.ollama_client = await TranslationClient(self.llm_type, api_key=self.api_key).__aenter__()

    async def cleanup(self):
        """清理資源"""
        if self.ollama_client:
            try:
                await self.ollama_client.__aexit__(None, None, None)
            except Exception as e:
                logger.error(f"清理資源時發生錯誤: {str(e)}")

    def pause(self):
        """暫停翻譯"""
        self.pause_event.clear()

    def resume(self):
        """恢復翻譯"""
        self.pause_event.set()

    def stop(self):
        """停止翻譯"""
        self.running = False
        self.resume()

    async def translate_subtitles(self):
        """翻譯字幕檔案，OpenAI 使用優化的批次處理方式"""
        try:
            self.start_time = time.time()
            subs = pysrt.open(self.file_path)
            total_subs = len(subs)
            translated_count = 0
            
            # 為 OpenAI 和 Ollama 優化批次大小
            if self.llm_type == 'openai':
                batch_size = min(5, self.parallel_requests)  # OpenAI 使用較小批次
            else:
                batch_size = self.optimize_batch_size(total_subs)  # Ollama 使用原始策略

            logger.info(f"開始翻譯檔案: {self.file_path}, 總字幕數: {total_subs}, 批次大小: {batch_size}, 顯示模式: {self.display_mode}")

            for i in range(0, total_subs, batch_size):
                if not self.running:
                    logger.info("翻譯被用戶停止")
                    break

                await self.pause_event.wait()
                
                batch = subs[i:i + batch_size]
                
                # 準備這個批次的翻譯請求
                translation_requests = []
                for sub in batch:
                    context_start = max(0, subs.index(sub) - 5)
                    context_end = min(len(subs), subs.index(sub) + 6)
                    context = [s.text for s in subs[context_start:context_end]]
                    translation_requests.append((sub.text, context))
                
                # OpenAI 使用優化的批次翻譯
                if self.llm_type == 'openai':
                    translations = await self.ollama_client.translate_batch(translation_requests, self.model_name)
                    
                    # 應用翻譯結果
                    for idx, sub in enumerate(batch):
                        if idx < len(translations) and translations[idx]:
                            translation = translations[idx]
                            if self.display_mode == "target_only":
                                sub.text = translation
                            elif self.display_mode == "target_above_source":
                                sub.text = f"{translation}\n{sub.text}"
                            elif self.display_mode == "source_above_target":
                                sub.text = f"{sub.text}\n{translation}"
                            translated_count += 1
                            self.progress_callback(translated_count, total_subs)
                
                # Ollama 使用原始並行方式
                else:
                    tasks = []
                    for sub in batch:
                        context_start = max(0, subs.index(sub) - 5)
                        context_end = min(len(subs), subs.index(sub) + 6)
                        context = [s.text for s in subs[context_start:context_end]]
                        
                        async with self.semaphore:
                            task = asyncio.create_task(
                                self.ollama_client.translate_text(sub.text, context, self.model_name)
                            )
                            tasks.append((sub, task))

                    for sub, task in tasks:
                        try:
                            translation = await task
                            if translation:
                                if self.display_mode == "target_only":
                                    sub.text = translation
                                elif self.display_mode == "target_above_source":
                                    sub.text = f"{translation}\n{sub.text}"
                                elif self.display_mode == "source_above_target":
                                    sub.text = f"{sub.text}\n{translation}"
                                translated_count += 1
                                self.progress_callback(translated_count, total_subs)
                        except Exception as e:
                            logger.error(f"翻譯字幕 '{sub.text}' 時發生錯誤: {str(e)}", exc_info=True)
                            continue

            # 在所有翻譯完成後立即計算耗時
            if self.running:
                elapsed_time = time.time() - self.start_time
                elapsed_str = self.format_elapsed_time(elapsed_time)
                logger.info(f"翻譯完成，總耗時: {elapsed_str}")

                output_path = self.file_handler.get_output_path(self.file_path, self.target_lang, 
                                                               self.progress_callback)
                if output_path:
                    subs.save(output_path, encoding='utf-8')
                    self.complete_callback(f"翻譯完成 | 檔案已成功保存為: {output_path}", elapsed_str)
                else:
                    self.complete_callback(f"已跳過檔案: {self.file_path}", elapsed_str)

        except Exception as e:
            logger.error(f"翻譯過程中發生異常: {str(e)}", exc_info=True)
            self.complete_callback(f"翻譯過程中發生錯誤: {str(e)}", "未知")

    def optimize_batch_size(self, total_subs: int) -> int:
        """根據字幕總數優化批次大小"""
        if total_subs < 100:
            return min(self.parallel_requests, total_subs)
        elif total_subs < 500:
            return min(self.parallel_requests * 2, total_subs)
        else:
            return min(self.parallel_requests * 3, total_subs)

    def format_elapsed_time(self, seconds: float) -> str:
        """格式化耗時為易讀格式"""
        minutes = int(seconds // 60)
        seconds = int(seconds % 60)
        return f"{minutes} 分 {seconds} 秒" if minutes > 0 else f"{seconds} 秒"

class TranslationThread(threading.Thread):
    """翻譯線程"""
    def __init__(self, file_path, source_lang, target_lang, model_name, parallel_requests, 
                 progress_callback, complete_callback, display_mode: str, llm_type: str, api_key: str = None):
        threading.Thread.__init__(self)
        self.manager = None
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

    def run(self):
        """運行翻譯線程"""
        async def async_run():
            self.manager = TranslationManager(
                self.file_path, self.source_lang, self.target_lang, self.model_name,
                self.parallel_requests, self.progress_callback, self.complete_callback, 
                self.display_mode, self.llm_type, self.api_key
            )
            await self.manager.initialize()
            try:
                await self.manager.translate_subtitles()
            finally:
                await self.manager.cleanup()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(async_run())
        loop.close()

    def stop(self):
        """停止翻譯"""
        if self.manager:
            self.manager.stop()

    def pause(self):
        """暫停翻譯"""
        if self.manager:
            self.manager.pause()

    def resume(self):
        """恢復翻譯"""
        if self.manager:
            self.manager.resume()

# 測試代碼
if __name__ == "__main__":
    def progress(current, total):
        print(f"進度: {current}/{total}")

    def complete(message, elapsed_time):
        print(f"{message} | 耗時: {elapsed_time}")

    thread = TranslationThread("test.srt", "日文", "繁體中文", "test_model", 2, progress, complete, "target_only", "ollama")
    thread.start()
    thread.join()