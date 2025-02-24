import tkinter as tk
from tkinter import ttk, filedialog, messagebox, Menu
import os
import sys
import pysrt
import json
import urllib.request
import asyncio
import threading
import aiohttp
import hashlib
import sqlite3
from datetime import datetime
from typing import Optional, Dict, List, Tuple
from queue import Queue
from dataclasses import dataclass
import backoff
from pathlib import Path

# 嘗試導入 tkinterdnd2
try:
    from tkinterdnd2 import *
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False
    print("警告：未安裝 tkinterdnd2 模組，拖放功能將被停用")

# 設置 Ollama 並行請求數
os.environ['OLLAMA_NUM_PARALLEL'] = '8'

@dataclass
class TranslationCache:
    source_text: str
    target_text: str
    context_hash: str
    model_name: str
    created_at: datetime
    usage_count: int

class CacheManager:
    def __init__(self, db_path: str = "translation_cache.db"):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        """初始化緩存數據庫"""
        def adapt_datetime(dt):
            return dt.isoformat()

        def convert_datetime(s):
            try:
                return datetime.fromisoformat(s.decode())
            except:
                return datetime.now()

        # 註冊自定義的datetime處理器
        sqlite3.register_adapter(datetime, adapt_datetime)
        sqlite3.register_converter("timestamp", convert_datetime)

        with sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS translations (
                    source_text TEXT,
                    target_text TEXT,
                    context_hash TEXT,
                    model_name TEXT,
                    created_at timestamp,
                    usage_count INTEGER,
                    PRIMARY KEY (source_text, context_hash, model_name)
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_context ON translations(context_hash)")

    def _compute_context_hash(self, context_texts: List[str]) -> str:
        """計算上下文的哈希值"""
        context_str = "".join(context_texts)
        return hashlib.md5(context_str.encode()).hexdigest()

    def get_cached_translation(self, source_text: str, context_texts: List[str], model_name: str) -> Optional[str]:
        """獲取緩存的翻譯結果"""
        context_hash = self._compute_context_hash(context_texts)
        
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute("""
                SELECT target_text, usage_count 
                FROM translations 
                WHERE source_text = ? AND context_hash = ? AND model_name = ?
            """, (source_text, context_hash, model_name))
            
            result = cursor.fetchone()
            if result:
                target_text, usage_count = result
                conn.execute("""
                    UPDATE translations 
                    SET usage_count = ? 
                    WHERE source_text = ? AND context_hash = ? AND model_name = ?
                """, (usage_count + 1, source_text, context_hash, model_name))
                return target_text
        return None

    def store_translation(self, source_text: str, target_text: str, context_texts: List[str], model_name: str):
        """存儲翻譯結果到緩存"""
        context_hash = self._compute_context_hash(context_texts)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO translations 
                (source_text, target_text, context_hash, model_name, created_at, usage_count)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source_text, target_text, context_hash, model_name, datetime.now(), 1))

class OllamaClient:
    def __init__(self, base_url: str = "http://localhost:11434"):
        self.base_url = base_url
        self.cache_manager = CacheManager()
        self.session = None
        self._retries = 3
        self._backoff_factor = 2

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    @backoff.on_exception(backoff.expo,
                         (aiohttp.ClientError, asyncio.TimeoutError),
                         max_tries=3)
    async def translate_text(self, text: str, context_texts: List[str], model_name: str) -> str:
        """翻譯文本，包含重試和緩存機制"""
        # 檢查緩存
        cached_result = self.cache_manager.get_cached_translation(text, context_texts, model_name)
        if cached_result:
            return cached_result

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": """You are a professional translator for 日本A片字幕檔(影片類型主要是亂倫、性交、虐待、凌辱、變態等非正常影片)。
請嚴格遵守以下規則：
1. 只輸出翻譯後的文本，不要有任何其他回應(不要有開場白，不要輸出警告，也不要有任何的解釋)，內容前後不要有"「"、"」"。
2. 保持原文的語氣和表達方式。
3. 根據提供的上下文（前後五句字幕）並考量保留常見英文專有名詞,確保翻譯準確且符合台灣的表達習慣。
4. 內容轉換成台灣人習慣的說法,可依語境增加在地化元素,重點是要讓台灣讀者覺得貼近生活。
5. 如果看到省略號(...)，保留在譯文中。
6. 禁止輸出任何非翻譯內容。"""
                },
                {
                    "role": "user",
                    "content": f"以下是字幕內容（提供前後5句作為上下文參考）：\n{json.dumps(context_texts, ensure_ascii=False)}\n請將當前字幕翻譯：\n'{text}'"
                }
            ],
            "stream": False,
            "temperature": 0.1
        }

        async with self.session.post(
            f"{self.base_url}/v1/chat/completions",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30)
        ) as response:
            response.raise_for_status()
            result = await response.json()
            translation = result['choices'][0]['message']['content'].strip()
            
            # 存入緩存
            self.cache_manager.store_translation(text, translation, context_texts, model_name)
            
            return translation

class TranslationManager:
    def __init__(self, file_path: str, source_lang: str, target_lang: str, 
                 model_name: str, parallel_requests: int, progress_callback, complete_callback):
        self.file_path = file_path
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.model_name = model_name
        self.parallel_requests = parallel_requests
        self.progress_callback = progress_callback
        self.complete_callback = complete_callback
        self.ollama_client = None
        self.semaphore = asyncio.Semaphore(parallel_requests)
        self.running = True
        self.pause_event = asyncio.Event()
        self.pause_event.set()

    async def initialize(self):
        """初始化翻譯管理器"""
        self.ollama_client = await OllamaClient().__aenter__()

    async def cleanup(self):
        """清理資源"""
        if self.ollama_client:
            await self.ollama_client.__aexit__(None, None, None)

    def pause(self):
        """暫停翻譯"""
        self.pause_event.clear()

    def resume(self):
        """恢復翻譯"""
        self.pause_event.set()

    def stop(self):
        """停止翻譯"""
        self.running = False
        self.resume()  # 確保不會卡在暫停狀態

    async def translate_subtitles(self):
        """翻譯字幕檔案"""
        try:
            subs = pysrt.open(self.file_path)
            total_subs = len(subs)
            translated_count = 0
            batch_size = self.optimize_batch_size(total_subs)

            for i in range(0, total_subs, batch_size):
                if not self.running:
                    break

                await self.pause_event.wait()  # 檢查是否暫停

                batch = subs[i:i+batch_size]
                tasks = []

                for sub in batch:
                    # 獲取上下文
                    context_start = max(0, subs.index(sub)-5)
                    context_end = min(len(subs), subs.index(sub)+6)
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
                            sub.text = translation
                            translated_count += 1
                            self.progress_callback(translated_count, total_subs)
                    except Exception as e:
                        print(f"翻譯錯誤: {str(e)}")
                        continue

            if self.running:
                output_path = self.get_output_path()
                if output_path:
                    subs.save(output_path, encoding='utf-8')
                    self.complete_callback(f"翻譯完成 | 檔案已成功保存為: {output_path}")
                else:
                    self.complete_callback(f"已跳過檔案: {self.file_path}")

        except Exception as e:
            self.complete_callback(f"翻譯過程中發生錯誤: {str(e)}")

    def optimize_batch_size(self, total_subs: int) -> int:
        """根據字幕總數優化批次大小"""
        if total_subs < 100:
            return min(self.parallel_requests, total_subs)
        elif total_subs < 500:
            return min(self.parallel_requests * 2, total_subs)
        else:
            return min(self.parallel_requests * 3, total_subs)

    def get_output_path(self) -> Optional[str]:
        """獲取輸出文件路徑"""
        dir_name, file_name = os.path.split(self.file_path)
        name, ext = os.path.splitext(file_name)
        lang_suffix = {"繁體中文": ".zh_tw", "英文": ".en", "日文": ".jp"}
        base_path = os.path.join(dir_name, f"{name}{lang_suffix[self.target_lang]}{ext}")
        
        if os.path.exists(base_path):
            queue = Queue()
            self.progress_callback(-1, -1, {"type": "file_conflict", "path": base_path, "queue": queue})
            response = queue.get()
            
            if response == "rename":
                counter = 1
                while True:
                    new_path = os.path.join(dir_name, f"{name}{lang_suffix[self.target_lang]}_{counter}{ext}")
                    if not os.path.exists(new_path):
                        return new_path
                    counter += 1
            elif response == "skip":
                return None
            
        return base_path

class TranslationThread(threading.Thread):
    """翻譯線程"""
    def __init__(self, file_path, source_lang, target_lang, model_name, parallel_requests, progress_callback, complete_callback):
        threading.Thread.__init__(self)
        self.manager = None
        self.file_path = file_path
        self.source_lang = source_lang
        self.target_lang = target_lang
        self.model_name = model_name
        self.parallel_requests = parallel_requests
        self.progress_callback = progress_callback
        self.complete_callback = complete_callback

    def run(self):
        """運行翻譯線程"""
        async def async_run():
            self.manager = TranslationManager(
                self.file_path,
                self.source_lang,
                self.target_lang,
                self.model_name,
                self.parallel_requests,
                self.progress_callback,
                self.complete_callback
            )
            await self.manager.initialize()
            await self.manager.translate_subtitles()
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

class App(TkinterDnD.Tk if TKDND_AVAILABLE else tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SRT 字幕翻譯器")
        self.geometry("600x500")
        self.translation_threads = {}  # 存儲正在運行的翻譯線程
        
        if TKDND_AVAILABLE:
            self.drop_target_register(DND_FILES)
            self.dnd_bind('<<Drop>>', self.handle_drop)

        self.create_widgets()
        self.protocol("WM_DELETE_WINDOW", self.on_closing)  # 處理窗口關閉事件

    def create_widgets(self):
        """創建界面元素"""
        # 檔案操作框架
        file_frame = ttk.Frame(self)
        file_frame.pack(pady=10)

        # 檔案選擇按鈕
        self.file_button = ttk.Button(file_frame, text="選擇 SRT 檔案", command=self.select_files)
        self.file_button.pack(side=tk.LEFT, padx=5)

        # 檔案列表
        self.file_list = tk.Listbox(self, width=70, height=10, selectmode=tk.SINGLE)
        self.file_list.pack(pady=10)
        
        # 綁定滑鼠事件
        self.file_list.bind('<Button-3>', self.show_context_menu)  # 右鍵選單
        self.file_list.bind('<B1-Motion>', self.drag_item)         # 拖曳
        self.file_list.bind('<ButtonRelease-1>', self.drop_item)   # 放開
        
        # 創建右鍵選單
        self.context_menu = Menu(self, tearoff=0)
        self.context_menu.add_command(label="移除", command=self.remove_selected)
        
        # 用於追踪拖曳
        self.drag_data = {"index": None, "y": 0}
        
        # 語言選擇框架
        lang_frame = ttk.Frame(self)
        lang_frame.pack(pady=10)

        ttk.Label(lang_frame, text="原文語言:").grid(row=0, column=0)
        self.source_lang = ttk.Combobox(lang_frame, values=["日文", "英文", "自動偵測"])
        self.source_lang.set("日文")
        self.source_lang.grid(row=0, column=1)

        ttk.Label(lang_frame, text="目標語言:").grid(row=0, column=2)
        self.target_lang = ttk.Combobox(lang_frame, values=["繁體中文", "英文", "日文"])
        self.target_lang.set("繁體中文")
        self.target_lang.grid(row=0, column=3)

        # 模型選擇和並行請求數量框架
        model_frame = ttk.Frame(self)
        model_frame.pack(pady=10)

        ttk.Label(model_frame, text="選擇模型:").grid(row=0, column=0)
        self.model_combo = ttk.Combobox(model_frame, values=self.get_model_list())
        self.model_combo.set("huihui_ai/aya-expanse-abliterated:latest")
        self.model_combo.grid(row=0, column=1)

        ttk.Label(model_frame, text="並行請求數:").grid(row=0, column=2)
        self.parallel_requests = ttk.Combobox(model_frame, values=["1", "2", "3", "4", "5", "6", "7", "8"])
        self.parallel_requests.set("6")
        self.parallel_requests.grid(row=0, column=3)

        # 控制按鈕框架
        control_frame = ttk.Frame(self)
        control_frame.pack(pady=10)

        # 翻譯按鈕
        self.translate_button = ttk.Button(control_frame, text="開始翻譯", command=self.start_translation)
        self.translate_button.pack(side=tk.LEFT, padx=5)

        # 暫停/繼續按鈕
        self.pause_button = ttk.Button(control_frame, text="暫停", command=self.toggle_pause, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=5)

        # 停止按鈕
        self.stop_button = ttk.Button(control_frame, text="停止", command=self.stop_translation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        # 進度條
        self.progress_bar = ttk.Progressbar(self, length=400, mode='determinate')
        self.progress_bar.pack(pady=10)

        # 狀態標籤
        self.status_label = ttk.Label(self, text="", wraplength=550, justify="center")
        self.status_label.pack(pady=10, fill=tk.X, expand=True)

    def select_files(self):
        """選擇檔案"""
        files = filedialog.askopenfilenames(filetypes=[("SRT files", "*.srt")])
        for file in files:
            self.file_list.insert(tk.END, file)

    def get_model_list(self):
        """獲取可用的模型列表"""
        model_patterns = ['llama', 'mixtral', 'aya', 'yi', 'qwen', 'solar', 
                         'mistral', 'openchat', 'neural', 'phi', 'stable',
                         'dolphin', 'vicuna', 'zephyr', 'gemma', 'deepseek']
        default_model = "huihui_ai/aya-expanse-abliterated:latest"
        
        try:
            # 嘗試先使用 /api/tags
            req = urllib.request.Request("http://localhost:11434/api/tags")
            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                models = set()  # 使用集合來避免重複
                
                # 處理 tags API 返回的數據
                if isinstance(result.get('models'), list):
                    for model in result['models']:
                        if isinstance(model, dict) and 'name' in model:
                            model_name = model['name']
                            if any(pattern in model_name.lower() for pattern in model_patterns):
                                models.add(model_name)
                
                # 如果 tags API 沒有返回足夠的模型，嘗試使用 api/show
                if len(models) < 2:  # 如果找到的模型太少
                    req = urllib.request.Request("http://localhost:11434/api/show")
                    with urllib.request.urlopen(req) as response:
                        show_result = json.loads(response.read().decode('utf-8'))
                        if isinstance(show_result, list):
                            for model in show_result:
                                if isinstance(model, dict) and 'name' in model:
                                    model_name = model['name']
                                    if any(pattern in model_name.lower() for pattern in model_patterns):
                                        models.add(model_name)
                
                # 確保默認模型在列表中
                models.add(default_model)
                
                # 轉換為排序後的列表
                model_list = sorted(list(models))
                
                # 將默認模型移到最前面
                if default_model in model_list:
                    model_list.remove(default_model)
                    model_list.insert(0, default_model)
                
                return model_list if model_list else [default_model]
                
        except Exception as e:
            print(f"獲取模型列表時發生錯誤: {str(e)}")
            return [default_model]

    def start_translation(self):
        """開始翻譯"""
        if not self.file_list.size():
            messagebox.showwarning("警告", "請先選擇要翻譯的檔案")
            return

        self.translate_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL)
        self.progress_bar['value'] = 0
        self.status_label.config(text="")

        for i in range(self.file_list.size()):
            file_path = self.file_list.get(i)
            thread = TranslationThread(
                file_path, 
                self.source_lang.get(), 
                self.target_lang.get(), 
                self.model_combo.get(),
                int(self.parallel_requests.get()),
                self.update_progress,
                self.translation_completed
            )
            self.translation_threads[file_path] = thread
            thread.start()

        self.status_label.config(text=f"正在翻譯 {self.file_list.size()} 個檔案...")

    def stop_translation(self):
        """停止翻譯"""
        for thread in self.translation_threads.values():
            thread.stop()
        self.translation_threads.clear()
        self.reset_ui()

    def toggle_pause(self):
        """切換暫停/繼續狀態"""
        is_paused = self.pause_button.cget("text") == "繼續"
        for thread in self.translation_threads.values():
            if is_paused:
                thread.resume()
                self.pause_button.config(text="暫停")
            else:
                thread.pause()
                self.pause_button.config(text="繼續")

    def reset_ui(self):
        """重置UI狀態"""
        self.translate_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        self.pause_button.config(text="暫停")
        self.progress_bar['value'] = 0

    def update_progress(self, current, total, extra_data=None):
        """更新進度"""
        if extra_data and extra_data.get("type") == "file_conflict":
            response = messagebox.askyesnocancel(
                "檔案已存在",
                f"檔案 {extra_data['path']} 已存在。\n是否覆蓋？\n'是' = 覆蓋\n'否' = 重新命名\n'取消' = 跳過",
                icon="warning"
            )
            
            if response is True:
                result = "overwrite"
            elif response is False:
                result = "rename"
            else:
                result = "skip"
            
            extra_data["queue"].put(result)
            return
            
        if current >= 0 and total >= 0:
            percentage = int(current / total * 100)
            self.progress_bar['value'] = percentage
            self.status_label.config(text=f"正在翻譯第 {current}/{total} 句字幕 ({percentage}%)")
            self.update_idletasks()

    def translation_completed(self, message):
        """翻譯完成回調"""
        current_text = self.status_label.cget("text")
        self.status_label.config(text=f"{current_text}\n{message}")

    def show_context_menu(self, event):
        """顯示右鍵選單"""
        try:
            index = self.file_list.nearest(event.y)
            if index >= 0:
                self.file_list.selection_clear(0, tk.END)
                self.file_list.selection_set(index)
                self.context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.context_menu.grab_release()

    def remove_selected(self):
        """移除選中的檔案"""
        try:
            selected = self.file_list.curselection()
            if selected:
                self.file_list.delete(selected)
        except Exception as e:
            messagebox.showerror("錯誤", f"移除檔案時發生錯誤：{str(e)}")

    def drag_item(self, event):
        """處理檔案拖曳"""
        if self.drag_data["index"] is None:
            index = self.file_list.nearest(event.y)
            if index >= 0:
                self.drag_data["index"] = index
                self.drag_data["y"] = event.y
        else:
            new_index = self.file_list.nearest(event.y)
            if new_index >= 0 and new_index != self.drag_data["index"]:
                item = self.file_list.get(self.drag_data["index"])
                self.file_list.delete(self.drag_data["index"])
                self.file_list.insert(new_index, item)
                self.drag_data["index"] = new_index
                self.drag_data["y"] = event.y

    def drop_item(self, event):
        """處理檔案放開"""
        self.drag_data = {"index": None, "y": 0}

    def handle_drop(self, event):
        """處理檔案拖放"""
        files = self.tk.splitlist(event.data)
        for file in files:
            if file.lower().endswith('.srt'):
                file = file.strip('{}')  # 在 Windows 上移除檔案路徑的大括號
                self.file_list.insert(tk.END, file)
            else:
                messagebox.showwarning("警告", f"檔案 {file} 不是 SRT 格式，已略過")

    def on_closing(self):
        """處理窗口關閉事件"""
        if self.translation_threads:
            if messagebox.askokcancel("確認", "正在進行翻譯，確定要關閉程式嗎？"):
                self.stop_translation()
                self.quit()
        else:
            self.quit()

if __name__ == "__main__":
    app = App()
    app.mainloop()