import logging
import os
import threading
import tkinter as tk
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import List

# 從新模組導入
from srt_translator.core.config import ConfigManager, get_config, set_config
from srt_translator.services.factory import ServiceFactory
from srt_translator.utils import format_exception

# 嘗試匯入拖放功能模組
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False

# 設定日誌紀錄
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
    """GUI 元件類別，用於建立和管理翻譯器介面"""

    def __init__(self, root, start_callback, pause_callback, stop_callback,
                 progress_callback, complete_callback, prompt_manager=None):
        """
        初始化 GUI 元件
        
        參數：
            root: Tkinter 根視窗
            start_callback: 開始翻譯的回呼函式
            pause_callback: 暫停/繼續翻譯的回呼函式
            stop_callback: 停止翻譯的回呼函式
            progress_callback: 更新進度的回呼函式
            complete_callback: 完成翻譯的回呼函式
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

        # 建立控制項變數
        self.source_lang = tk.StringVar(value="日文")
        self.target_lang = tk.StringVar(value="繁體中文")
        self.llm_type = tk.StringVar(value="ollama")
        self.model_combo_var = tk.StringVar()
        self.parallel_requests = tk.StringVar(value="3")
        self.display_mode = tk.StringVar(value="雙語對照")

        # Netflix 風格選項
        self.netflix_style_enabled = tk.BooleanVar(value=False)

        # 獲取服務實例
        self.file_service = ServiceFactory.get_file_service()
        self.model_service = ServiceFactory.get_model_service()
        self.config_manager = ConfigManager.get_instance("user")

        # 載入主題設定
        self.load_theme_settings()

        # 初始化介面元素
        self.create_menu()

        logger.info("GUI 元件初始化完成")

    def load_theme_settings(self):
        """載入主題設定"""
        try:
            # 從配置管理器獲取主題設定
            theme_config = ConfigManager.get_instance("theme")
            self.colors = theme_config.get_value("colors", {
                "primary": "#3498db",
                "secondary": "#2ecc71",
                "background": "#f0f0f0",
                "text": "#333333",
                "accent": "#e74c3c",
                "button": "#3498db",
                "button_hover": "#2980b9"
            })
        except Exception as e:
            logger.error(f"載入主題設定失敗: {format_exception(e)}")
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
        """建立選單列"""
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
        settings_menu.add_command(label="快取管理", command=self.open_cache_manager)
        settings_menu.add_command(label="進階設定", command=self.open_advanced_settings)
        menu_bar.add_cascade(label="設定", menu=settings_menu)

        # 工具選單
        tools_menu = tk.Menu(menu_bar, tearoff=0)
        tools_menu.add_command(label="字幕格式轉換", command=self.open_subtitle_converter)
        tools_menu.add_command(label="從影片提取字幕", command=self.open_subtitle_extractor)
        tools_menu.add_separator()
        tools_menu.add_command(label="統計報告", command=self.open_stats_viewer)
        menu_bar.add_cascade(label="工具", menu=tools_menu)

        # 關於選單
        help_menu = tk.Menu(menu_bar, tearoff=0)
        help_menu.add_command(label="使用說明", command=self.show_help)
        help_menu.add_command(label="關於", command=self.show_about)
        menu_bar.add_cascade(label="說明", menu=help_menu)

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

            # 新增拖放提示
            drop_label = ttk.Label(file_frame, text="支援拖放檔案", foreground="gray")
            drop_label.pack(pady=(5, 0))

        # 語言設定和模型選擇
        settings_frame = ttk.LabelFrame(top_frame, text="翻譯設定", padding=10)
        settings_frame.pack(fill=tk.BOTH, side=tk.RIGHT, expand=True, padx=(10, 0))

        # 建立表格佈局
        settings_grid = ttk.Frame(settings_frame)
        settings_grid.pack(fill=tk.BOTH, expand=True)

        # 語言設定
        ttk.Label(settings_grid, text="來源語言:").grid(row=0, column=0, sticky=tk.W, pady=5)
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

        ttk.Label(settings_grid, text="模型:").grid(row=3, column=0, sticky=tk.W, pady=5)
        self.model_combo = ttk.Combobox(settings_grid, textvariable=self.model_combo_var, width=15, state="readonly")
        self.model_combo.grid(row=3, column=1, sticky=tk.W, pady=5)

        # 顯示模式和並行請求
        ttk.Label(settings_grid, text="顯示模式:").grid(row=0, column=2, sticky=tk.W, pady=5, padx=(10, 0))
        # 修改：確保顯示模式的值與 translation_manager.py 中使用的值一致
        display_modes = ["雙語對照", "僅顯示翻譯", "翻譯在上", "原文在上"]
        self.display_mode_combo = ttk.Combobox(settings_grid, textvariable=self.display_mode, values=display_modes, width=10, state="readonly")
        self.display_mode_combo.grid(row=0, column=3, sticky=tk.W, pady=5)
        self.display_mode_combo.bind("<<ComboboxSelected>>", self.on_display_mode_changed)

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
            content_types = ["general", "adult", "anime", "movie"]
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
            styles = ["standard", "literal", "localized", "specialized"]
            self.style_var = tk.StringVar(value="standard")
            self.style_combo = ttk.Combobox(settings_grid, textvariable=self.style_var,
                                           values=styles, width=10, state="readonly")
            self.style_combo.grid(row=3, column=3, sticky=tk.W, pady=5)

        # Netflix 風格選項
        ttk.Label(settings_grid, text="Netflix 風格:").grid(row=4, column=2, sticky=tk.W, pady=5, padx=(10, 0))
        self.netflix_checkbox = ttk.Checkbutton(
            settings_grid,
            text="啟用",
            variable=self.netflix_style_enabled,
            command=self.on_netflix_style_changed
        )
        self.netflix_checkbox.grid(row=4, column=3, sticky=tk.W, pady=5)

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

    # 新增：顯示模式變更的回呼函式
    def on_display_mode_changed(self, event=None):
        """顯示模式變更時的處理函式"""
        selected_mode = self.display_mode.get()
        logger.info(f"顯示模式已變更為: {selected_mode}")

        # 保存設置到配置
        set_config("user", "display_mode", selected_mode)

    def browse_files(self):
        """瀏覽並選擇字幕檔案"""
        try:
            files = self.file_service.select_files()
            if files:
                self.add_files(files)
        except Exception as e:
            logger.error(f"選擇檔案時發生錯誤: {format_exception(e)}")
            messagebox.showerror("錯誤", f"選擇檔案時發生錯誤: {e!s}")

    def browse_folder(self):
        """瀏覽並選擇含有字幕檔案的資料夾"""
        try:
            folder = self.file_service.select_directory()
            if folder:
                # 搜尋資料夾中的字幕檔案
                files = self.file_service.scan_directory(folder)

                if files:
                    self.add_files(files)
                    messagebox.showinfo("檔案搜尋", f"在資料夾中找到 {len(files)} 個字幕檔案")
                else:
                    messagebox.showinfo("檔案搜尋", "在選中的資料夾中未找到任何字幕檔案")
        except Exception as e:
            logger.error(f"瀏覽資料夾時發生錯誤: {format_exception(e)}")
            messagebox.showerror("錯誤", f"瀏覽資料夾時發生錯誤: {e!s}")

    def add_files(self, files):
        """新增檔案到列表"""
        for file in files:
            # 確保檔案存在
            if not os.path.exists(file):
                continue

            # 避免重複新增
            if file not in self.selected_files:
                self.selected_files.append(file)
                # 在列表框中顯示檔案名而非完整路徑
                self.file_listbox.insert(tk.END, os.path.basename(file))

        logger.info(f"已新增 {len(files)} 個檔案，目前共有 {len(self.selected_files)} 個檔案")

        # 更新最後使用的目錄
        if files:
            first_file = files[0]
            last_directory = os.path.dirname(first_file)
            set_config("user", "last_directory", last_directory)

    def clear_selection(self):
        """清除選中的檔案"""
        self.file_listbox.delete(0, tk.END)
        self.selected_files = []
        logger.info("已清除所有選中的檔案")

    def handle_drop(self, event):
        """處理檔案拖放事件"""
        if not TKDND_AVAILABLE:
            return

        try:
            files = self.file_service.handle_drop(event)
            if files:
                self.add_files(files)
                messagebox.showinfo("檔案拖放", f"已新增 {len(files)} 個字幕檔案")
        except Exception as e:
            logger.error(f"處理拖放檔案時發生錯誤: {format_exception(e)}")
            messagebox.showerror("錯誤", f"處理拖放檔案時發生錯誤: {e!s}")

    def get_selected_files(self) -> List[str]:
        """取得所有選中的檔案路徑"""
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
        self.display_mode_combo.config(state=tk.DISABLED)  # 禁用顯示模式選擇

        # 禁用選單項
        # 在實際實作中，這裡可能需要保存選單項的引用並禁用它們

    def reset_ui(self):
        """重置 UI（翻譯完成或停止時）"""
        self.start_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        self.pause_button.config(text="暫停")  # 重置按鈕文字
        self.stop_button.config(state=tk.DISABLED)
        self.settings_button.config(state=tk.NORMAL)
        self.llm_combobox.config(state="readonly")
        self.model_combo.config(state="readonly")
        self.display_mode_combo.config(state="readonly")  # 啟用顯示模式選擇
        self.progress_bar["value"] = 0

        # 啟用選單項
        # 在實際實作中，這裡可能需要保存選單項的引用並啟用它們

    def on_llm_type_changed(self, event=None):
        """LLM 類型變更時的處理函式"""
        # 這個函式會在外部被覆蓋以更新模型列表
        pass

    def on_content_type_changed(self, event=None):
        """內容類型變更時的處理函式"""
        if self.prompt_manager:
            content_type = self.content_type_var.get()
            self.prompt_manager.set_content_type(content_type)
            logger.info(f"內容類型已變更為: {content_type}")

            # 保存設置到配置
            set_config("prompt", "current_content_type", content_type)

    def on_style_changed(self, event=None):
        """翻譯風格變更時的處理函式"""
        if self.prompt_manager:
            style = self.style_var.get()
            self.prompt_manager.set_translation_style(style)
            logger.info(f"翻譯風格已變更為: {style}")

            # 保存設置到配置
            set_config("prompt", "current_style", style)

    def on_netflix_style_changed(self):
        """Netflix 風格選項變更時的處理函式"""
        enabled = self.netflix_style_enabled.get()
        logger.info(f"Netflix 風格已{'啟用' if enabled else '停用'}")

        # 保存設置到配置
        set_config("user", "netflix_style_enabled", enabled)

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

        # 建立提示詞編輯視窗
        PromptEditorWindow(self.root, self.prompt_manager)

    def open_cache_manager(self):
        """開啟快取管理器"""
        try:
            # 使用快取服務
            cache_service = ServiceFactory.get_cache_service()
            cache_stats = cache_service.get_cache_stats()

            # 顯示快取統計資訊
            stats_text = "\n".join([f"{k}: {v}" for k, v in cache_stats.items() if k != "top_used"])
            messagebox.showinfo("快取統計", f"快取統計資訊:\n\n{stats_text}")

            # TODO: 將來實現完整的快取管理界面
        except Exception as e:
            logger.error(f"開啟快取管理器時發生錯誤: {format_exception(e)}")
            messagebox.showerror("錯誤", f"開啟快取管理器時發生錯誤: {e!s}")

    def open_advanced_settings(self):
        """開啟進階設定視窗"""
        # 在主程式中實現
        pass

    def open_subtitle_converter(self):
        """開啟字幕格式轉換工具"""
        # 建立一個簡單的轉換對話框
        dialog = tk.Toplevel(self.root)
        dialog.title("字幕格式轉換")
        dialog.geometry("500x300")
        dialog.transient(self.root)
        dialog.grab_set()

        # 建立界面元素
        ttk.Label(dialog, text="選擇要轉換的字幕檔案:").pack(pady=(20, 5))

        # 檔案選擇框
        file_frame = ttk.Frame(dialog)
        file_frame.pack(fill=tk.X, padx=20, pady=5)

        self.convert_file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.convert_file_var, width=50).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(file_frame, text="瀏覽", command=self._select_file_for_conversion).pack(side=tk.LEFT)

        # 格式選擇
        format_frame = ttk.Frame(dialog)
        format_frame.pack(fill=tk.X, padx=20, pady=15)

        ttk.Label(format_frame, text="目標格式:").pack(side=tk.LEFT, padx=(0, 10))
        self.target_format_var = tk.StringVar(value="srt")
        format_combo = ttk.Combobox(format_frame, textvariable=self.target_format_var,
                                   values=["srt", "vtt", "ass"], width=10, state="readonly")
        format_combo.pack(side=tk.LEFT)

        # 轉換按鈕
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=20, pady=20)

        ttk.Button(button_frame, text="轉換", command=lambda: self._convert_subtitle_format(dialog),
                  style="Primary.TButton", width=15).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)

    def _select_file_for_conversion(self):
        """選擇要轉換的字幕檔案"""
        files = self.file_service.select_files()
        if files and len(files) > 0:
            self.convert_file_var.set(files[0])

    def _convert_subtitle_format(self, dialog):
        """執行字幕格式轉換"""
        file_path = self.convert_file_var.get()
        target_format = self.target_format_var.get()

        if not file_path or not os.path.exists(file_path):
            messagebox.showwarning("警告", "請選擇有效的字幕檔案")
            return

        try:
            # 使用檔案服務進行轉換
            result = self.file_service.convert_subtitle_format(file_path, target_format)

            if result:
                messagebox.showinfo("轉換成功", f"檔案已成功轉換並儲存為:\n{result}")
                dialog.destroy()
            else:
                messagebox.showerror("轉換失敗", "無法轉換檔案，請檢查檔案格式和權限")
        except Exception as e:
            logger.error(f"轉換字幕格式時發生錯誤: {format_exception(e)}")
            messagebox.showerror("錯誤", f"轉換字幕格式時發生錯誤: {e!s}")

    def open_subtitle_extractor(self):
        """開啟從影片提取字幕工具"""
        # 建立提取對話框
        dialog = tk.Toplevel(self.root)
        dialog.title("從影片提取字幕")
        dialog.geometry("500x300")
        dialog.transient(self.root)
        dialog.grab_set()

        # 建立界面元素
        ttk.Label(dialog, text="選擇要提取字幕的影片檔案:").pack(pady=(20, 5))

        # 檔案選擇框
        file_frame = ttk.Frame(dialog)
        file_frame.pack(fill=tk.X, padx=20, pady=5)

        self.extract_file_var = tk.StringVar()
        ttk.Entry(file_frame, textvariable=self.extract_file_var, width=50).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Button(file_frame, text="瀏覽", command=self._select_video_for_extraction).pack(side=tk.LEFT)

        # 字幕軌道選擇
        track_frame = ttk.Frame(dialog)
        track_frame.pack(fill=tk.X, padx=20, pady=15)

        ttk.Label(track_frame, text="字幕軌道:").pack(side=tk.LEFT, padx=(0, 10))
        self.subtitle_track_var = tk.StringVar(value="1")
        track_combo = ttk.Combobox(track_frame, textvariable=self.subtitle_track_var,
                                  values=["1", "2", "3", "all"], width=10, state="readonly")
        track_combo.pack(side=tk.LEFT)

        # 提取按鈕
        button_frame = ttk.Frame(dialog)
        button_frame.pack(fill=tk.X, padx=20, pady=20)

        ttk.Button(button_frame, text="提取", command=lambda: self._extract_subtitle_from_video(dialog),
                  style="Primary.TButton", width=15).pack(side=tk.RIGHT, padx=5)
        ttk.Button(button_frame, text="取消", command=dialog.destroy, width=15).pack(side=tk.RIGHT, padx=5)

    def _select_video_for_extraction(self):
        """選擇要提取字幕的影片檔案"""
        filetypes = [
            ("影片檔案", "*.mp4 *.mkv *.avi *.mov *.wmv"),
            ("所有檔案", "*.*")
        ]

        file = filedialog.askopenfilename(
            title="選擇影片檔案",
            filetypes=filetypes
        )

        if file:
            self.extract_file_var.set(file)

    def _extract_subtitle_from_video(self, dialog):
        """從影片提取字幕"""
        video_path = self.extract_file_var.get()

        if not video_path or not os.path.exists(video_path):
            messagebox.showwarning("警告", "請選擇有效的影片檔案")
            return

        try:
            # 使用檔案服務提取字幕
            progress_dialog = tk.Toplevel(dialog)
            progress_dialog.title("提取中")
            progress_dialog.geometry("300x100")
            progress_dialog.transient(dialog)
            progress_dialog.grab_set()

            ttk.Label(progress_dialog, text="正在從影片提取字幕...").pack(pady=(20, 10))
            progress = ttk.Progressbar(progress_dialog, mode="indeterminate")
            progress.pack(fill=tk.X, padx=20)
            progress.start()

            def extract_task():
                try:
                    result = self.file_service.extract_subtitle(video_path)

                    # 在主線程更新 UI
                    self.root.after(0, lambda: self._show_extraction_result(progress_dialog, dialog, result))
                except Exception as e:
                    logger.error(f"提取字幕時發生錯誤: {format_exception(e)}")
                    self.root.after(0, lambda: messagebox.showerror("錯誤", f"提取字幕時發生錯誤: {e!s}"))
                    self.root.after(0, progress_dialog.destroy)

            # 在背景執行提取
            threading.Thread(target=extract_task, daemon=True).start()

        except Exception as e:
            logger.error(f"準備提取字幕時發生錯誤: {format_exception(e)}")
            messagebox.showerror("錯誤", f"準備提取字幕時發生錯誤: {e!s}")

    def _show_extraction_result(self, progress_dialog, parent_dialog, result):
        """顯示字幕提取結果"""
        progress_dialog.destroy()

        if result:
            messagebox.showinfo("提取成功", f"字幕已成功提取並儲存為:\n{result}")
            parent_dialog.destroy()

            # 詢問是否將提取的字幕添加到翻譯列表
            if messagebox.askyesno("添加到翻譯列表", "是否要將提取的字幕添加到翻譯列表？"):
                self.add_files([result])
        else:
            messagebox.showerror("提取失敗", "無法從影片提取字幕，可能沒有內嵌字幕或格式不支援")

    def open_stats_viewer(self):
        """開啟統計報告檢視器"""
        try:
            # 取得翻譯服務的統計資訊
            translation_service = ServiceFactory.get_translation_service()
            stats = translation_service.get_stats()

            # 取得快取服務的統計資訊
            cache_service = ServiceFactory.get_cache_service()
            cache_stats = cache_service.get_cache_stats()

            # 創建統計報告視窗
            dialog = tk.Toplevel(self.root)
            dialog.title("翻譯統計報告")
            dialog.geometry("500x400")
            dialog.transient(self.root)

            # 建立介面
            notebook = ttk.Notebook(dialog)
            notebook.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

            # 翻譯統計頁面
            trans_frame = ttk.Frame(notebook)
            notebook.add(trans_frame, text="翻譯統計")

            # 建立文本區域顯示統計資訊
            trans_text = scrolledtext.ScrolledText(trans_frame, width=60, height=20)
            trans_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

            trans_text.insert(tk.END, "=== 翻譯統計 ===\n\n")
            for key, value in stats.items():
                trans_text.insert(tk.END, f"{key}: {value}\n")
            trans_text.config(state=tk.DISABLED)

            # 快取統計頁面
            cache_frame = ttk.Frame(notebook)
            notebook.add(cache_frame, text="快取統計")

            cache_text = scrolledtext.ScrolledText(cache_frame, width=60, height=20)
            cache_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5)

            cache_text.insert(tk.END, "=== 快取統計 ===\n\n")
            for key, value in cache_stats.items():
                if key != "top_used" and key != "models":
                    cache_text.insert(tk.END, f"{key}: {value}\n")

            if "models" in cache_stats:
                cache_text.insert(tk.END, "\n=== 模型統計 ===\n\n")
                for model, count in cache_stats["models"].items():
                    cache_text.insert(tk.END, f"{model}: {count} 筆記錄\n")

            cache_text.config(state=tk.DISABLED)

            # 底部按鈕
            button_frame = ttk.Frame(dialog)
            button_frame.pack(fill=tk.X, pady=10)

            ttk.Button(button_frame, text="清理快取",
                      command=lambda: self._clean_cache(dialog)).pack(side=tk.LEFT, padx=10)
            ttk.Button(button_frame, text="關閉",
                      command=dialog.destroy).pack(side=tk.RIGHT, padx=10)

        except Exception as e:
            logger.error(f"開啟統計報告時發生錯誤: {format_exception(e)}")
            messagebox.showerror("錯誤", f"開啟統計報告時發生錯誤: {e!s}")

    def _clean_cache(self, dialog):
        """清理快取"""
        try:
            # 詢問確認
            if messagebox.askyesno("確認", "確定要清理快取嗎？此操作會刪除 30 天前的快取記錄。"):
                cache_service = ServiceFactory.get_cache_service()
                deleted = cache_service.clear_old_cache(30)

                messagebox.showinfo("清理完成", f"已刪除 {deleted} 筆快取記錄")

                # 關閉對話框
                dialog.destroy()

                # 重新開啟統計報告
                self.open_stats_viewer()
        except Exception as e:
            logger.error(f"清理快取時發生錯誤: {format_exception(e)}")
            messagebox.showerror("錯誤", f"清理快取時發生錯誤: {e!s}")

    def show_help(self):
        """顯示使用說明"""
        help_text = """
使用說明：

1. 選擇檔案：點擊"選擇檔案"按鈕或直接拖放字幕檔案到列表中。
2. 設定翻譯參數：選擇來源語言、目標語言、LLM類型和模型。
3. 設定內容類型和翻譯風格：根據字幕內容選擇合適的類型和風格。
4. 設定顯示模式：選擇如何顯示原文和翻譯。
   - 雙語對照：原文和翻譯同時顯示（原文在上，翻譯在下）
   - 僅顯示翻譯：只顯示翻譯文本
   - 翻譯在上：翻譯在上，原文在下
   - 原文在上：原文在上，翻譯在下
5. 點擊"開始翻譯"按鈕開始翻譯過程。
6. 翻譯過程中可以暫停或停止。
7. 可以在"設定"選單中自訂提示詞和管理快取。

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
- 翻譯快取功能，提高效率
- 自訂提示詞模板
- 批次處理功能
- 支援中斷恢復

© 2024 版權所有
        """
        messagebox.showinfo("關於", about_text)


class PromptEditorWindow:
    """提示詞編輯器視窗"""
    def __init__(self, parent, prompt_manager):
        """初始化提示詞編輯器視窗
        
        參數:
            parent: 父窗口
            prompt_manager: 提示詞管理器
        """
        self.prompt_manager = prompt_manager

        # 建立視窗
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

        # 取得提示詞
        prompt = self.prompt_manager.get_prompt(llm_type, content_type)

        # 顯示在編輯區
        self.prompt_text.delete(1.0, tk.END)
        self.prompt_text.insert(tk.END, prompt)

    def save_prompt(self):
        """儲存編輯後的提示詞"""
        content_type = self.content_type_var.get()
        llm_type = self.llm_type_var.get()

        # 取得編輯區的內容
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

字數: {analysis['length']} 字元
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


# 測試程式碼
if __name__ == "__main__":
    # 設定控制台日誌以便於測試
    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter('%(levelname)s - %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 測試介面
    try:
        # 初始化服務
        file_service = ServiceFactory.get_file_service()
        model_service = ServiceFactory.get_model_service()

        # 初始化配置管理器
        config_manager = ConfigManager.get_instance("user")

        # 從服務獲取提示詞管理器
        translation_service = ServiceFactory.get_translation_service()
        prompt_manager = translation_service.prompt_manager

        # 簡易模擬回調函式
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

        # 初始化 GUI 元件
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

        # 設置標題顯示版本
        version = get_config("app", "version", "1.0.0")
        root.title(f"SRT 字幕翻譯器 v{version}")

        # 執行主迴圈
        root.mainloop()

    except Exception as e:
        logger.error(f"運行GUI測試時發生錯誤: {format_exception(e)}")
        print(f"錯誤: {e!s}")
