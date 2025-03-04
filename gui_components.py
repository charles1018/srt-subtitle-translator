import os
import tkinter as tk
from tkinter import ttk, filedialog, scrolledtext, messagebox
from typing import Callable, List, Dict, Any, Optional
import threading
import json
import queue
from pathlib import Path
import logging
from logging.handlers import TimedRotatingFileHandler
from datetime import datetime

# 嘗試導入拖放功能模組
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False

# 設定日誌記錄
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 確保日誌目錄存在
os.makedirs('logs', exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = TimedRotatingFileHandler(
        filename='logs/gui.log',
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

class GUIComponents:
    """GUI 組件類，用於創建和管理翻譯器介面"""
    
    def __init__(self, root, start_callback, pause_callback, stop_callback, 
                 progress_callback, complete_callback, prompt_manager=None):
        """
        初始化 GUI 組件
        
        參數：
            root: Tkinter 根視窗
            start_callback: 開始翻譯的回呼函數
            pause_callback: 暫停/繼續翻譯的回呼函數
            stop_callback: 停止翻譯的回呼函數
            progress_callback: 更新進度的回呼函數
            complete_callback: 完成翻譯的回呼函數
            prompt_manager: 提示詞管理器
        """
        self.root = root
        self.start_callback = start_callback
        self.pause_callback = pause_callback
        self.stop_callback = stop_callback
        self.progress_callback = progress_callback
        self.complete_callback = complete_callback
        self.prompt_manager = prompt_manager
        
        # 用於儲存選中的檔案
        self.selected_files = []
        
        # 創建控制項變數
        self.source_lang = tk.StringVar(value="日文")
        self.target_lang = tk.StringVar(value="繁體中文")
        self.llm_type = tk.StringVar(value="ollama")
        self.model_combo_var = tk.StringVar()
        self.parallel_requests = tk.StringVar(value="3")
        self.display_mode = tk.StringVar(value="雙語對照")
        
        # 主題色彩
        self.load_theme_settings()
        
        # 初始化介面元素
        self.create_menu()
        
        logger.info("GUI 組件初始化完成")
    
    def load_theme_settings(self):
        """載入主題設定"""
        try:
            theme_file = "config/theme_settings.json"
            if os.path.exists(theme_file):
                with open(theme_file, 'r', encoding='utf-8') as f:
                    theme = json.load(f)
                    
                # 設定主題色彩
                self.colors = theme.get("colors", {
                    "primary": "#3498db",
                    "secondary": "#2ecc71",
                    "background": "#f0f0f0",
                    "text": "#333333",
                    "accent": "#e74c3c",
                    "button": "#3498db",
                    "button_hover": "#2980b9"
                })
            else:
                # 預設主題色彩
                self.colors = {
                    "primary": "#3498db",
                    "secondary": "#2ecc71",
                    "background": "#f0f0f0",
                    "text": "#333333",
                    "accent": "#e74c3c",
                    "button": "#3498db",
                    "button_hover": "#2980b9"
                }
        except Exception as e:
            logger.error(f"載入主題設定失敗: {str(e)}")
            # 預設主題色彩
            self.colors = {
                "primary": "#3498db",
                "secondary": "#2ecc71",
                "background": "#f0f0f0",
                "text": "#333333",
                "accent": "#e74c3c",
                "button": "#3498db",
                "button_hover": "#2980b9"
            }
    
    def create_menu(self):
        """創建選單列"""
        menu_bar = tk.Menu(self.root)
        
        # 檔案選單
        file_menu = tk.Menu(menu_bar, tearoff=0)
        file_menu.add_command(label="選擇檔案", command=self.browse_files)
        file_menu.add_command(label="選擇資料夾", command=self.browse_folder)
        file_menu.add_separator()
        file_menu.add_command(label="清除選中", command=self.clear_selection)
        file_menu.add_separator()
        file_menu.add_command(label="退出", command=self.root.quit)
        menu_bar.add_cascade(label="檔案", menu=file_menu)
        
        # 設定選單
        settings_menu = tk.Menu(menu_bar, tearoff=0)
        settings_menu.add_command(label="提示詞編輯", command=self.open_prompt_editor)
        settings_menu.add_command(label="緩存管理", command=self.open_cache_manager)
        settings_menu.add_command(label="進階設定", command=self.open_advanced_settings)
        menu_bar.add_cascade(label="設定", menu=settings_menu)
        
        # 關於選單
        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="使用說明", command=self.show_help)
        help_menu.add_command(label="關於", command=self.show_about)
        menu_bar.add_cascade(label="幫助", menu=help_menu)
        
        # 設置選單列
        self.root.config(menu=menu_bar)
    
    def setup(self):
        """設置介面"""
        # 主框架
        main_frame = ttk.Frame(self.root, padding=10)
        main_frame.pack(fill=tk.BOTH, expand=True)
        
        # 上半部分 - 檔案選擇和設定
        top_frame = ttk.Frame(main_frame)
        top_frame.pack(fill=tk.BOTH, pady=(0, 10))
        
        # 檔案選擇部分
        file_frame = ttk.LabelFrame(top_frame, text="檔案選擇", padding=10)
        file_frame.pack(fill=tk.BOTH, side=tk.LEFT, expand=True)
        
        # 檔案列表框架和捲動條
        list_frame = ttk.Frame(file_frame)
        list_frame.pack(fill=tk.BOTH, expand=True)
        
        # 檔案列表
        self.file_listbox = tk.Listbox(list_frame, selectmode=tk.EXTENDED, height=8)
        self.file_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # 捲動條
        scrollbar = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.file_listbox.yview)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.file_listbox.config(yscrollcommand=scrollbar.set)
        
        # 檔案按鈕框架
        file_buttons_frame = ttk.Frame(file_frame)
        file_buttons_frame.pack(fill=tk.X, pady=(10, 0))
        
        # 檔案按鈕
        ttk.Button(file_buttons_frame, text="選擇檔案", command=self.browse_files).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(file_buttons_frame, text="選擇資料夾", command=self.browse_folder).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(file_buttons_frame, text="清除選中", command=self.clear_selection).pack(side=tk.LEFT)
        
        # 如果支援拖放，設置拖放目標
        if TKDND_AVAILABLE:
            self.file_listbox.drop_target_register(DND_FILES)
            self.file_listbox.dnd_bind('<<Drop>>', self.handle_drop)
            
            # 添加拖放提示
            drop_label = ttk.Label(file_frame, text="支援拖放檔案", foreground="gray")
            drop_label.pack(pady=(5, 0))
        
        # 語言設定和模型選擇
        settings_frame = ttk.LabelFrame(top_frame, text="翻譯設定", padding=10)
        settings_frame.pack(fill=tk.BOTH, side=tk.RIGHT, expand=True, padx=(10, 0))
        
        # 創建表格佈局
        settings_grid = ttk.Frame(settings_frame)
        settings_grid.pack(fill=tk.BOTH, expand=True)
        
        # 語言設定
        ttk.Label(settings_grid, text="源語言:").grid(row=0, column=0, sticky=tk.W, pady=5)
        source_langs = ["日文", "英文", "韓文", "簡體中文", "繁體中文"]
        ttk.Combobox(settings_grid, textvariable=self.source_lang, values=source_langs, width=10, state="readonly").grid(row=0, column=1, sticky=tk.W, pady=5)
        
        ttk.Label(settings_grid, text="目標語言:").grid(row=1, column=0, sticky=tk.W, pady=5)
        target_langs = ["繁體中文", "英文", "日文", "韓文", "簡體中文"]
        ttk.Combobox(settings_grid, textvariable=self.target_lang, values=target_langs, width=10, state="readonly").grid(row=1, column=1, sticky=tk.W, pady=5)
        
        # LLM 類型和模型選擇
        ttk.Label(settings_grid, text="LLM類型:").grid(row=2, column=0, sticky=tk.W, pady=5)
        llm_types = ["ollama", "openai"]
        self.llm_combobox = ttk.Combobox(settings_grid, textvariable=self.llm_type, values=llm_types, width=10, state="readonly")
        self.llm_combobox.grid(row=2, column=1, sticky=tk.W, pady=5)
        self.llm_combobox.bind("<<ComboboxSelected>>", self.on_llm_type_changed)
        
        ttk.Label(settings_grid, text="模型:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.model_combo = ttk.Combobox(settings_grid, textvariable=self.model_combo_var, width=15, state="readonly")
        self.model_combo.grid(row=3, column=1, sticky=tk.W, pady=5)
        
        # 顯示模式和並行請求
        ttk.Label(settings_grid, text="顯示模式:").grid(row=0, column=2, sticky=tk.W, pady=5, padx=(10, 0))
        display_modes = ["雙語對照", "僅顯示翻譯", "翻譯在上", "原文在上"]
        ttk.Combobox(settings_grid, textvariable=self.display_mode, values=display_modes, width=10, state="readonly").grid(row=0, column=3, sticky=tk.W, pady=5)
        
        ttk.Label(settings_grid, text="並行請求:").grid(row=1, column=2, sticky=tk.W, pady=5, padx=(10, 0))
        parallel_options = ["1", "2", "3", "4", "5", "10", "15", "20"]
        ttk.Combobox(settings_grid, textvariable=self.parallel_requests, values=parallel_options, width=5, state="readonly").grid(row=1, column=3, sticky=tk.W, pady=5)
        
        # 內容類型
        ttk.Label(settings_grid, text="內容類型:").grid(row=2, column=2, sticky=tk.W, pady=5, padx=(10, 0))
        if self.prompt_manager:
            content_types = self.prompt_manager.get_available_content_types()
            self.content_type_var = tk.StringVar(value=self.prompt_manager.current_content_type)
            self.content_type_combo = ttk.Combobox(settings_grid, textvariable=self.content_type_var, 
                                                  values=content_types, width=10, state="readonly")
            self.content_type_combo.grid(row=2, column=3, sticky=tk.W, pady=5)
            self.content_type_combo.bind("<<ComboboxSelected>>", self.on_content_type_changed)
        else:
            content_types = ["general", "anime", "movie", "documentary", "adult"]
            self.content_type_var = tk.StringVar(value="general")
            self.content_type_combo = ttk.Combobox(settings_grid, textvariable=self.content_type_var, 
                                                  values=content_types, width=10, state="readonly")
            self.content_type_combo.grid(row=2, column=3, sticky=tk.W, pady=5)

        # 翻譯風格
        ttk.Label(settings_grid, text="翻譯風格:").grid(row=3, column=2, sticky=tk.W, pady=5, padx=(10, 0))
        if self.prompt_manager:
            styles = list(self.prompt_manager.get_available_styles().keys())
            self.style_var = tk.StringVar(value=self.prompt_manager.current_style)
            self.style_combo = ttk.Combobox(settings_grid, textvariable=self.style_var, 
                                           values=styles, width=10, state="readonly")
            self.style_combo.grid(row=3, column=3, sticky=tk.W, pady=5)
            self.style_combo.bind("<<ComboboxSelected>>", self.on_style_changed)
        else:
            styles = ["standard", "literal", "literary", "localized", "concise", "formal", "casual"]
            self.style_var = tk.StringVar(value="standard")
            self.style_combo = ttk.Combobox(settings_grid, textvariable=self.style_var, 
                                           values=styles, width=10, state="readonly")
            self.style_combo.grid(row=3, column=3, sticky=tk.W, pady=5)

        # 下半部分 - 狀態和控制
        bottom_frame = ttk.Frame(main_frame)
        bottom_frame.pack(fill=tk.BOTH, expand=True)
        
        # 進度框架
        progress_frame = ttk.LabelFrame(bottom_frame, text="翻譯進度", padding=10)
        progress_frame.pack(fill=tk.BOTH, expand=True)
        
        # 進度條
        self.progress_bar = ttk.Progressbar(progress_frame, orient=tk.HORIZONTAL, mode="determinate", length=100)
        self.progress_bar.pack(fill=tk.X, pady=(0, 10))
        
        # 狀態訊息
        status_frame = ttk.Frame(progress_frame)
        status_frame.pack(fill=tk.X)
        
        self.status_label = ttk.Label(status_frame, text="準備就緒", anchor=tk.W)
        self.status_label.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.total_files_label = ttk.Label(status_frame, text="總進度: 0/0 檔案完成")
        self.total_files_label.pack(side=tk.RIGHT)
        
        # 控制按鈕
        button_frame = ttk.Frame(main_frame)
        button_frame.pack(fill=tk.X, pady=(10, 0))
        
        # 建立按鈕樣式
        style = ttk.Style()
        style.configure("Primary.TButton", foreground="white", background=self.colors["primary"], font=("Arial", 10, "bold"))
        style.map("Primary.TButton", background=[("active", self.colors["button_hover"])])
        
        style.configure("Success.TButton", foreground="white", background=self.colors["secondary"], font=("Arial", 10, "bold"))
        style.map("Success.TButton", background=[("active", "#27ae60")])  # 深綠色
        
        style.configure("Danger.TButton", foreground="white", background=self.colors["accent"], font=("Arial", 10, "bold"))
        style.map("Danger.TButton", background=[("active", "#c0392b")])  # 深紅色
        
        # 建立並放置按鈕
        self.start_button = ttk.Button(button_frame, text="開始翻譯", command=self.start_callback, style="Success.TButton", width=15)
        self.start_button.pack(side=tk.LEFT, padx=(0, 10))
        
        self.pause_button = ttk.Button(button_frame, text="暫停", command=self.toggle_pause, style="Primary.TButton", width=15)
        self.pause_button.pack(side=tk.LEFT, padx=(0, 10))
        self.pause_button.config(state=tk.DISABLED)
        
        self.stop_button = ttk.Button(button_frame, text="停止", command=self.stop_callback, style="Danger.TButton", width=15)
        self.stop_button.pack(side=tk.LEFT)
        self.stop_button.config(state=tk.DISABLED)
        
        # 設定按鈕
        self.settings_button = ttk.Button(button_frame, text="進階設定", command=self.open_advanced_settings, width=15)
        self.settings_button.pack(side=tk.RIGHT)
        
        # 初始狀態為禁用暫停和停止按鈕
        self.pause_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        
        logger.info("GUI 介面設置完成")
    
    def browse_files(self):
        """瀏覽並選擇字幕檔案"""
        filetypes = [
            ("字幕檔案", "*.srt;*.vtt;*.ass;*.ssa;*.sub"),
            ("SRT檔案", "*.srt"),
            ("VTT檔案", "*.vtt"),
            ("ASS檔案", "*.ass;*.ssa"),
            ("SUB檔案", "*.sub"),
            ("所有檔案", "*.*")
        ]
        
        files = filedialog.askopenfilenames(
            title="選擇字幕檔案",
            filetypes=filetypes
        )
        
        if files:
            self.add_files(files)
    
    def browse_folder(self):
        """瀏覽並選擇含有字幕檔案的資料夾"""
        folder = filedialog.askdirectory(title="選擇資料夾")
        if folder:
            # 搜尋資料夾中的字幕檔案
            subtitle_extensions = (".srt", ".vtt", ".ass", ".ssa", ".sub")
            files = []
            
            for root, _, filenames in os.walk(folder):
                for filename in filenames:
                    if filename.lower().endswith(subtitle_extensions):
                        files.append(os.path.join(root, filename))
            
            if files:
                self.add_files(files)
                messagebox.showinfo("檔案搜尋", f"在資料夾中找到 {len(files)} 個字幕檔案")
            else:
                messagebox.showinfo("檔案搜尋", "在選中的資料夾中未找到任何字幕檔案")
    
    def add_files(self, files):
        """添加檔案到列表"""
        for file in files:
            # 確保檔案存在
            if not os.path.exists(file):
                continue
                
            # 避免重複添加
            if file not in self.selected_files:
                self.selected_files.append(file)
                # 在列表框中顯示檔案名而非完整路徑
                self.file_listbox.insert(tk.END, os.path.basename(file))
        
        logger.info(f"已添加 {len(files)} 個檔案，目前共有 {len(self.selected_files)} 個檔案")
    
    def clear_selection(self):
        """清除選中的檔案"""
        self.file_listbox.delete(0, tk.END)
        self.selected_files = []
        logger.info("已清除所有選中的檔案")
    
    def handle_drop(self, event):
        """處理檔案拖放事件"""
        if not TKDND_AVAILABLE:
            return
        
        # 解析拖放的檔案路徑
        file_paths = event.data
        
        # Windows 系統下可能需要處理大括號
        if isinstance(file_paths, str):
            # 去除大括號和多餘的引號
            file_paths = file_paths.strip('{}')
            file_paths = file_paths.split('} {')
        
        # 檢查是檔案還是資料夾
        processed_files = []
        
        for path in file_paths:
            path = path.strip()
            if os.path.isfile(path):
                # 檢查是否為字幕檔案
                if path.lower().endswith((".srt", ".vtt", ".ass", ".ssa", ".sub")):
                    processed_files.append(path)
            elif os.path.isdir(path):
                # 資料夾，遞迴搜尋字幕檔案
                for root, _, filenames in os.walk(path):
                    for filename in filenames:
                        if filename.lower().endswith((".srt", ".vtt", ".ass", ".ssa", ".sub")):
                            processed_files.append(os.path.join(root, filename))
        
        if processed_files:
            self.add_files(processed_files)
            messagebox.showinfo("檔案拖放", f"已添加 {len(processed_files)} 個字幕檔案")
        else:
            messagebox.showinfo("檔案拖放", "未找到任何有效的字幕檔案")
    
    def get_selected_files(self) -> List[str]:
        """獲取所有選中的檔案路徑"""
        return self.selected_files.copy()
    
    def toggle_pause(self):
        """切換暫停/繼續狀態"""
        current_text = self.pause_button.cget("text")
        if current_text == "暫停":
            self.pause_button.config(text="繼續")
        else:
            self.pause_button.config(text="暫停")
        
        # 呼叫外部暫停回呼
        self.pause_callback()
    
    def disable_controls(self):
        """禁用控制項（翻譯開始時）"""
        self.start_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.NORMAL)
        self.settings_button.config(state=tk.DISABLED)
        self.llm_combobox.config(state=tk.DISABLED)
        self.model_combo.config(state=tk.DISABLED)
        
        # 禁用選單項
        # 這需要獲取選單引用，此處略過
    
    def reset_ui(self):
        """重置 UI（翻譯完成或停止時）"""
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        self.pause_button.config(text="暫停")  # 重置按鈕文字
        self.stop_button.config(state=tk.DISABLED)
        self.settings_button.config(state=tk.NORMAL)
        self.llm_combobox.config(state="readonly")
        self.model_combo.config(state="readonly")
        self.progress_bar["value"] = 0
        
        # 啟用選單項
        # 這需要獲取選單引用，此處略過
    
    def on_llm_type_changed(self, event=None):
        """LLM 類型變更時的處理函數"""
        # 這個函數會在外部被覆蓋以更新模型列表
        pass
    
    def on_content_type_changed(self, event=None):
        """內容類型變更時的處理函數"""
        if self.prompt_manager:
            self.prompt_manager.set_content_type(self.content_type_var.get())
    
    def on_style_changed(self, event=None):
        """翻譯風格變更時的處理函數"""
        if self.prompt_manager:
            self.prompt_manager.set_translation_style(self.style_var.get())
    
    def set_model_list(self, models: List[str], default_model: str = ""):
        """設置模型列表"""
        if isinstance(models, list) and models:
            self.model_combo["values"] = models
            
            # 設置預設選中的模型
            if default_model and default_model in models:
                self.model_combo_var.set(default_model)
            else:
                self.model_combo_var.set(models[0])
        else:
            self.model_combo["values"] = ["無可用模型"]
            self.model_combo_var.set("無可用模型")
    
    def open_prompt_editor(self):
        """開啟提示詞編輯器"""
        if not self.prompt_manager:
            messagebox.showwarning("功能不可用", "提示詞管理器未初始化")
            return
            
        # 創建提示詞編輯視窗
        prompt_editor = PromptEditorWindow(self.root, self.prompt_manager)
    
    def open_cache_manager(self):
        """開啟緩存管理器"""
        messagebox.showinfo("功能開發中", "緩存管理功能正在開發中")
    
    def open_advanced_settings(self):
        """開啟進階設定視窗"""
        # 此功能可能由外部回呼實現
        messagebox.showinfo("功能開發中", "進階設定功能正在開發中")
    
    def show_help(self):
        """顯示使用說明"""
        help_text = """
使用說明：

1. 選擇檔案：點擊"選擇檔案"按鈕或直接拖放字幕檔案到列表中。
2. 設定翻譯參數：選擇源語言、目標語言、LLM類型和模型。
3. 設定內容類型和翻譯風格：根據字幕內容選擇合適的類型和風格。
4. 點擊"開始翻譯"按鈕開始翻譯過程。
5. 翻譯過程中可以暫停或停止。
6. 可以在"設定"選單中自定義提示詞和管理緩存。

支援的檔案格式：SRT, VTT, ASS, SSA, SUB
        """
        messagebox.showinfo("使用說明", help_text)
    
    def show_about(self):
        """顯示關於資訊"""
        about_text = """
SRT字幕翻譯器 V1.0.0

這是一個使用大型語言模型(LLM)的字幕翻譯工具，支援多種語言和翻譯風格。
可以使用本地模型(Ollama)或OpenAI API進行翻譯。

特點：
- 支援多種字幕格式
- 多種翻譯風格和內容類型
- 翻譯緩存功能，提高效率
- 自定義提示詞模板
- 批量處理功能
- 支援中斷恢復

© 2024 版權所有
        """
        messagebox.showinfo("關於", about_text)


class PromptEditorWindow:
    """提示詞編輯器視窗"""
    def __init__(self, parent, prompt_manager):
        self.prompt_manager = prompt_manager
        
        # 創建視窗
        self.window = tk.Toplevel(parent)
        self.window.title("提示詞編輯器")
        self.window.geometry("800x600")
        self.window.minsize(600, 400)
        
        # 讓視窗成為模態
        self.window.transient(parent)
        self.window.grab_set()
        
        # 設置內容類型和 LLM 類型選擇
        options_frame = ttk.Frame(self.window, padding=10)
        options_frame.pack(fill=tk.X)
        
        # 內容類型選擇
        ttk.Label(options_frame, text="內容類型:").pack(side=tk.LEFT, padx=(0, 5))
        content_types = prompt_manager.get_available_content_types()
        self.content_type_var = tk.StringVar(value=prompt_manager.current_content_type)
        content_type_combo = ttk.Combobox(options_frame, textvariable=self.content_type_var, 
                                          values=content_types, state="readonly", width=12)
        content_type_combo.pack(side=tk.LEFT, padx=(0, 10))
        content_type_combo.bind("<<ComboboxSelected>>", self.load_prompt)
        
        # LLM 類型選擇
        ttk.Label(options_frame, text="LLM類型:").pack(side=tk.LEFT, padx=(10, 5))
        self.llm_type_var = tk.StringVar(value="ollama")
        llm_type_combo = ttk.Combobox(options_frame, textvariable=self.llm_type_var,
                                      values=["ollama", "openai"], state="readonly", width=8)
        llm_type_combo.pack(side=tk.LEFT)
        llm_type_combo.bind("<<ComboboxSelected>>", self.load_prompt)
        
        # 提示詞編輯區域
        editor_frame = ttk.LabelFrame(self.window, text="提示詞編輯", padding=10)
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # 文字編輯區
        self.prompt_text = scrolledtext.ScrolledText(editor_frame, wrap=tk.WORD, font=("Consolas", 10))
        self.prompt_text.pack(fill=tk.BOTH, expand=True)
        
        # 按鈕區域
        button_frame = ttk.Frame(self.window, padding=10)
        button_frame.pack(fill=tk.X)
        
        # 建立按鈕
        ttk.Button(button_frame, text="儲存", command=self.save_prompt, width=10).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="重置為預設", command=self.reset_to_default, width=15).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="匯出", command=self.export_prompt, width=10).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="匯入", command=self.import_prompt, width=10).pack(side=tk.RIGHT, padx=(5, 0))
        ttk.Button(button_frame, text="分析提示詞", command=self.analyze_prompt, width=12).pack(side=tk.LEFT)
        
        # 載入當前提示詞
        self.load_prompt()
        
        # 等待視窗關閉
        parent.wait_window(self.window)
    
    def load_prompt(self, event=None):
        """載入對應內容類型和 LLM 類型的提示詞"""
        content_type = self.content_type_var.get()
        llm_type = self.llm_type_var.get()
        
        # 獲取提示詞
        prompt = self.prompt_manager.get_prompt(llm_type, content_type)
        
        # 顯示在編輯區
        self.prompt_text.delete(1.0, tk.END)
        self.prompt_text.insert(tk.END, prompt)
    
    def save_prompt(self):
        """儲存編輯後的提示詞"""
        content_type = self.content_type_var.get()
        llm_type = self.llm_type_var.get()
        
        # 獲取編輯區的內容
        prompt = self.prompt_text.get(1.0, tk.END).strip()
        
        # 儲存提示詞
        self.prompt_manager.set_prompt(prompt, llm_type, content_type)
        messagebox.showinfo("提示詞儲存", f"已成功儲存 {content_type} 類型的 {llm_type} 提示詞")
    
    def reset_to_default(self):
        """重置為預設提示詞"""
        content_type = self.content_type_var.get()
        llm_type = self.llm_type_var.get()
        
        # 確認對話框
        if messagebox.askyesno("確認重置", f"確定要將 {content_type} 類型的 {llm_type} 提示詞重置為預設值嗎？"):
            self.prompt_manager.reset_to_default(llm_type, content_type)
            self.load_prompt()  # 重新載入
            messagebox.showinfo("重置完成", "已重置為預設提示詞")
    
    def export_prompt(self):
        """匯出提示詞到檔案"""
        content_type = self.content_type_var.get()
        file_path = filedialog.asksaveasfilename(
            title="匯出提示詞",
            defaultextension=".json",
            filetypes=[("JSON檔案", "*.json"), ("所有檔案", "*.*")],
            initialfile=f"prompt_{content_type}_{datetime.now().strftime('%Y%m%d')}.json"
        )
        
        if file_path:
            result = self.prompt_manager.export_prompt(content_type, file_path=file_path)
            if result:
                messagebox.showinfo("匯出成功", f"提示詞已匯出到: {file_path}")
            else:
                messagebox.showerror("匯出失敗", "提示詞匯出過程中發生錯誤")
    
    def import_prompt(self):
        """從檔案匯入提示詞"""
        file_path = filedialog.askopenfilename(
            title="匯入提示詞",
            filetypes=[("JSON檔案", "*.json"), ("所有檔案", "*.*")]
        )
        
        if file_path:
            result = self.prompt_manager.import_prompt(file_path)
            if result:
                messagebox.showinfo("匯入成功", "提示詞已成功匯入")
                self.load_prompt()  # 重新載入
            else:
                messagebox.showerror("匯入失敗", "提示詞匯入過程中發生錯誤")
    
    def analyze_prompt(self):
        """分析當前提示詞的品質"""
        prompt = self.prompt_text.get(1.0, tk.END).strip()
        if not prompt:
            messagebox.showwarning("分析提示詞", "提示詞為空，無法分析")
            return
        
        # 使用提示詞管理器分析
        analysis = self.prompt_manager.analyze_prompt(prompt)
        
        # 顯示分析結果
        result_text = f"""提示詞分析結果:

字數: {analysis['length']} 字符
單詞數: {analysis['word_count']} 單詞

品質評分 ({analysis['quality_score']}/100):
- 清晰度: {analysis['clarity']}/5
- 特異性: {analysis['specificity']}/5
- 完整性: {analysis['completeness']}/5
- 格式評分: {analysis['formatting_score']}/5

特性:
- 包含規則: {'是' if analysis['contains_rules'] else '否'}
- 包含範例: {'是' if analysis['contains_examples'] else '否'}
- 包含約束條件: {'是' if analysis['contains_constraints'] else '否'}
"""
        messagebox.showinfo("提示詞分析", result_text)


# 測試代碼
if __name__ == "__main__":
    # 測試介面
    from prompt import PromptManager
    
    # 簡易模擬回呼函數
    def start_callback():
        print("開始翻譯")
        gui.disable_controls()
    
    def pause_callback():
        print("暫停/繼續翻譯")
    
    def stop_callback():
        print("停止翻譯")
        gui.reset_ui()
    
    def progress_callback(current, total, extra_data=None):
        print(f"進度更新: {current}/{total}")
        progress = int(current / total * 100) if total > 0 else 0
        gui.progress_bar["value"] = progress
        gui.status_label.config(text=f"正在翻譯第 {current}/{total} 句字幕 ({progress}%)")
    
    def complete_callback(message, elapsed_time):
        print(f"翻譯完成: {message}, 耗時: {elapsed_time}")
        gui.reset_ui()
        gui.status_label.config(text=message)
    
    # 初始化根視窗
    root = tk.Tk() if not TKDND_AVAILABLE else TkinterDnD.Tk()
    root.title("SRT 字幕翻譯器")
    root.geometry("600x550")
    
    # 初始化提示詞管理器(可選)
    try:
        prompt_manager = PromptManager()
    except Exception as e:
        print(f"初始化提示詞管理器失敗: {e}")
        prompt_manager = None
    
    # 初始化 GUI 組件
    gui = GUIComponents(
        root, 
        start_callback, 
        pause_callback, 
        stop_callback, 
        progress_callback, 
        complete_callback,
        prompt_manager
    )
    
    # 設置介面
    gui.setup()
    
    # 測試設置模型列表
    gui.set_model_list(["llama3", "mistral", "mixtral"], "llama3")
    
    # 運行主循環
    root.mainloop()