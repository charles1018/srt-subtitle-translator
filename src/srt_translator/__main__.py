import logging
import os
import threading
import tkinter as tk
from typing import Any, Dict, List, Optional

try:
    from tkinterdnd2 import TkinterDnD
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False
    from tkinter import Tk as TkBase
    TkinterDnD = type('TkinterDnD', (object,), {'Tk': TkBase})

# 從新創建的模組導入
from srt_translator.core.config import ConfigManager, get_config, set_config
from srt_translator.services.factory import ServiceFactory, TranslationTaskManager
from srt_translator.utils import AppError, check_internet_connection, format_exception

# 設定日誌
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s',
    handlers=[
        logging.FileHandler('logs/app.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('SRTTranslator')

class App:
    """字幕翻譯應用程式主類"""

    def __init__(self):
        """初始化應用程式"""
        # 建立主視窗
        self.root = TkinterDnD.Tk() if TKDND_AVAILABLE else tk.Tk()
        self.root.title("SRT 字幕翻譯器")
        self.root.geometry("600x550")

        # 初始化服務
        self._init_services()

        # 初始化介面
        self._init_gui()

        # 套用使用者設定
        self._apply_user_settings()

        # 設定關閉視窗協議
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

        # 設定主題
        self._apply_theme()

        logger.info("應用程式初始化完成")

    def _init_services(self) -> None:
        """初始化所需的服務"""
        # 確保必要的目錄存在
        self._ensure_directories()

        # 獲取服務實例
        self.file_service = ServiceFactory.get_file_service()
        self.model_service = ServiceFactory.get_model_service()
        self.translation_service = ServiceFactory.get_translation_service()
        self.cache_service = ServiceFactory.get_cache_service()

        # 初始化翻譯任務管理器
        self.task_manager = TranslationTaskManager()

        # 配置管理器
        self.user_config = ConfigManager.get_instance("user")
        self.app_config = ConfigManager.get_instance("app")

        # 載入 API 金鑰
        self._load_api_keys()

    def _ensure_directories(self) -> None:
        """確保必要的目錄存在"""
        directories = [
            "data",
            "data/checkpoints",
            "config",
            "logs",
            "data/terms_dictionaries"
        ]

        for directory in directories:
            os.makedirs(directory, exist_ok=True)

    def _load_api_keys(self) -> None:
        """載入 API 金鑰"""
        # 載入 OpenAI API 金鑰
        openai_key = self.file_service.load_api_key()
        if not openai_key:
            logger.warning("未找到 OpenAI API 金鑰或檔案為空，OpenAI 模式可能不可用")

    def _init_gui(self) -> None:
        """初始化圖形介面"""
        # 從 GUI 模組導入 GUI 相關類
        from srt_translator.gui.components import GUIComponents

        # 獲取提示詞服務
        prompt_manager = ServiceFactory.get_translation_service().prompt_manager

        # 初始化 GUI 元件
        self.gui = GUIComponents(
            self.root,
            self.start_translation,  # 開始翻譯的回調函數
            self.toggle_pause,       # 暫停/繼續翻譯的回調函數
            self.stop_translation,   # 停止翻譯的回調函數
            self._update_progress,   # 更新進度的回調函數
            self._translation_completed,  # 翻譯完成的回調函數
            prompt_manager
        )

        # 設置介面
        self.gui.setup()

        # 配置模型選單更新響應
        self.gui.llm_combobox.bind("<<ComboboxSelected>>", self.update_model_list)

        # 配置設定按鈕
        self.gui.settings_button.config(command=self.open_settings)

    def _apply_user_settings(self) -> None:
        """套用使用者設定"""
        settings = self.user_config.get_config()

        # 設定 GUI 元件的初始值
        self.gui.source_lang.set(settings.get("source_lang", "日文"))
        self.gui.target_lang.set(settings.get("target_lang", "繁體中文"))
        self.gui.llm_type.set(settings.get("llm_type", "ollama"))
        self.gui.parallel_requests.set(str(settings.get("parallel_requests", "3")))
        self.gui.display_mode.set(settings.get("display_mode", "雙語對照"))

        # Netflix 風格選項
        self.gui.netflix_style_enabled.set(settings.get("netflix_style_enabled", False))

        # 更新模型列表
        self.update_model_list()

    def _apply_theme(self) -> None:
        """套用主題設定"""
        theme = get_config("user", "theme", "default")
        if theme == "dark":
            self.root.tk_setPalette(
                background='#2E2E2E',
                foreground='#FFFFFF',
                activeBackground='#4A4A4A',
                activeForeground='#FFFFFF')
        else:
            # 恢復預設主題
            self.root.tk_setPalette(background=self.root.cget('background'))

    def update_model_list(self, event=None) -> None:
        """根據選擇的 LLM 類型更新模型列表"""
        llm_type = self.gui.llm_type.get()
        try:
            # 非同步獲取模型列表
            def async_update_models():
                try:
                    import asyncio
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    try:
                        models = loop.run_until_complete(
                            self.model_service.get_available_models(llm_type)
                        )

                        # 在主線程更新 UI
                        self.root.after(0, lambda: self._update_model_dropdown(models, llm_type))
                    finally:
                        loop.close()
                except Exception as e:
                    logger.error(f"獲取模型列表失敗: {format_exception(e)}")
                    self.root.after(0, lambda: self._update_model_dropdown([], llm_type))

            # 在背景線程獲取模型
            threading.Thread(target=async_update_models, daemon=True).start()

            # 暫時顯示載入中
            self.gui.set_model_list(["載入中..."], "載入中...")
        except Exception as e:
            logger.error(f"更新模型列表失敗: {format_exception(e)}")
            self.gui.set_model_list(["無法載入模型"], "")

    def _update_model_dropdown(self, models: List[str], llm_type: str) -> None:
        """更新模型下拉選單（在主線程中調用）"""
        if not models:
            self.gui.set_model_list(["無可用模型"], "")
            return

        # 獲取之前保存的模型設定
        default_model = get_config("user", "model_name") or ""

        # 如果之前選擇的模型不在列表中或LLM類型已更改，獲取推薦模型
        if not default_model or default_model not in models:
            default_model = self.model_service.get_recommended_model("translation", llm_type)

        # 更新下拉選單
        self.gui.set_model_list(models, default_model)

    def open_settings(self) -> None:
        """開啟設定視窗"""
        try:
            from settings_window import SettingsWindow

            # 獲取當前設定
            settings = self.user_config.get_config()

            # 開啟設定視窗
            settings_window = SettingsWindow(self.root, settings)

            # 如果有新設定
            if settings_window.result:
                # 更新設定
                for key, value in settings_window.result.items():
                    self.user_config.set_value(key, value, auto_save=False)

                # 儲存設定
                self.user_config.save_config()

                # 重新套用主題
                self._apply_theme()

        except ImportError:
            # 如果設定視窗模組不存在，使用舊有的設定方式
            from tkinter import messagebox
            messagebox.showinfo("功能開發中", "進階設定功能正在開發中")

    def start_translation(self) -> None:
        """開始翻譯處理"""
        files = self.gui.get_selected_files()
        if not files:
            tk.messagebox.showwarning("警告", "請先選擇要翻譯的檔案")
            return

        # 檢查網路連線
        if not check_internet_connection():
            tk.messagebox.showerror("錯誤", "網路連線異常，請檢查網路後重試")
            return

        # 禁用界面控制項
        self.gui.disable_controls()

        # 獲取翻譯參數
        source_lang = self.gui.source_lang.get()
        target_lang = self.gui.target_lang.get()
        model_name = self.gui.model_combo.get()
        parallel_requests = int(self.gui.parallel_requests.get())
        display_mode = self.gui.display_mode.get()
        llm_type = self.gui.llm_type.get()

        # 啟動翻譯任務
        success = self.task_manager.start_translation(
            files,
            source_lang,
            target_lang,
            model_name,
            parallel_requests,
            display_mode,
            llm_type,
            self._update_progress,
            self._translation_completed
        )

        if not success:
            self.gui.reset_ui()
            tk.messagebox.showerror("錯誤", "啟動翻譯任務失敗")
            return

        # 更新界面狀態
        self.gui.status_label.config(text=f"正在翻譯 {len(files)} 個檔案...")
        self.gui.total_files_label.config(text=f"總進度: 0/{len(files)} 檔案完成")

        # 自動儲存當前設定
        if get_config("user", "auto_save", True):
            self._save_user_settings()

    def _save_user_settings(self) -> None:
        """儲存使用者設定"""
        # 從 GUI 獲取當前設定
        settings = {
            "source_lang": self.gui.source_lang.get(),
            "target_lang": self.gui.target_lang.get(),
            "llm_type": self.gui.llm_type.get(),
            "model_name": self.gui.model_combo.get(),
            "parallel_requests": int(self.gui.parallel_requests.get()),
            "display_mode": self.gui.display_mode.get()
        }

        # 更新設定
        for key, value in settings.items():
            set_config("user", key, value, auto_save=False)

        # 儲存設定
        self.user_config.save_config()

    def stop_translation(self) -> None:
        """停止所有翻譯作業"""
        self.task_manager.stop_all()
        self.gui.reset_ui()

    def toggle_pause(self) -> None:
        """切換暫停/繼續狀態"""
        is_paused = self.gui.pause_button.cget("text") == "繼續"
        if is_paused:
            self.task_manager.resume_all()
            self.gui.pause_button.config(text="暫停")
        else:
            self.task_manager.pause_all()
            self.gui.pause_button.config(text="繼續")

    def _update_progress(self, current: int, total: int, extra_data: Optional[Dict[str, Any]] = None) -> None:
        """處理翻譯進度更新"""
        # 處理檔案衝突
        if extra_data and extra_data.get("type") == "file_conflict":
            from tkinter import messagebox
            response = messagebox.askyesnocancel(
                "檔案已存在",
                f"檔案 {extra_data['path']} 已存在。\n是否覆蓋？\n'是' = 覆蓋\n'否' = 重新命名\n'取消' = 跳過",
                icon="warning"
            )
            result = "overwrite" if response is True else "rename" if response is False else "skip"
            extra_data["queue"].put(result)
            return

        # 一般進度更新
        if current >= 0 and total >= 0:
            percentage = int((current / total) * 100) if total > 0 else 0
            self.gui.progress_bar['value'] = percentage
            self.gui.status_label.config(text=f"正在翻譯第 {current}/{total} 句字幕 ({percentage}%)")
            self.root.update_idletasks()

    def _translation_completed(self, message: str, elapsed_time: str) -> None:
        """處理翻譯完成回調"""
        # 更新狀態訊息
        self.gui.status_label.config(text=message)

        # 如果訊息中包含"總進度"，更新總進度標籤
        if "總進度:" in message:
            parts = message.split("總進度:", 1)
            if len(parts) > 1:
                self.gui.total_files_label.config(text=f"總進度:{parts[1].strip()}")

        # 如果所有任務都完成，播放提示音
        if not self.task_manager.is_any_running():
            # 重置 UI
            self.gui.reset_ui()

            # 播放提示音
            if get_config("user", "play_sound", True):
                self._play_notification_sound()

    def _play_notification_sound(self) -> None:
        """播放通知音效"""
        try:
            import winsound
            winsound.MessageBeep(winsound.MB_ICONASTERISK)
        except:
            # 在非Windows系統上，嘗試其他方法播放聲音
            try:
                import subprocess
                os_name = os.name
                if os_name == 'posix':  # macOS or Linux
                    if 'darwin' in os.sys.platform:  # macOS
                        subprocess.call(['afplay', '/System/Library/Sounds/Tink.aiff'])
                    else:  # Linux
                        subprocess.call(['paplay', '/usr/share/sounds/freedesktop/stereo/complete.oga'])
            except:
                # 如果上述方法都不可用，靜默失敗
                pass

    def on_closing(self) -> None:
        """處理視窗關閉事件"""
        if self.task_manager.is_any_running():
            from tkinter import messagebox
            if messagebox.askokcancel("確認", "正在進行翻譯，確定要關閉程式嗎？"):
                self.task_manager.stop_all()
                self._save_user_settings()
                # 清理服務資源
                ServiceFactory.reset_services()
                self.root.quit()
        else:
            self._save_user_settings()
            # 清理服務資源
            ServiceFactory.reset_services()
            self.root.quit()

    def run(self) -> None:
        """運行應用程式"""
        self.root.mainloop()

def main() -> None:
    """主程式入口點"""
    try:
        app = App()
        app.run()
    except AppError as e:
        # 處理應用程式自定義錯誤
        logger.error(f"應用程式錯誤: {format_exception(e)}")
        from tkinter import messagebox
        messagebox.showerror("應用程式錯誤", str(e))
    except Exception as e:
        # 處理未捕獲的錯誤
        logger.error(f"未預期的錯誤: {format_exception(e)}")
        from tkinter import messagebox
        messagebox.showerror("未預期的錯誤", f"發生未預期的錯誤:\n{e!s}")

# 主程式進入點
if __name__ == "__main__":
    main()
