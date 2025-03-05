import os
import json
import tkinter as tk
from tkinter import messagebox
from typing import Dict, Any, Optional, Callable
import threading
from datetime import datetime

try:
    from tkinterdnd2 import TkinterDnD
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False

# 從本地模組導入
from gui_components import GUIComponents
from translation_manager import TranslationManager, TranslationThread
from model_manager import ModelManager
from prompt import PromptManager
from file_handler import FileHandler
from cache import CacheManager

# 初始化各模組
file_handler = FileHandler()
model_manager = ModelManager()
prompt_manager = PromptManager()
cache_manager = CacheManager("data/translation_cache.db")

# 設定加載函數
def load_settings(file_path: str) -> Dict[str, Any]:
    """從JSON檔案載入設定
    
    參數:
        file_path: 設定檔案的路徑
        
    回傳:
        含有設定值的字典
    """
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"載入設定檔案失敗: {e}")
    return {}

# 設定保存函數
def save_settings(file_path: str, settings: Dict[str, Any]) -> bool:
    """保存設定到JSON檔案
    
    參數:
        file_path: 設定檔案的路徑
        settings: 要保存的設定字典
        
    回傳:
        保存是否成功
    """
    try:
        # 確保目錄存在
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"保存設定檔案失敗: {e}")
        return False

# 設定視窗類別
class SettingsWindow:
    def __init__(self, parent, settings):
        self.result = None
        self.dialog = tk.Toplevel(parent)
        self.dialog.title("設定")
        self.dialog.geometry("400x350")
        self.dialog.resizable(False, False)
        self.dialog.transient(parent)  # 設置為父視窗的子視窗
        self.dialog.grab_set()  # 模態視窗
        
        # 將當前設定複製一份避免直接修改
        self.settings = settings.copy()
        
        # 創建UI元素
        self.create_ui()
        
        # 等待視窗關閉
        parent.wait_window(self.dialog)
        
    def create_ui(self):
        # 主框架
        frame = tk.Frame(self.dialog, padx=20, pady=20)
        frame.pack(fill="both", expand=True)
        
        # 主題選項
        theme_frame = tk.LabelFrame(frame, text="主題設定", padx=10, pady=10)
        theme_frame.pack(fill="x", pady=(0, 10))
        
        self.theme_var = tk.StringVar(value=self.settings.get("theme", "default"))
        tk.Radiobutton(theme_frame, text="預設主題", variable=self.theme_var, value="default").pack(anchor="w")
        tk.Radiobutton(theme_frame, text="暗黑主題", variable=self.theme_var, value="dark").pack(anchor="w")
        
        # 功能選項
        options_frame = tk.LabelFrame(frame, text="功能選項", padx=10, pady=10)
        options_frame.pack(fill="x", pady=(0, 10))
        
        self.play_sound_var = tk.BooleanVar(value=self.settings.get("play_sound", True))
        tk.Checkbutton(options_frame, text="完成時播放提示音", variable=self.play_sound_var).pack(anchor="w")
        
        self.auto_save_var = tk.BooleanVar(value=self.settings.get("auto_save", True))
        tk.Checkbutton(options_frame, text="自動儲存設定", variable=self.auto_save_var).pack(anchor="w")
        
        # 進階選項...
        
        # 按鈕區域
        button_frame = tk.Frame(frame)
        button_frame.pack(fill="x", pady=(20, 0))
        
        tk.Button(button_frame, text="儲存", command=self.save_settings, width=10).pack(side="right", padx=5)
        tk.Button(button_frame, text="取消", command=self.dialog.destroy, width=10).pack(side="right", padx=5)
        
    def save_settings(self):
        # 更新設定
        self.settings["theme"] = self.theme_var.get()
        self.settings["play_sound"] = self.play_sound_var.get()
        self.settings["auto_save"] = self.auto_save_var.get()
        
        # 回傳設定
        self.result = self.settings
        self.dialog.destroy()

class App:
    def __init__(self):
        self.root = TkinterDnD.Tk() if TKDND_AVAILABLE else tk.Tk()
        self.root.title("SRT 字幕翻譯器")
        self.root.geometry("600x550")  # 稍微增加高度以容納更多UI元素
        
        # 應用程式狀態
        self.translation_threads: Dict[str, TranslationThread] = {}
        self.total_files = 0
        self.completed_files = 0
        self.settings: Dict[str, Any] = {}
        
        # 初始化管理器
        self.prompt_manager = PromptManager()
        self.model_manager = ModelManager()
        
        # 載入API金鑰
        self.openai_api_key = file_handler.load_api_key()
        if not self.openai_api_key:
            messagebox.showwarning("警告", "未找到 openapi_api_key.txt 或檔案為空，OpenAI 模式可能不可用")
        
        # 載入使用者設定
        self.load_user_settings()
        
        # 初始化介面
        self.gui = GUIComponents(
            self.root, 
            self.start_translation, 
            self.toggle_pause, 
            self.stop_translation, 
            self._update_progress, 
            self._translation_completed, 
            self.prompt_manager
        )
        self.gui.setup()
        
        # 根據設定設置介面初始值
        self.apply_settings_to_gui()
        
        # 更新模型列表
        self.update_model_list()
        
        # 綁定事件
        self.gui.llm_combobox.bind("<<ComboboxSelected>>", self.update_model_list)
        self.gui.settings_button.config(command=self.open_settings)
        
        # 設定關閉視窗協議
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)
        
        # 設定主題
        self.apply_theme()

    def apply_theme(self) -> None:
        """套用主題設定"""
        theme = self.settings.get("theme", "default")
        if theme == "dark":
            self.root.tk_setPalette(
                background='#2E2E2E',
                foreground='#FFFFFF',
                activeBackground='#4A4A4A',
                activeForeground='#FFFFFF')
        else:
            # 恢復預設主題，只重置背景或不做操作
            self.root.tk_setPalette(background=self.root.cget('background'))
            # 或者乾脆不設置，讓系統恢復預設

    def load_user_settings(self) -> None:
        """載入使用者設定"""
        default_settings = {
            "source_lang": "日文",
            "target_lang": "繁體中文",
            "llm_type": "ollama",
            "model_name": "",
            "parallel_requests": "3",
            "display_mode": "雙語對照",  # 預設使用雙語對照模式
            "theme": "default",
            "play_sound": True,
            "auto_save": True
        }
        
        try:
            self.settings = load_settings("config/user_settings.json")
            # 合併預設設定，確保所有設定都存在
            for key, value in default_settings.items():
                if key not in self.settings:
                    self.settings[key] = value
        except Exception as e:
            print(f"載入設定時發生錯誤: {e}")
            self.settings = default_settings

    def save_user_settings(self) -> None:
        """儲存當前使用者設定"""
        # 從GUI獲取當前值
        self.settings["source_lang"] = self.gui.source_lang.get()
        self.settings["target_lang"] = self.gui.target_lang.get()
        self.settings["llm_type"] = self.gui.llm_type.get()
        self.settings["model_name"] = self.gui.model_combo.get()
        self.settings["parallel_requests"] = self.gui.parallel_requests.get()
        self.settings["display_mode"] = self.gui.display_mode.get()
        
        try:
            save_settings("config/user_settings.json", self.settings)
        except Exception as e:
            print(f"儲存設定時發生錯誤: {e}")

    def apply_settings_to_gui(self) -> None:
        """將設定套用到GUI介面"""
        if not hasattr(self, 'gui') or not self.settings:
            return
            
        self.gui.source_lang.set(self.settings.get("source_lang", "日文"))
        self.gui.target_lang.set(self.settings.get("target_lang", "繁體中文"))
        self.gui.llm_type.set(self.settings.get("llm_type", "ollama"))
        self.gui.parallel_requests.set(self.settings.get("parallel_requests", "3"))
        self.gui.display_mode.set(self.settings.get("display_mode", "雙語對照"))
        
        # 模型名稱會在update_model_list中設定

    def open_settings(self) -> None:
        """開啟設定視窗"""
        settings_window = SettingsWindow(self.root, self.settings)
        if settings_window.result:
            self.settings = settings_window.result
            self.apply_theme()
            # 儲存設定到檔案
            save_settings("config/user_settings.json", self.settings)

    def update_model_list(self, event=None) -> None:
        """根據選擇的 LLM 類型更新模型列表"""
        llm_type = self.gui.llm_type.get()
        try:
            models = self.model_manager.get_model_list(llm_type, self.openai_api_key)
            default_model = self.settings.get("model_name") or self.model_manager.get_default_model(llm_type)
            self.gui.set_model_list(models, default_model)
        except Exception as e:
            messagebox.showerror("錯誤", f"獲取模型列表失敗: {str(e)}")
            self.gui.set_model_list([], "")

    def start_translation(self) -> None:
        """開始翻譯處理"""
        files = self.gui.get_selected_files()
        if not files:
            messagebox.showwarning("警告", "請先選擇要翻譯的檔案")
            return

        # 檢查網路連線
        if not self._check_connection():
            messagebox.showerror("錯誤", "網路連線異常，請檢查網路後重試")
            return

        # 記錄顯示模式選擇，並記錄日誌
        display_mode = self.gui.display_mode.get()
        print(f"選擇的顯示模式: {display_mode}")  # 控制台列印以便偵錯

        self.gui.disable_controls()
        self.total_files = len(files)
        self.completed_files = 0
        self.gui.status_label.config(text=f"正在翻譯 {self.total_files} 個檔案...")
        self.gui.total_files_label.config(text=f"總進度: 0/{self.total_files} 檔案完成")
        
        llm_type = self.gui.llm_type.get()
        model_name = self.gui.model_combo.get()
        
        # 記錄開始時間
        self.batch_start_time = datetime.now()
        
        for file_path in files:
            thread = TranslationThread(
                file_path, 
                self.gui.source_lang.get(), 
                self.gui.target_lang.get(),
                model_name, 
                int(self.gui.parallel_requests.get()),
                self._update_progress, 
                self._translation_completed, 
                display_mode,  # 傳遞顯示模式
                llm_type,
                self.openai_api_key if llm_type == 'openai' else None,
                file_handler,
                self.prompt_manager,
                cache_manager
            )
            self.translation_threads[file_path] = thread
            thread.start()
        
        # 自動儲存當前設定
        if self.settings.get("auto_save", True):
            self.save_user_settings()

    def _check_connection(self) -> bool:
        """檢查網路連線狀態
        
        回傳:
            網路是否連線正常
        """
        # 簡易網路連線檢查，可以擴展為更複雜的檢查
        import socket
        try:
            # 嘗試連線到Google的DNS伺服器
            socket.create_connection(("8.8.8.8", 53), timeout=3)
            return True
        except OSError:
            return False

    def stop_translation(self) -> None:
        """停止所有翻譯作業"""
        for thread in self.translation_threads.values():
            thread.stop()
        self.translation_threads.clear()
        self.gui.reset_ui()

    def toggle_pause(self) -> None:
        """切換暫停/繼續狀態"""
        is_paused = self.gui.pause_button.cget("text") == "繼續"
        for thread in self.translation_threads.values():
            if is_paused:
                thread.resume()
                self.gui.pause_button.config(text="暫停")
            else:
                thread.pause()
                self.gui.pause_button.config(text="繼續")

    def _update_progress(self, current: int, total: int, extra_data: Optional[Dict[str, Any]] = None) -> None:
        """更新翻譯進度
        
        參數:
            current: 當前處理的項目數
            total: 總項目數
            extra_data: 額外的資料，如檔案衝突資訊
        """
        if extra_data and extra_data.get("type") == "file_conflict":
            response = messagebox.askyesnocancel(
                "檔案已存在",
                f"檔案 {extra_data['path']} 已存在。\n是否覆蓋？\n'是' = 覆蓋\n'否' = 重新命名\n'取消' = 跳過",
                icon="warning"
            )
            result = "overwrite" if response is True else "rename" if response is False else "skip"
            extra_data["queue"].put(result)
            return
            
        if current >= 0 and total >= 0:
            percentage = int(current / total * 100) if total > 0 else 0
            self.gui.progress_bar['value'] = percentage
            self.gui.status_label.config(text=f"正在翻譯第 {current}/{total} 句字幕 ({percentage}%)")
            self.root.update_idletasks()

    def _translation_completed(self, message: str, elapsed_time: str) -> None:
        """處理翻譯完成回呼，顯示耗時
        
        參數:
            message: 完成訊息
            elapsed_time: 耗費時間
        """
        self.completed_files += 1
        
        # 更新總進度
        self.gui.total_files_label.config(text=f"總進度: {self.completed_files}/{self.total_files} 檔案完成")
        
        # 所有檔案翻譯完成
        if self.completed_files >= self.total_files:
            # 計算總耗時
            total_elapsed = datetime.now() - self.batch_start_time
            total_mins = total_elapsed.total_seconds() // 60
            total_secs = total_elapsed.total_seconds() % 60
            total_time_str = f"{int(total_mins)}分{int(total_secs)}秒"
            
            complete_message = f"翻譯完成！共處理 {self.total_files} 個檔案 | 總耗時: {total_time_str}"
            self.gui.status_label.config(text=complete_message)
            
            # 播放提示音
            if self.settings.get("play_sound", True):
                self._play_notification_sound()
        else:
            # 單個檔案完成
            self.gui.status_label.config(text=f"{message} | 翻譯耗時: {elapsed_time}")
        
        # 如果沒有正在處理的翻譯，重置UI
        if not any(thread.is_alive() for thread in self.translation_threads.values()):
            self.gui.reset_ui()

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
        if self.translation_threads and any(thread.is_alive() for thread in self.translation_threads.values()):
            if messagebox.askokcancel("確認", "正在進行翻譯，確定要關閉程式嗎？"):
                self.stop_translation()
                self.save_user_settings()
                self.root.quit()
        else:
            self.save_user_settings()
            self.root.quit()

    def run(self) -> None:
        """運行應用程式"""
        self.root.mainloop()

# 主程式進入點
if __name__ == "__main__":
    # 確保必要的目錄存在
    os.makedirs("data", exist_ok=True)
    os.makedirs("data/checkpoints", exist_ok=True)
    os.makedirs("config", exist_ok=True)
    os.makedirs("logs", exist_ok=True)
    
    app = App()
    app.run()