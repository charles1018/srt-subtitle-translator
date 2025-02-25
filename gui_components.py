# gui_components.py
import tkinter as tk
from tkinter import ttk, messagebox, Menu
from typing import Callable, List
from file_handler import FileHandler

try:
    from tkinterdnd2 import *
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False
    print("警告：未安裝 tkinterdnd2 模組，拖放功能將被停用")

class GUIComponents:
    def __init__(self, root: tk.Tk, start_translation: Callable, toggle_pause: Callable, 
                 stop_translation: Callable, update_progress: Callable, 
                 translation_completed: Callable, prompt_manager):
        self.root = root
        self.start_translation = start_translation
        self.toggle_pause = toggle_pause
        self.stop_translation = stop_translation
        self.update_progress = update_progress
        self.translation_completed = translation_completed
        self.prompt_manager = prompt_manager
        self.file_handler = FileHandler(root)
        self.drag_data = {"index": None, "y": 0}

    def setup(self):
        """設置 GUI 界面"""
        if TKDND_AVAILABLE and isinstance(self.root, TkinterDnD.Tk):
            self.root.drop_target_register(DND_FILES)
            self.root.dnd_bind('<<Drop>>', lambda e: self.add_files(self.file_handler.handle_drop(e)))

        self.create_widgets()

    def create_widgets(self):
        """創建界面元素"""
        file_frame = ttk.Frame(self.root)
        file_frame.pack(pady=10)

        self.file_button = ttk.Button(file_frame, text="選擇 SRT 檔案", 
                                     command=lambda: self.add_files(self.file_handler.select_files()))
        self.file_button.pack(side=tk.LEFT, padx=5)

        self.file_list = tk.Listbox(self.root, width=70, height=10, selectmode=tk.SINGLE)
        self.file_list.pack(pady=10)
        self.file_list.bind('<Button-3>', self.show_context_menu)
        self.file_list.bind('<B1-Motion>', self.drag_item)
        self.file_list.bind('<ButtonRelease-1>', self.drop_item)

        self.context_menu = Menu(self.root, tearoff=0)
        self.context_menu.add_command(label="移除", command=self.remove_selected)

        lang_frame = ttk.Frame(self.root)
        lang_frame.pack(pady=10)

        ttk.Label(lang_frame, text="原文語言:").grid(row=0, column=0)
        self.source_lang = ttk.Combobox(lang_frame, values=["日文", "英文", "自動偵測"])
        self.source_lang.set("日文")
        self.source_lang.grid(row=0, column=1)

        ttk.Label(lang_frame, text="目標語言:").grid(row=0, column=2)
        self.target_lang = ttk.Combobox(lang_frame, values=["繁體中文", "英文", "日文"])
        self.target_lang.set("繁體中文")
        self.target_lang.grid(row=0, column=3)

        model_frame = ttk.Frame(self.root)
        model_frame.pack(pady=10)

        ttk.Label(model_frame, text="選擇模型:").grid(row=0, column=0)
        self.model_combo = ttk.Combobox(model_frame)
        self.model_combo.grid(row=0, column=1)

        ttk.Label(model_frame, text="並行請求數:").grid(row=0, column=2)
        self.parallel_requests = ttk.Combobox(model_frame, values=["1", "2", "3", "4", "5", "6", "7", "8"])
        self.parallel_requests.set("6")
        self.parallel_requests.grid(row=0, column=3)

        # 顯示模式框架
        display_frame = ttk.Frame(self.root)
        display_frame.pack(pady=10)

        ttk.Label(display_frame, text="字幕顯示模式:").grid(row=0, column=0)
        self.display_mode = ttk.Combobox(display_frame, values=[
            "目標語言", "目標語言在上，原文語言在下", "原文語言在上，目標語言在下"
        ], state="readonly")
        self.display_mode.set("目標語言")  # 預設僅目標語言
        self.display_mode.grid(row=0, column=1)

        control_frame = ttk.Frame(self.root)
        control_frame.pack(pady=10)

        self.translate_button = ttk.Button(control_frame, text="開始翻譯", command=self.start_translation)
        self.translate_button.pack(side=tk.LEFT, padx=5)

        self.pause_button = ttk.Button(control_frame, text="暫停", command=self.toggle_pause, state=tk.DISABLED)
        self.pause_button.pack(side=tk.LEFT, padx=5)

        self.stop_button = ttk.Button(control_frame, text="停止", command=self.stop_translation, state=tk.DISABLED)
        self.stop_button.pack(side=tk.LEFT, padx=5)

        self.edit_prompt_button = ttk.Button(control_frame, text="編輯 Prompt", command=self.edit_prompt)
        self.edit_prompt_button.pack(side=tk.LEFT, padx=5)

        self.progress_bar = ttk.Progressbar(self.root, length=400, mode='determinate')
        self.progress_bar.pack(pady=10)

        self.status_label = ttk.Label(self.root, text="", wraplength=550, justify="center")
        self.status_label.pack(pady=10, fill=tk.X, expand=True)

    def add_files(self, files: List[str]):
        """添加檔案到列表"""
        for file in files:
            self.file_list.insert(tk.END, file)

    def edit_prompt(self):
        """彈出 Prompt 編輯窗口"""
        edit_window = tk.Toplevel(self.root)
        edit_window.title("編輯 Prompt")
        edit_window.geometry("400x300")

        ttk.Label(edit_window, text="自定義 Prompt:").pack(pady=5)
        prompt_text = tk.Text(edit_window, height=10, width=50)
        prompt_text.pack(pady=5)
        prompt_text.insert(tk.END, self.prompt_manager.get_prompt())

        def save_prompt():
            new_prompt = prompt_text.get("1.0", tk.END).strip()
            self.prompt_manager.set_prompt(new_prompt)
            messagebox.showinfo("成功", "Prompt 已保存")
            edit_window.destroy()

        def reset_prompt():
            self.prompt_manager.reset_to_default()
            prompt_text.delete("1.0", tk.END)
            prompt_text.insert(tk.END, self.prompt_manager.get_prompt())
            messagebox.showinfo("成功", "已重置為預設 Prompt")

        ttk.Button(edit_window, text="保存", command=save_prompt).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(edit_window, text="重置為預設", command=reset_prompt).pack(side=tk.LEFT, padx=5, pady=5)
        ttk.Button(edit_window, text="取消", command=edit_window.destroy).pack(side=tk.LEFT, padx=5, pady=5)

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

    def disable_controls(self):
        """禁用控制按鈕"""
        self.translate_button.config(state=tk.DISABLED)
        self.pause_button.config(state=tk.NORMAL)
        self.stop_button.config(state=tk.DISABLED)
        self.progress_bar['value'] = 0
        self.status_label.config(text="")

    def reset_ui(self):
        """重置 UI 狀態"""
        self.translate_button.config(state=tk.NORMAL)
        self.pause_button.config(state=tk.DISABLED)
        self.stop_button.config(state=tk.DISABLED)
        self.pause_button.config(text="暫停")
        self.progress_bar['value'] = 0

    def get_selected_files(self) -> List[str]:
        """獲取選中的檔案列表"""
        return [self.file_list.get(i) for i in range(self.file_list.size())]

    def set_model_list(self, models: List[str], default_model: str):
        """設置模型列表和預設值"""
        self.model_combo.config(values=models)
        self.model_combo.set(default_model)