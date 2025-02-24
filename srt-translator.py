# srt-translator.py
import tkinter as tk
from tkinter import messagebox
try:
    from tkinterdnd2 import TkinterDnD
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False

from gui_components import GUIComponents
from translation_manager import TranslationThread
from model_manager import ModelManager
from prompt import PromptManager

class App:
    def __init__(self):
        self.root = TkinterDnD.Tk() if TKDND_AVAILABLE else tk.Tk()
        self.root.title("SRT 字幕翻譯器")
        self.root.geometry("600x500")
        self.translation_threads = {}
        self.prompt_manager = PromptManager()
        self.model_manager = ModelManager()
        
        self.gui = GUIComponents(self.root, self.start_translation, self.toggle_pause, 
                                 self.stop_translation, self._update_progress, 
                                 self._translation_completed, self.prompt_manager)
        self.gui.setup()
        self.gui.set_model_list(self.model_manager.get_model_list(), self.model_manager.get_default_model())
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_closing)

    def start_translation(self):
        """開始翻譯"""
        files = self.gui.get_selected_files()
        if not files:
            messagebox.showwarning("警告", "請先選擇要翻譯的檔案")
            return

        self.gui.disable_controls()
        self.gui.status_label.config(text=f"正在翻譯 {len(files)} 個檔案...")
        
        for file_path in files:
            thread = TranslationThread(
                file_path, self.gui.source_lang.get(), self.gui.target_lang.get(),
                self.gui.model_combo.get(), int(self.gui.parallel_requests.get()),
                self._update_progress, self._translation_completed
            )
            self.translation_threads[file_path] = thread
            thread.start()

    def stop_translation(self):
        """停止翻譯"""
        for thread in self.translation_threads.values():
            thread.stop()
        self.translation_threads.clear()
        self.gui.reset_ui()

    def toggle_pause(self):
        """切換暫停/繼續狀態"""
        is_paused = self.gui.pause_button.cget("text") == "繼續"
        for thread in self.translation_threads.values():
            if is_paused:
                thread.resume()
                self.gui.pause_button.config(text="暫停")
            else:
                thread.pause()
                self.gui.pause_button.config(text="繼續")

    def _update_progress(self, current, total, extra_data=None):
        """更新進度"""
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
            percentage = int(current / total * 100)
            self.gui.progress_bar['value'] = percentage
            self.gui.status_label.config(text=f"正在翻譯第 {current}/{total} 句字幕 ({percentage}%)")
            self.root.update_idletasks()

    def _translation_completed(self, message):
        """處理翻譯完成回調"""
        current_text = self.gui.status_label.cget("text")
        self.gui.status_label.config(text=f"{current_text}\n{message}")

    def on_closing(self):
        """處理窗口關閉事件"""
        if self.translation_threads:
            if messagebox.askokcancel("確認", "正在進行翻譯，確定要關閉程式嗎？"):
                self.stop_translation()
                self.root.quit()
        else:
            self.root.quit()

    def run(self):
        """運行應用程式"""
        self.root.mainloop()

if __name__ == "__main__":
    app = App()
    app.run()