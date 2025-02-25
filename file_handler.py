# file_handler.py
import os
from typing import Optional, List
from queue import Queue
import tkinter as tk
from tkinter import filedialog, messagebox

try:
    from tkinterdnd2 import *
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False

class FileHandler:
    def __init__(self, root: tk.Tk = None):
        self.root = root
        self.lang_suffix = {"繁體中文": ".zh_tw", "英文": ".en", "日文": ".jp"}

    def select_files(self) -> List[str]:
        """通過對話框選擇檔案"""
        files = filedialog.askopenfilenames(filetypes=[("SRT files", "*.srt")])
        return list(files)

    def handle_drop(self, event) -> List[str]:
        """處理檔案拖放"""
        if not TKDND_AVAILABLE or not self.root:
            return []
        
        files = self.root.tk.splitlist(event.data)
        valid_files = []
        for file in files:
            if file.lower().endswith('.srt'):
                file = file.strip('{}')  # 在 Windows 上移除檔案路徑的大括號
                valid_files.append(file)
            else:
                messagebox.showwarning("警告", f"檔案 {file} 不是 SRT 格式，已略過")
        return valid_files

    def get_output_path(self, file_path: str, target_lang: str, progress_callback: callable) -> Optional[str]:
        """獲取輸出文件路徑並處理衝突"""
        dir_name, file_name = os.path.split(file_path)
        name, ext = os.path.splitext(file_name)
        base_path = os.path.join(dir_name, f"{name}{self.lang_suffix.get(target_lang, '.unknown')}{ext}")
        
        if os.path.exists(base_path):
            queue = Queue()
            progress_callback(-1, -1, {"type": "file_conflict", "path": base_path, "queue": queue})
            response = queue.get()
            
            if response == "rename":
                counter = 1
                while True:
                    new_path = os.path.join(dir_name, f"{name}{self.lang_suffix[target_lang]}_{counter}{ext}")
                    if not os.path.exists(new_path):
                        return new_path
                    counter += 1
            elif response == "skip":
                return None
            # "overwrite" 情況直接返回 base_path
        
        return base_path

# 測試代碼
if __name__ == "__main__":
    root = tk.Tk() if not TKDND_AVAILABLE else TkinterDnD.Tk()
    root.title("檔案處理測試")
    handler = FileHandler(root)

    # 測試檔案選擇
    files = handler.select_files()
    print("選擇的檔案:", files)

    # 測試輸出路徑生成
    def dummy_progress_callback(current, total, extra_data=None):
        if extra_data and extra_data["type"] == "file_conflict":
            print(f"模擬檔案衝突: {extra_data['path']}")
            extra_data["queue"].put("rename")  # 模擬選擇重新命名

    test_path = "test.srt"
    output = handler.get_output_path(test_path, "繁體中文", dummy_progress_callback)
    print("輸出路徑:", output)

    root.mainloop()