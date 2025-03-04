import os
import re
import json
import shutil
import tempfile
import logging
import logging.handlers
from datetime import datetime
from pathlib import Path
from typing import Optional, List, Dict, Tuple, Any, Union, Set
from queue import Queue
import tkinter as tk
from tkinter import filedialog, messagebox
import chardet

# 嘗試匯入tkinterdnd2
try:
    from tkinterdnd2 import *
    TKDND_AVAILABLE = True
except ImportError:
    TKDND_AVAILABLE = False

# 嘗試匯入字幕相關套件
try:
    import pysrt
    PYSRT_AVAILABLE = True
except ImportError:
    PYSRT_AVAILABLE = False

try:
    import webvtt
    WEBVTT_AVAILABLE = True
except ImportError:
    WEBVTT_AVAILABLE = False

# 設定日誌
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

# 確保日誌目錄存在
os.makedirs('logs', exist_ok=True)

# 避免重複添加處理程序
if not logger.handlers:
    handler = logging.handlers.TimedRotatingFileHandler(
        filename='logs/file_handler.log',
        when='midnight',
        interval=1,
        backupCount=7,
        encoding='utf-8'
    )
    formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

class SubtitleInfo:
    """字幕檔案資訊類別"""
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.format = self._detect_format(file_path)
        self.encoding = self._detect_encoding(file_path)
        self.subtitle_count = 0
        self.duration = 0  # 秒數
        self.languages = []
        self.file_size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        self.last_modified = os.path.getmtime(file_path) if os.path.exists(file_path) else 0
        
        # 解析字幕檔案獲取更多資訊
        self._parse_subtitle_file()
    
    def _detect_format(self, file_path: str) -> str:
        """檢測字幕檔案格式"""
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.srt':
            return 'srt'
        elif ext == '.vtt':
            return 'vtt'
        elif ext in ['.ssa', '.ass']:
            return 'ass'
        elif ext == '.sub':
            return 'sub'
        else:
            return 'unknown'
    
    def _detect_encoding(self, file_path: str) -> str:
        """檢測檔案編碼"""
        try:
            with open(file_path, 'rb') as f:
                raw_data = f.read(4096)  # 讀取前4KB來檢測
                result = chardet.detect(raw_data)
                encoding = result['encoding'] or 'utf-8'
                confidence = result['confidence']
                
                # 如果可信度低於0.7，嘗試更多方法
                if confidence < 0.7:
                    # 檢查BOM標記
                    if raw_data.startswith(b'\xef\xbb\xbf'):
                        encoding = 'utf-8-sig'
                    elif raw_data.startswith(b'\xff\xfe'):
                        encoding = 'utf-16-le'
                    elif raw_data.startswith(b'\xfe\xff'):
                        encoding = 'utf-16-be'
                
                return encoding
        except Exception as e:
            logger.error(f"檢測檔案編碼時發生錯誤: {str(e)}")
            return 'utf-8'  # 預設為UTF-8
    
    def _parse_subtitle_file(self) -> None:
        """解析字幕檔案以獲取更多資訊"""
        try:
            if self.format == 'srt' and PYSRT_AVAILABLE:
                self._parse_srt_file()
            elif self.format == 'vtt' and WEBVTT_AVAILABLE:
                self._parse_vtt_file()
            elif self.format in ['ass', 'ssa']:
                self._parse_ass_file()
            # 其他格式可以根據需要添加
        except Exception as e:
            logger.error(f"解析字幕檔案時發生錯誤: {str(e)}")
    
    def _parse_srt_file(self) -> None:
        """解析SRT檔案"""
        try:
            subs = pysrt.open(self.file_path, encoding=self.encoding)
            self.subtitle_count = len(subs)
            
            # 計算總時長
            if self.subtitle_count > 0:
                try:
                    last_sub = subs[-1]
                    self.duration = last_sub.end.ordinal / 1000  # 轉換為秒
                except Exception as e:
                    logger.warning(f"計算SRT時長時發生錯誤: {str(e)}")
            
            # 嘗試檢測語言
            self._detect_language_from_content(subs)
        except Exception as e:
            logger.error(f"解析SRT檔案時發生錯誤: {str(e)}")
    
    def _parse_vtt_file(self) -> None:
        """解析VTT檔案"""
        try:
            vtt = webvtt.read(self.file_path)
            self.subtitle_count = len(vtt)
            
            # 計算總時長
            if self.subtitle_count > 0:
                try:
                    last_caption = vtt.captions[-1]
                    # WebVTT時間格式為HH:MM:SS.mmm
                    end_time = last_caption.end_in_seconds
                    self.duration = end_time
                except Exception as e:
                    logger.warning(f"計算VTT時長時發生錯誤: {str(e)}")
            
            # 嘗試檢測語言
            content = '\n'.join([caption.text for caption in vtt])
            self._detect_language_from_text(content)
        except Exception as e:
            logger.error(f"解析VTT檔案時發生錯誤: {str(e)}")
    
    def _parse_ass_file(self) -> None:
        """解析ASS/SSA檔案"""
        try:
            with open(self.file_path, 'r', encoding=self.encoding, errors='replace') as f:
                content = f.read()
            
            # 使用正規表達式提取字幕對話
            dialogue_pattern = re.compile(r'Dialogue: [^,]*,([^,]*),([^,]*),')
            matches = dialogue_pattern.findall(content)
            
            self.subtitle_count = len(matches)
            
            # 計算總時長
            if matches:
                # 試著從最後一個對話解析結束時間
                try:
                    last_end_time = matches[-1][1]  # 格式通常是 0:00:00.00
                    h, m, s = last_end_time.split(':')
                    self.duration = int(h) * 3600 + int(m) * 60 + float(s)
                except Exception as e:
                    logger.warning(f"計算ASS時長時發生錯誤: {str(e)}")
            
            # 嘗試檢測語言
            self._detect_language_from_text(content)
        except Exception as e:
            logger.error(f"解析ASS檔案時發生錯誤: {str(e)}")
    
    def _detect_language_from_content(self, subs) -> None:
        """從字幕內容檢測語言"""
        if self.subtitle_count == 0:
            return
        
        try:
            # 連接一些字幕文本用於語言檢測
            sample_size = min(10, self.subtitle_count)
            sample_text = '\n'.join([subs[i].text for i in range(sample_size)])
            self._detect_language_from_text(sample_text)
        except Exception as e:
            logger.warning(f"從字幕內容檢測語言時發生錯誤: {str(e)}")
            
    def _detect_language_from_text(self, text: str) -> None:
        """從文本檢測語言"""
        if not text:
            return
            
        # 基於字元分佈的簡單語言檢測
        # 檢測常見語言的特徵
        
        # 檢測日文(日文字元範圍)
        japanese_chars = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF]', text))
        
        # 檢測中文(中文字元範圍)
        chinese_chars = len(re.findall(r'[\u4E00-\u9FFF]', text))
        
        # 檢測韓文(韓文字元範圍)
        korean_chars = len(re.findall(r'[\uAC00-\uD7A3]', text))
        
        # 檢測英文和其他拉丁語言
        latin_chars = len(re.findall(r'[a-zA-Z]', text))
        
        # 統計字元總數(排除空白字元)
        total_chars = len(re.sub(r'\s', '', text))
        if total_chars == 0:
            return
            
        # 計算各語言佔比
        jp_ratio = japanese_chars / total_chars
        cn_ratio = chinese_chars / total_chars
        kr_ratio = korean_chars / total_chars
        latin_ratio = latin_chars / total_chars
        
        # 根據比例判斷語言
        if jp_ratio > 0.3:
            self.languages.append('日文')
        if cn_ratio > 0.3:
            self.languages.append('中文')
        if kr_ratio > 0.3:
            self.languages.append('韓文')
        if latin_ratio > 0.5:
            self.languages.append('英文')
        
        # 如果沒有檢測到任何語言，標記為未知
        if not self.languages:
            self.languages.append('未知')
    
    def get_summary(self) -> Dict[str, Any]:
        """獲取字幕檔案摘要資訊"""
        return {
            "檔案路徑": self.file_path,
            "檔案名稱": os.path.basename(self.file_path),
            "格式": self.format.upper(),
            "編碼": self.encoding,
            "字幕數量": self.subtitle_count,
            "時長": self._format_duration(self.duration),
            "檔案大小": self._format_size(self.file_size),
            "語言": ', '.join(self.languages) if self.languages else '未知',
            "最後修改": datetime.fromtimestamp(self.last_modified).strftime('%Y-%m-%d %H:%M:%S')
        }
    
    def _format_duration(self, seconds: float) -> str:
        """格式化時間為小時:分鐘:秒格式"""
        if seconds <= 0:
            return "未知"
        
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        
        if hours > 0:
            return f"{hours}時{minutes}分{secs}秒"
        else:
            return f"{minutes}分{secs}秒"
    
    def _format_size(self, size_bytes: int) -> str:
        """格式化檔案大小"""
        if size_bytes < 1024:
            return f"{size_bytes} B"
        elif size_bytes < 1024 * 1024:
            return f"{size_bytes / 1024:.1f} KB"
        else:
            return f"{size_bytes / (1024 * 1024):.2f} MB"

class FileHandler:
    def __init__(self, root: tk.Tk = None, config_file: str = "config/file_handler_config.json"):
        self.root = root
        self.config_file = config_file
        
        # 確保設定目錄存在
        os.makedirs(os.path.dirname(config_file), exist_ok=True)
        
        self.config = self._load_config()
        
        # 語言後綴對應表
        self.lang_suffix = self.config.get("lang_suffix", {
            "繁體中文": ".zh_tw", 
            "簡體中文": ".zh_cn",
            "英文": ".en", 
            "日文": ".jp",
            "韓文": ".kr",
            "法文": ".fr",
            "德文": ".de",
            "西班牙文": ".es",
            "俄文": ".ru"
        })
        
        # 支援的字幕格式
        self.supported_formats = self.config.get("supported_formats", [
            (".srt", "SRT字幕檔"),
            (".vtt", "WebVTT字幕檔"),
            (".ass", "ASS字幕檔"),
            (".ssa", "SSA字幕檔"),
            (".sub", "SUB字幕檔")
        ])
        
        # 用於讀取字幕檔案資訊的快取
        self.subtitle_info_cache = {}
        
        # 記住上次使用的目錄
        self.last_directory = self.config.get("last_directory", "")
        
        # 記住檔案選擇和批次管理的設定
        self.batch_settings = self.config.get("batch_settings", {
            "name_pattern": "{filename}_{language}{ext}",
            "overwrite_mode": "ask",  # ask, overwrite, rename, skip
            "output_directory": "",
            "preserve_folder_structure": True
        })
        
        logger.debug("FileHandler初始化完成")
    
    def _load_config(self) -> Dict[str, Any]:
        """載入設定檔案"""
        default_config = {
            "lang_suffix": {
                "繁體中文": ".zh_tw", 
                "簡體中文": ".zh_cn",
                "英文": ".en", 
                "日文": ".jp",
                "韓文": ".kr",
                "法文": ".fr",
                "德文": ".de",
                "西班牙文": ".es",
                "俄文": ".ru"
            },
            "supported_formats": [
                (".srt", "SRT字幕檔"),
                (".vtt", "WebVTT字幕檔"),
                (".ass", "ASS字幕檔"),
                (".ssa", "SSA字幕檔"),
                (".sub", "SUB字幕檔")
            ],
            "last_directory": "",
            "batch_settings": {
                "name_pattern": "{filename}_{language}{ext}",
                "overwrite_mode": "ask",
                "output_directory": "",
                "preserve_folder_structure": True
            }
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                logger.debug(f"已載入設定檔案: {self.config_file}")
                
                # 合併預設設定，確保所有設定都存在
                for key, value in default_config.items():
                    if key not in config:
                        config[key] = value
                    elif isinstance(value, dict) and isinstance(config[key], dict):
                        # 對於字典類型的設定，確保所有子項也存在
                        for sub_key, sub_value in value.items():
                            if sub_key not in config[key]:
                                config[key][sub_key] = sub_value
                
                return config
            else:
                logger.debug(f"設定檔案不存在，使用預設設定")
                # 儲存預設設定
                os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
                with open(self.config_file, 'w', encoding='utf-8') as f:
                    json.dump(default_config, f, ensure_ascii=False, indent=2)
                return default_config
                
        except Exception as e:
            logger.error(f"載入設定檔案時發生錯誤: {str(e)}")
            return default_config
    
    def _save_config(self) -> bool:
        """儲存設定到檔案"""
        try:
            # 更新設定中的最後使用目錄
            self.config["last_directory"] = self.last_directory
            self.config["batch_settings"] = self.batch_settings
            
            # 確保目錄存在
            os.makedirs(os.path.dirname(self.config_file), exist_ok=True)
            
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
            
            logger.debug(f"已儲存設定到檔案: {self.config_file}")
            return True
        except Exception as e:
            logger.error(f"儲存設定檔案時發生錯誤: {str(e)}")
            return False
    
    def add_language_suffix(self, language: str, suffix: str) -> None:
        """添加或更新語言後綴對應"""
        self.lang_suffix[language] = suffix
        self.config["lang_suffix"] = self.lang_suffix
        self._save_config()
        logger.debug(f"已添加語言後綴對應: {language} -> {suffix}")
    
    def select_files(self) -> List[str]:
        """通過對話框選擇檔案"""
        initial_dir = self.last_directory if os.path.exists(self.last_directory) else os.path.expanduser("~")
        
        # 構建檔案類型過濾器
        filetypes = []
        for ext, desc in self.supported_formats:
            filetypes.append((desc, f"*{ext}"))
        filetypes.append(("所有支援的字幕檔", " ".join([f"*{ext}" for ext, _ in self.supported_formats])))
        filetypes.append(("所有檔案", "*.*"))
        
        files = filedialog.askopenfilenames(
            title="選擇字幕檔案",
            initialdir=initial_dir,
            filetypes=filetypes
        )
        
        if files:
            # 更新最後使用的目錄
            self.last_directory = os.path.dirname(files[0])
            self._save_config()
            
            # 過濾非支援的檔案格式
            valid_files = []
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if any(ext == supported_ext for supported_ext, _ in self.supported_formats):
                    valid_files.append(file)
                else:
                    logger.warning(f"不支援的檔案格式: {file}")
            
            logger.info(f"已選擇 {len(valid_files)}/{len(files)} 個有效檔案")
            return valid_files
        
        return []
    
    def select_directory(self) -> str:
        """選擇目錄"""
        initial_dir = self.batch_settings["output_directory"] if os.path.exists(self.batch_settings["output_directory"]) else self.last_directory
        if not os.path.exists(initial_dir):
            initial_dir = os.path.expanduser("~")
            
        directory = filedialog.askdirectory(
            title="選擇輸出目錄",
            initialdir=initial_dir
        )
        
        if directory:
            self.batch_settings["output_directory"] = directory
            self._save_config()
            logger.info(f"已選擇輸出目錄: {directory}")
            return directory
        
        return ""
    
    def handle_drop(self, event) -> List[str]:
        """處理檔案拖放"""
        if not TKDND_AVAILABLE or not self.root:
            logger.warning("拖放功能不可用")
            return []
        
        files = self.root.tk.splitlist(event.data)
        valid_files = []
        
        for file in files:
            # 在 Windows 上移除檔案路徑的大括號
            file = file.strip('{}')
            
            # 檢查是否為目錄
            if os.path.isdir(file):
                # 掃描目錄下的字幕檔案
                logger.info(f"拖放了目錄: {file}，正在掃描字幕檔案...")
                dir_files = self.scan_directory(file)
                valid_files.extend(dir_files)
                logger.info(f"從目錄 {file} 找到 {len(dir_files)} 個字幕檔案")
            elif os.path.isfile(file):
                # 檢查檔案類型
                ext = os.path.splitext(file)[1].lower()
                if any(ext == supported_ext for supported_ext, _ in self.supported_formats):
                    valid_files.append(file)
                else:
                    logger.warning(f"不支援的檔案格式: {file}")
                    messagebox.showwarning("警告", f"檔案 {os.path.basename(file)} 不是支援的字幕格式，已略過")
            else:
                logger.warning(f"拖放的項目不是有效的檔案或目錄: {file}")
        
        # 更新最後使用的目錄(如果有有效檔案)
        if valid_files:
            self.last_directory = os.path.dirname(valid_files[0])
            self._save_config()
        
        return valid_files
    
    def scan_directory(self, directory: str, recursive: bool = True) -> List[str]:
        """掃描目錄下的字幕檔案"""
        valid_files = []
        valid_extensions = [ext for ext, _ in self.supported_formats]
        
        try:
            if recursive:
                # 遞迴掃描
                for root, _, files in os.walk(directory):
                    for file in files:
                        ext = os.path.splitext(file)[1].lower()
                        if ext in valid_extensions:
                            valid_files.append(os.path.join(root, file))
            else:
                # 僅掃描當前目錄
                with os.scandir(directory) as entries:
                    for entry in entries:
                        if entry.is_file():
                            ext = os.path.splitext(entry.name)[1].lower()
                            if ext in valid_extensions:
                                valid_files.append(entry.path)
        except Exception as e:
            logger.error(f"掃描目錄時發生錯誤: {str(e)}")
        
        return valid_files
    
    def get_subtitle_info(self, file_path: str, force_refresh: bool = False) -> Dict[str, Any]:
        """獲取字幕檔案的資訊"""
        if not os.path.exists(file_path):
            logger.warning(f"檔案不存在: {file_path}")
            return {"error": "檔案不存在"}
        
        # 檢查快取
        if not force_refresh and file_path in self.subtitle_info_cache:
            return self.subtitle_info_cache[file_path].get_summary()
        
        try:
            info = SubtitleInfo(file_path)
            # 更新快取
            self.subtitle_info_cache[file_path] = info
            return info.get_summary()
        except Exception as e:
            logger.error(f"獲取字幕資訊時發生錯誤: {str(e)}")
            return {"error": f"處理錯誤: {str(e)}"}

    def set_batch_settings(self, settings: Dict[str, Any]) -> None:
        """設定批次處理設定"""
        if settings:
            self.batch_settings.update(settings)
            self._save_config()
            logger.debug(f"已更新批次處理設定: {self.batch_settings}")
    
    def get_output_path(self, file_path: str, target_lang: str, progress_callback=None) -> Optional[str]:
        """獲取輸出檔案路徑並處理衝突"""
        try:
            # 檢查檔案是否存在
            if not os.path.exists(file_path):
                logger.warning(f"來源檔案不存在: {file_path}")
                return None
            
            dir_name, file_name = os.path.split(file_path)
            name, ext = os.path.splitext(file_name)
            
            # 應用批次設定中的輸出目錄
            output_dir = self.batch_settings["output_directory"]
            if output_dir and os.path.exists(output_dir):
                # 是否保留目錄結構
                if self.batch_settings["preserve_folder_structure"]:
                    # 獲取相對路徑(如果有共同的根目錄)
                    try:
                        common_base = os.path.commonpath([self.last_directory, file_path])
                        rel_dir = os.path.dirname(os.path.relpath(file_path, common_base))
                        new_dir = os.path.join(output_dir, rel_dir)
                        os.makedirs(new_dir, exist_ok=True)
                    except Exception as e:
                        logger.warning(f"計算相對路徑時發生錯誤: {str(e)}，使用平面結構")
                        new_dir = output_dir
                else:
                    new_dir = output_dir
                    
                dir_name = new_dir
            
            # 獲取語言後綴
            lang_suffix = self.lang_suffix.get(target_lang, ".unknown")
            
            # 應用檔案命名模式
            name_pattern = self.batch_settings["name_pattern"]
            output_filename = name_pattern.format(
                filename=name, 
                language=target_lang.lower(), 
                suffix=lang_suffix.replace(".", ""), 
                ext=ext,
                date=datetime.now().strftime('%Y%m%d'),
                time=datetime.now().strftime('%H%M%S')
            )
            
            # 如果輸出檔名沒有副檔名，添加原始副檔名
            if not os.path.splitext(output_filename)[1]:
                output_filename += ext
                
            base_path = os.path.join(dir_name, output_filename)
            
            # 處理檔案衝突
            if os.path.exists(base_path):
                # 檢查衝突處理模式
                overwrite_mode = self.batch_settings["overwrite_mode"]
                
                if overwrite_mode == "ask" and progress_callback:
                    # 通過回調函數詢問使用者
                    queue = Queue()
                    progress_callback(-1, -1, {"type": "file_conflict", "path": base_path, "queue": queue})
                    response = queue.get()
                    
                    if response == "rename":
                        return self._get_unique_path(dir_name, name, lang_suffix, ext)
                    elif response == "skip":
                        return None
                    # "overwrite" 情況直接返回 base_path
                
                elif overwrite_mode == "rename":
                    # 自動重新命名
                    return self._get_unique_path(dir_name, name, lang_suffix, ext)
                    
                elif overwrite_mode == "skip":
                    # 跳過已存在的檔案
                    logger.info(f"檔案已存在，跳過: {base_path}")
                    return None
                    
                # "overwrite" 情況直接返回 base_path
            
            return base_path
        except Exception as e:
            logger.error(f"獲取輸出路徑時發生錯誤: {str(e)}")
            return None
    
    def _get_unique_path(self, dir_name: str, name: str, lang_suffix: str, ext: str) -> str:
        """獲取唯一的檔案路徑(避免衝突)"""
        counter = 1
        while True:
            new_path = os.path.join(dir_name, f"{name}{lang_suffix}_{counter}{ext}")
            if not os.path.exists(new_path):
                return new_path
            counter += 1
    
    def load_api_key(self, file_path: str = "openapi_api_key.txt") -> str:
        """載入API金鑰"""
        try:
            # 嘗試從環境變數讀取
            api_key = os.environ.get("OPENAI_API_KEY")
            if api_key:
                logger.info("從環境變數載入API金鑰")
                return api_key
                
            # 嘗試從檔案讀取
            if os.path.exists(file_path):
                with open(file_path, 'r', encoding='utf-8') as f:
                    api_key = f.read().strip()
                    
                if api_key:
                    logger.info(f"從檔案 {file_path} 載入API金鑰")
                    return api_key
                    
            logger.warning(f"API金鑰檔案 {file_path} 不存在或為空")
            return ""
        except Exception as e:
            logger.error(f"讀取API金鑰時發生錯誤: {str(e)}")
            return ""
    
    def save_api_key(self, api_key: str, file_path: str = "openapi_api_key.txt") -> bool:
        """儲存API金鑰"""
        try:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(api_key)
            logger.info(f"已儲存API金鑰到檔案: {file_path}")
            return True
        except Exception as e:
            logger.error(f"儲存API金鑰時發生錯誤: {str(e)}")
            return False
    
    def convert_subtitle_format(self, input_path: str, target_format: str) -> Optional[str]:
        """轉換字幕檔案格式"""
        try:
            # 檢查來源檔案
            if not os.path.exists(input_path):
                logger.warning(f"來源檔案不存在: {input_path}")
                return None
                
            # 檢查來源格式和目標格式
            source_format = os.path.splitext(input_path)[1].lower().replace(".", "")
            if source_format == target_format:
                logger.info(f"來源檔案已經是 {target_format} 格式: {input_path}")
                return input_path
                
            # 獲取輸出檔案路徑
            output_dir = os.path.dirname(input_path)
            base_name = os.path.splitext(os.path.basename(input_path))[0]
            output_path = os.path.join(output_dir, f"{base_name}.{target_format}")
            
            # 確保輸出路徑不與來源檔案相同
            if output_path == input_path:
                output_path = os.path.join(output_dir, f"{base_name}_converted.{target_format}")
                
            # 處理檔案已存在的情況
            if os.path.exists(output_path):
                output_path = self._get_unique_path(
                    output_dir, 
                    base_name, 
                    "_converted", 
                    f".{target_format}"
                )
            
            # 根據不同格式進行轉換
            if source_format == "srt" and target_format == "vtt":
                self._convert_srt_to_vtt(input_path, output_path)
            elif source_format == "vtt" and target_format == "srt":
                self._convert_vtt_to_srt(input_path, output_path)
            # 更多格式轉換可以在這裡添加
            else:
                logger.warning(f"暫不支援從 {source_format} 轉換到 {target_format}")
                return None
                
            logger.info(f"已將 {input_path} 轉換為 {output_path}")
            return output_path
                
        except Exception as e:
            logger.error(f"轉換字幕格式時發生錯誤: {str(e)}")
            return None
    
    def _convert_srt_to_vtt(self, srt_path: str, vtt_path: str) -> None:
        """將SRT格式轉換為VTT格式"""
        if not PYSRT_AVAILABLE:
            raise ImportError("缺少pysrt套件，無法轉換SRT格式")
            
        # 讀取SRT檔案
        encoding = self.get_subtitle_info(srt_path).get("編碼", "utf-8")
        subs = pysrt.open(srt_path, encoding=encoding)
        
        # 寫入VTT檔案
        with open(vtt_path, 'w', encoding='utf-8') as f:
            f.write("WEBVTT\n\n")
            
            for sub in subs:
                # 轉換時間格式 (00:00:00,000 -> 00:00:00.000)
                start = sub.start.to_time().strftime('%H:%M:%S.%f')[:-3]
                end = sub.end.to_time().strftime('%H:%M:%S.%f')[:-3]
                
                # 寫入字幕
                f.write(f"{start} --> {end}\n")
                f.write(f"{sub.text}\n\n")
    
    def _convert_vtt_to_srt(self, vtt_path: str, srt_path: str) -> None:
        """將VTT格式轉換為SRT格式"""
        if not WEBVTT_AVAILABLE:
            raise ImportError("缺少webvtt套件，無法轉換VTT格式")
            
        # 讀取VTT檔案
        vtt = webvtt.read(vtt_path)
        
        # 寫入SRT檔案
        with open(srt_path, 'w', encoding='utf-8') as f:
            for i, caption in enumerate(vtt, 1):
                # 轉換時間格式 (00:00:00.000 -> 00:00:00,000)
                start = caption.start.replace('.', ',')
                end = caption.end.replace('.', ',')
                
                # 寫入字幕
                f.write(f"{i}\n")
                f.write(f"{start} --> {end}\n")
                f.write(f"{caption.text}\n\n")
    
    def extract_subtitle(self, video_path: str, callback=None) -> Optional[str]:
        """從影片檔案中提取字幕"""
        try:
            import subprocess
            
            # 檢查ffmpeg是否可用
            try:
                subprocess.run(["ffmpeg", "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            except (subprocess.SubprocessError, FileNotFoundError):
                logger.error("未找到ffmpeg，無法提取字幕")
                return None
                
            # 準備路徑
            output_dir = os.path.dirname(video_path)
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            output_path = os.path.join(output_dir, f"{base_name}.srt")
            
            # 確保輸出路徑不存在
            if os.path.exists(output_path):
                output_path = self._get_unique_path(
                    output_dir, 
                    base_name, 
                    "_extracted", 
                    ".srt"
                )
            
            # 提取字幕命令
            cmd = [
                "ffmpeg", "-i", video_path, 
                "-map", "0:s:0", # 選擇第一個字幕軌道
                "-c", "copy", 
                output_path
            ]
            
            # 執行命令
            if callback:
                callback(-1, -1, {"type": "extracting", "path": video_path})
                
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # 檢查結果
            if result.returncode != 0 or not os.path.exists(output_path) or os.path.getsize(output_path) == 0:
                logger.warning(f"提取字幕失敗: {result.stderr.decode()}")
                return None
                
            logger.info(f"已從 {video_path} 提取字幕到 {output_path}")
            return output_path
                
        except Exception as e:
            logger.error(f"提取字幕時發生錯誤: {str(e)}")
            return None