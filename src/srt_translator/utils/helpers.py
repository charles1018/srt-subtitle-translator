"""工具函數模組

提供各種實用工具函數，包括文本處理、字幕處理、進度追踪等。
"""

import hashlib
import heapq
import json
import logging
import os
import re
import threading
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

# 導入錯誤類別
from srt_translator.utils.errors import AppError, TranslationError

# 導入日誌配置
from srt_translator.utils.logging_config import setup_logger

# 設置本模組的日誌記錄器
logger = setup_logger(__name__, log_file="utils.log")


def format_exception(e: Exception) -> str:
    """格式化異常信息

    參數:
        e: 異常對象

    回傳:
        格式化後的異常信息字符串
    """
    if isinstance(e, AppError):
        return str(e)

    # 獲取完整的堆疊追蹤
    tb_str = traceback.format_exception(type(e), e, e.__traceback__)

    # 只返回最關鍵的信息
    return f"{type(e).__name__}: {e!s}\n最後調用: {tb_str[-2].strip()}"


def safe_execute(func: Callable, *args, default_return=None, **kwargs) -> Any:
    """安全執行函數，捕獲並記錄異常

    參數:
        func: 要執行的函數
        *args: 函數參數
        default_return: 出錯時的默認返回值
        **kwargs: 函數關鍵字參數

    回傳:
        函數執行結果或default_return（如果出錯）
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"執行 {func.__name__} 失敗: {format_exception(e)}")
        return default_return


# ================ 文本處理工具 ================


def clean_text(text: str) -> str:
    """清理文本，去除多餘空格和特殊字符

    參數:
        text: 輸入文本

    回傳:
        清理後的文本
    """
    if not text:
        return ""

    # 移除控制字符
    text = re.sub(r"[\x00-\x1F\x7F]", " ", text)

    # 替換多個空格為單個空格
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def detect_language(text: str) -> str:
    """簡易語言檢測

    參數:
        text: 輸入文本

    回傳:
        檢測到的語言 ('ja', 'en', 'zh-tw', 'ko', 'unknown')

    注意:
        繁簡體中文區分非常困難，此函數默認返回 'zh-tw'。
        如需精確區分，建議使用專門的庫（如 opencc）。
    """
    if not text:
        return "unknown"

    # 樣本文本，避免分析過長
    sample = text[:1000]

    # 日文字符特徵（平假名 + 片假名）
    jp_chars = re.findall(r"[\u3040-\u309F\u30A0-\u30FF]", sample)
    # 韓文（諺文音節 + 諺文字母）
    ko_chars = re.findall(r"[\uAC00-\uD7A3\u1100-\u11FF\u3130-\u318F]", sample)
    # 英文
    en_chars = re.findall(r"[a-zA-Z]", sample)
    # 中文（通用 CJK 漢字範圍）
    zh_chars = re.findall(r"[\u4E00-\u9FFF]", sample)

    # 統計非空白字符總數
    total_chars = len(re.sub(r"\s", "", sample))
    if total_chars == 0:
        return "unknown"

    # 計算各語言占比
    jp_ratio = len(jp_chars) / total_chars
    ko_ratio = len(ko_chars) / total_chars
    en_ratio = len(en_chars) / total_chars
    zh_ratio = len(zh_chars) / total_chars

    # 根據占比確定語言（按優先級排序）
    if jp_ratio > 0.1:
        # 日文有明顯的假名特徵
        return "ja"
    elif ko_ratio > 0.1:
        # 韓文有明顯的諺文特徵
        return "ko"
    elif zh_ratio > 0.3:
        # 中文（繁簡體區分困難，默認返回繁體中文）
        # 如需精確區分，需使用專門庫如 opencc
        return "zh-tw"
    elif en_ratio > 0.5:
        # 英文為主
        return "en"

    return "unknown"


def standardize_language_code(lang_name: str) -> str:
    """將語言名稱轉換為標準代碼

    參數:
        lang_name: 語言名稱

    回傳:
        標準語言代碼
    """
    lang_map = {
        # 繁體中文
        "繁體中文": "zh-tw",
        "中文(繁體)": "zh-tw",
        "台灣中文": "zh-tw",
        "繁中": "zh-tw",
        "zh-tw": "zh-tw",
        "zh_tw": "zh-tw",
        "zh-hant": "zh-tw",
        "traditional chinese": "zh-tw",
        # 簡體中文
        "簡體中文": "zh-cn",
        "中文(簡體)": "zh-cn",
        "簡中": "zh-cn",
        "zh-cn": "zh-cn",
        "zh_cn": "zh-cn",
        "zh-hans": "zh-cn",
        "simplified chinese": "zh-cn",
        # 日文
        "日文": "ja",
        "日語": "ja",
        "ja": "ja",
        "jp": "ja",
        "japanese": "ja",
        # 英文
        "英文": "en",
        "英語": "en",
        "en": "en",
        "english": "en",
        # 韓文
        "韓文": "ko",
        "韓語": "ko",
        "ko": "ko",
        "kr": "ko",
        "korean": "ko",
        # 法文
        "法文": "fr",
        "法語": "fr",
        "fr": "fr",
        "french": "fr",
        # 德文
        "德文": "de",
        "德語": "de",
        "de": "de",
        "german": "de",
        # 西班牙文
        "西班牙文": "es",
        "西語": "es",
        "es": "es",
        "spanish": "es",
        # 俄文
        "俄文": "ru",
        "俄語": "ru",
        "ru": "ru",
        "russian": "ru",
    }

    normalized = lang_name.lower() if isinstance(lang_name, str) else ""
    return lang_map.get(normalized, lang_map.get(lang_name, "unknown"))


def get_language_name(lang_code: str) -> str:
    """將標準語言代碼轉換為人類可讀的語言名稱

    參數:
        lang_code: 語言代碼

    回傳:
        語言名稱
    """
    lang_names = {
        "zh-tw": "繁體中文",
        "zh-cn": "簡體中文",
        "ja": "日文",
        "en": "英文",
        "ko": "韓文",
        "fr": "法文",
        "de": "德文",
        "es": "西班牙文",
        "ru": "俄文",
    }

    return lang_names.get(lang_code.lower(), "未知語言")


def compute_text_hash(text: str) -> str:
    """計算文本的SHA-256哈希值

    參數:
        text: 輸入文本

    回傳:
        哈希字串
    """
    if not text:
        return ""

    # 使用SHA-256創建哈希
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def truncate_text(text: str, max_length: int = 100, with_ellipsis: bool = True) -> str:
    """截斷文本至指定長度

    參數:
        text: 輸入文本
        max_length: 最大長度
        with_ellipsis: 是否添加省略號

    回傳:
        截斷後的文本
    """
    if not text or len(text) <= max_length:
        return text

    if with_ellipsis:
        return text[: max_length - 3] + "..."
    else:
        return text[:max_length]


def split_sentences(text: str) -> List[str]:
    """將文本分割為句子

    參數:
        text: 輸入文本

    回傳:
        句子列表
    """
    if not text:
        return []

    # 中文標點符號
    cn_delimiters = r"。！？；"
    # 英文標點符號
    en_delimiters = r"\.!\?;"
    # 合并所有分隔符
    all_delimiters = f"[{cn_delimiters}{en_delimiters}]"

    # 按標點符號分割，保留標點
    sentences = re.findall(f".+?{all_delimiters}+|.+$", text)

    # 清理空白句子並去除前後空格
    return [s.strip() for s in sentences if s.strip()]


# ================ 字幕處理工具 ================


def format_srt_time(milliseconds: int) -> str:
    """將毫秒轉換為SRT時間格式 (HH:MM:SS,mmm)

    參數:
        milliseconds: 毫秒時間

    回傳:
        SRT格式時間字符串
    """
    if milliseconds < 0:
        milliseconds = 0

    hours = milliseconds // 3600000
    minutes = (milliseconds % 3600000) // 60000
    seconds = (milliseconds % 60000) // 1000
    millis = milliseconds % 1000

    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def parse_srt_time(time_str: str) -> int:
    """解析SRT時間格式為毫秒

    參數:
        time_str: SRT格式時間字符串 (HH:MM:SS,mmm)

    回傳:
        毫秒時間
    """
    if not time_str:
        return 0

    # 匹配 HH:MM:SS,mmm 格式
    pattern = r"(\d+):(\d+):(\d+)[,.](\d+)"
    match = re.match(pattern, time_str)

    if not match:
        return 0

    hours = int(match.group(1))
    minutes = int(match.group(2))
    seconds = int(match.group(3))
    millis = int(match.group(4))

    # 轉換為毫秒
    return hours * 3600000 + minutes * 60000 + seconds * 1000 + millis


def generate_unique_filename(base_path: str, extension: str = None) -> str:
    """生成不會衝突的唯一文件名

    參數:
        base_path: 基礎文件路徑
        extension: 文件擴展名(可選)

    回傳:
        唯一文件路徑
    """
    # 解析輸入路徑
    path = Path(base_path)
    directory = path.parent
    filename = path.stem
    ext = extension or path.suffix

    if not ext.startswith(".") and ext:
        ext = f".{ext}"

    counter = 1
    new_path = path

    # 如果存在同名文件，則添加計數後綴
    while new_path.exists():
        new_name = f"{filename}_{counter}{ext}"
        new_path = directory / new_name
        counter += 1

    return str(new_path)


def is_valid_subtitle_file(file_path: str) -> bool:
    """檢查文件是否為有效的字幕文件

    參數:
        file_path: 文件路徑

    回傳:
        是否為有效字幕文件
    """
    if not file_path or not os.path.exists(file_path):
        return False

    # 檢查文件擴展名
    valid_extensions = {".srt", ".vtt", ".ass", ".ssa", ".sub"}
    file_ext = os.path.splitext(file_path)[1].lower()

    if file_ext not in valid_extensions:
        return False

    # 檢查文件內容
    try:
        with open(file_path, encoding="utf-8", errors="ignore") as f:
            content = f.read(1024)  # 只讀取開頭部分進行檢查

            # 不同格式的特徵
            if file_ext == ".srt":
                # SRT格式通常以數字索引開頭，然後是時間戳
                return bool(re.search(r"^\d+\s*\n\d{2}:\d{2}:\d{2},\d{3}\s*-->", content, re.MULTILINE))
            elif file_ext == ".vtt":
                # VTT格式通常以WEBVTT開頭
                return "WEBVTT" in content
            elif file_ext in {".ass", ".ssa"}:
                # ASS/SSA格式包含特定的節
                return "[Script Info]" in content or "[V4+ Styles]" in content
    except Exception as e:
        logger.warning(f"檢查字幕文件 {file_path} 時發生錯誤: {e!s}")
        return False

    # 默認假設有效
    return True


# ================ 時間和格式工具 ================


def format_elapsed_time(seconds: float) -> str:
    """格式化耗時為易讀格式

    參數:
        seconds: 秒數

    回傳:
        格式化的時間字符串
    """
    if seconds < 60:
        return f"{int(seconds)} 秒"

    minutes = int(seconds // 60)
    seconds = int(seconds % 60)

    if minutes < 60:
        return f"{minutes} 分 {seconds} 秒"

    hours = int(minutes // 60)
    minutes = int(minutes % 60)
    return f"{hours} 小時 {minutes} 分 {seconds} 秒"


def format_datetime(dt: datetime = None, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """格式化日期時間

    參數:
        dt: 日期時間對象，默認為當前時間
        format_str: 格式化字符串

    回傳:
        格式化的日期時間字符串
    """
    if dt is None:
        dt = datetime.now()

    return dt.strftime(format_str)


def format_file_size(size_bytes: int) -> str:
    """格式化文件大小

    參數:
        size_bytes: 文件大小（字節）

    回傳:
        格式化的文件大小字符串
    """
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.2f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# ================ 進度跟踪工具 ================


class ProgressTracker:
    """進度追踪器，支持回調和估計剩餘時間"""

    def __init__(self, total: int = 0, description: str = "", callback: Callable = None):
        """初始化進度追踪器

        參數:
            total: 總項目數
            description: 進度描述
            callback: 進度更新回調函數
        """
        self.total = total
        self.current = 0
        self.description = description
        self.callback = callback

        self.start_time = None
        self.last_update_time = None
        self.estimated_end_time = None

        # 用於計算平均速率
        self.progress_history = []
        self.max_history = 20

    def start(self):
        """開始進度追踪"""
        self.start_time = time.time()
        self.last_update_time = self.start_time
        self.current = 0
        self.progress_history = []
        self._update()

        logger.debug(f"進度追踪開始: {self.description}, 總項目: {self.total}")

    def update(self, current: int = None, increment: int = None, description: str = None):
        """更新進度

        參數:
            current: 當前進度
            increment: 增量
            description: 更新的描述
        """
        now = time.time()

        # 更新描述
        if description:
            self.description = description

        # 更新進度
        if current is not None:
            self.current = current
        elif increment is not None:
            self.current += increment

        # 記錄歷史
        elapsed = now - self.last_update_time
        if elapsed > 0 and self.last_update_time != self.start_time:
            self.progress_history.append((elapsed, self.current))
            if len(self.progress_history) > self.max_history:
                self.progress_history.pop(0)

        self.last_update_time = now
        self._update()

    def increment(self, amount: int = 1, description: str = None):
        """增加進度

        參數:
            amount: 增加量
            description: 更新的描述
        """
        self.update(increment=amount, description=description)

    def complete(self, description: str = None):
        """完成進度追踪

        參數:
            description: 完成描述
        """
        self.current = self.total
        if description:
            self.description = description
        self._update()

        logger.debug(f"進度追踪完成: {self.description}, 總耗時: {self.get_elapsed_time_str()}")

    def _update(self):
        """內部更新方法，計算預估時間並調用回調"""
        if not self.start_time:
            self.start_time = time.time()

        # 更新預估完成時間
        if self.total > 0 and self.current > 0 and self.current < self.total:
            remaining = self.get_estimated_remaining_time()
            if remaining > 0:
                self.estimated_end_time = time.time() + remaining

        # 調用回調函數
        if self.callback:
            self.callback(
                current=self.current,
                total=self.total,
                description=self.description,
                elapsed=self.get_elapsed_time(),
                remaining=self.get_estimated_remaining_time(),
            )

    def get_elapsed_time(self) -> float:
        """獲取已耗時間（秒）

        回傳:
            已耗時間（秒）
        """
        if not self.start_time:
            return 0
        return time.time() - self.start_time

    def get_elapsed_time_str(self) -> str:
        """獲取格式化的已耗時間

        回傳:
            格式化的已耗時間字串
        """
        return format_elapsed_time(self.get_elapsed_time())

    def get_estimated_remaining_time(self) -> float:
        """獲取估計剩餘時間（秒）

        回傳:
            估計剩餘時間（秒）
        """
        if not self.start_time or self.total <= 0 or self.current <= 0 or self.current >= self.total:
            return 0

        # 使用進度歷史計算平均速率
        if self.progress_history:
            total_time = sum(time for time, _ in self.progress_history)
            progress_diff = self.current - self.progress_history[0][1]

            if progress_diff > 0 and total_time > 0:
                rate = progress_diff / total_time  # 項目/秒
                remaining_items = self.total - self.current
                return remaining_items / rate

        # 備用方法：使用總體平均速度
        elapsed = self.get_elapsed_time()
        if elapsed > 0:
            rate = self.current / elapsed  # 項目/秒
            if rate > 0:
                remaining_items = self.total - self.current
                return remaining_items / rate

        return 0

    def get_estimated_remaining_time_str(self) -> str:
        """獲取格式化的估計剩餘時間

        回傳:
            格式化的估計剩餘時間字串
        """
        return format_elapsed_time(self.get_estimated_remaining_time())

    def get_progress_percentage(self) -> float:
        """獲取進度百分比

        回傳:
            進度百分比 (0-100)
        """
        if self.total <= 0:
            return 0
        return (self.current / self.total) * 100

    def get_status_text(self) -> str:
        """獲取完整的狀態文本

        回傳:
            狀態文本
        """
        percent = self.get_progress_percentage()
        elapsed = self.get_elapsed_time_str()
        remaining = self.get_estimated_remaining_time_str()

        if self.current >= self.total:
            return f"{self.description}: 完成! ({elapsed})"
        else:
            return (
                f"{self.description}: {self.current}/{self.total} ({percent:.1f}%) - 已用: {elapsed}, 剩餘: {remaining}"
            )


# ================ 網絡檢查工具 ================


def check_internet_connection() -> bool:
    """檢查互聯網連接是否正常

    回傳:
        是否連接正常
    """
    import socket

    try:
        # 嘗試連接到Google的DNS伺服器
        socket.create_connection(("8.8.8.8", 53), timeout=3)
        return True
    except (OSError, socket.timeout):
        return False


def check_api_connection(api_url: str, timeout: int = 5) -> bool:
    """檢查API連接是否正常

    參數:
        api_url: API URL
        timeout: 超時（秒）

    回傳:
        是否連接正常
    """
    import urllib.request

    try:
        urllib.request.urlopen(api_url, timeout=timeout)
        return True
    except:
        return False


# ================ 系統信息工具 ================


def get_system_info() -> Dict[str, Any]:
    """獲取系統信息

    回傳:
        系統信息字典
    """
    import platform

    import psutil

    info = {
        "system": platform.system(),
        "version": platform.version(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": psutil.cpu_count(),
        "memory": {
            "total": psutil.virtual_memory().total,
            "available": psutil.virtual_memory().available,
            "percent": psutil.virtual_memory().percent,
        },
        "disk": {
            "total": psutil.disk_usage("/").total,
            "free": psutil.disk_usage("/").free,
            "percent": psutil.disk_usage("/").percent,
        },
    }

    # 格式化大小數值
    info["memory"]["total_formatted"] = format_file_size(info["memory"]["total"])
    info["memory"]["available_formatted"] = format_file_size(info["memory"]["available"])
    info["disk"]["total_formatted"] = format_file_size(info["disk"]["total"])
    info["disk"]["free_formatted"] = format_file_size(info["disk"]["free"])

    return info


def check_python_packages() -> Dict[str, str]:
    """檢查關鍵Python包的版本

    回傳:
        包名和版本字典
    """
    import importlib

    import pkg_resources

    required_packages = ["pysrt", "tiktoken", "aiohttp", "backoff", "openai", "numpy", "matplotlib", "chardet"]

    package_versions = {}

    for package in required_packages:
        try:
            package_versions[package] = pkg_resources.get_distribution(package).version
        except (pkg_resources.DistributionNotFound, pkg_resources.VersionConflict):
            try:
                # 嘗試直接導入並檢查版本
                module = importlib.import_module(package)
                if hasattr(module, "__version__"):
                    package_versions[package] = module.__version__
                elif hasattr(module, "version"):
                    package_versions[package] = module.version
                else:
                    package_versions[package] = "已安裝但無法確定版本"
            except ImportError:
                package_versions[package] = "未安裝"

    return package_versions


# ================ 本地化和國際化工具 ================


class LocaleManager:
    """本地化管理器，處理多語言文本"""

    def __init__(self, locale_dir: str = "locales", default_locale: str = "zh-tw"):
        """初始化本地化管理器

        參數:
            locale_dir: 本地化文件目錄
            default_locale: 默認語言代碼
        """
        self.locale_dir = locale_dir
        self.default_locale = default_locale
        self.current_locale = default_locale
        self.translations = {}

        # 確保目錄存在
        os.makedirs(self.locale_dir, exist_ok=True)

        # 載入默認語言
        self._load_locale(default_locale)

    def _load_locale(self, locale_code: str) -> bool:
        """載入特定語言的翻譯

        參數:
            locale_code: 語言代碼

        回傳:
            是否成功載入
        """
        if locale_code in self.translations:
            return True

        locale_file = os.path.join(self.locale_dir, f"{locale_code}.json")

        try:
            if os.path.exists(locale_file):
                with open(locale_file, encoding="utf-8") as f:
                    self.translations[locale_code] = json.load(f)
                logger.debug(f"已載入語言文件: {locale_file}")
                return True
            else:
                # 如果是默認語言但文件不存在，創建空字典
                if locale_code == self.default_locale:
                    self.translations[locale_code] = {}
                    return True
                # 否則嘗試使用默認語言
                return False
        except Exception as e:
            logger.error(f"載入語言文件 {locale_file} 失敗: {e!s}")
            # 創建空字典以避免重複載入嘗試
            self.translations[locale_code] = {}
            return False

    def set_locale(self, locale_code: str) -> bool:
        """設置當前語言

        參數:
            locale_code: 語言代碼

        回傳:
            是否成功設置
        """
        # 規範化語言代碼
        locale_code = standardize_language_code(locale_code)

        # 嘗試載入語言文件
        if locale_code not in self.translations and not self._load_locale(locale_code):
            logger.warning(f"無法載入語言 {locale_code}，使用默認語言 {self.default_locale}")
            return False

        # 設置當前語言
        self.current_locale = locale_code
        logger.info(f"已設置語言為: {locale_code}")
        return True

    def get_text(self, key: str, **kwargs) -> str:
        """獲取本地化文本

        參數:
            key: 文本鍵名
            **kwargs: 用於替換的參數

        回傳:
            本地化的文本
        """
        # 先嘗試當前語言
        if self.current_locale in self.translations and key in self.translations[self.current_locale]:
            text = self.translations[self.current_locale][key]
        # 然後嘗試默認語言
        elif self.default_locale in self.translations and key in self.translations[self.default_locale]:
            text = self.translations[self.default_locale][key]
        # 最後回退到鍵名本身
        else:
            text = key

        # 替換參數
        if kwargs:
            try:
                return text.format(**kwargs)
            except KeyError as e:
                logger.warning(f"格式化文本 '{key}' 時缺少參數: {e!s}")
                return text

        return text

    def save_translations(self, locale_code: str = None) -> bool:
        """保存翻譯到文件

        參數:
            locale_code: 語言代碼，默認為當前語言

        回傳:
            是否成功保存
        """
        if locale_code is None:
            locale_code = self.current_locale

        if locale_code not in self.translations:
            return False

        locale_file = os.path.join(self.locale_dir, f"{locale_code}.json")

        try:
            with open(locale_file, "w", encoding="utf-8") as f:
                json.dump(self.translations[locale_code], f, ensure_ascii=False, indent=4)
            logger.info(f"已保存語言文件: {locale_file}")
            return True
        except Exception as e:
            logger.error(f"保存語言文件 {locale_file} 失敗: {e!s}")
            return False

    def add_translation(self, key: str, text: str, locale_code: str = None) -> bool:
        """添加或更新翻譯

        參數:
            key: 文本鍵名
            text: 翻譯文本
            locale_code: 語言代碼，默認為當前語言

        回傳:
            是否成功添加
        """
        if locale_code is None:
            locale_code = self.current_locale

        # 確保語言字典存在
        if locale_code not in self.translations:
            self.translations[locale_code] = {}

        # 添加翻譯
        self.translations[locale_code][key] = text

        # 保存到文件
        return self.save_translations(locale_code)

    def get_available_locales(self) -> List[str]:
        """獲取所有可用的語言

        回傳:
            語言代碼列表
        """
        locales = list(self.translations.keys())

        # 檢查目錄中的語言文件
        if os.path.exists(self.locale_dir):
            for file in os.listdir(self.locale_dir):
                if file.endswith(".json"):
                    locale_code = os.path.splitext(file)[0]
                    if locale_code not in locales:
                        locales.append(locale_code)

        return locales


# ================ 快取工具 ================


class MemoryCache:
    """簡單的記憶體快取實現"""

    def __init__(self, max_size: int = 1000, ttl: int = 3600):
        """初始化記憶體快取

        參數:
            max_size: 最大項目數
            ttl: 存活時間（秒）
        """
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl
        self.lock = threading.RLock()

    def get(self, key: str, default=None):
        """獲取快取項目

        參數:
            key: 鍵名
            default: 默認返回值

        回傳:
            快取值或默認值
        """
        with self.lock:
            if key not in self.cache:
                return default

            item = self.cache[key]
            # 檢查是否過期
            if time.time() > item["expires"]:
                del self.cache[key]
                return default

            # 更新訪問時間
            item["last_access"] = time.time()
            return item["value"]

    def set(self, key: str, value, ttl: int = None) -> bool:
        """設置快取項目

        參數:
            key: 鍵名
            value: 值
            ttl: 此項目的存活時間（秒）

        回傳:
            是否成功設置
        """
        with self.lock:
            # 檢查是否需要清理
            if len(self.cache) >= self.max_size and key not in self.cache:
                self._cleanup()

            # 設置快取項目
            expires = time.time() + (ttl if ttl is not None else self.ttl)
            self.cache[key] = {"value": value, "expires": expires, "last_access": time.time()}

            return True

    def delete(self, key: str) -> bool:
        """刪除快取項目

        參數:
            key: 鍵名

        回傳:
            是否成功刪除
        """
        with self.lock:
            if key in self.cache:
                del self.cache[key]
                return True
            return False

    def clear(self) -> None:
        """清空快取"""
        with self.lock:
            self.cache.clear()

    def _cleanup(self) -> None:
        """清理過期和最少使用的項目"""
        with self.lock:
            now = time.time()

            # 首先刪除過期項目
            expired_keys = [k for k, v in self.cache.items() if v["expires"] <= now]
            for k in expired_keys:
                del self.cache[k]

            # 如果仍然超出大小限制，刪除最少使用的項目
            if len(self.cache) >= self.max_size:
                items_to_remove = int(len(self.cache) * 0.3)
                if items_to_remove > 0:
                    # 使用 heapq.nsmallest 只找出需要刪除的項目，避免完整排序
                    # 時間複雜度從 O(n log n) 降為 O(n log k)
                    oldest_items = heapq.nsmallest(
                        items_to_remove,
                        self.cache.items(),
                        key=lambda x: x[1]["last_access"],
                    )
                    for k, _ in oldest_items:
                        del self.cache[k]

    def get_stats(self) -> Dict[str, Any]:
        """獲取快取統計信息

        回傳:
            統計信息字典
        """
        with self.lock:
            stats = {"size": len(self.cache), "max_size": self.max_size, "ttl": self.ttl}

            if self.cache:
                now = time.time()
                active_items = [v for v in self.cache.values() if v["expires"] > now]
                stats["active_items"] = len(active_items)
                stats["expired_items"] = len(self.cache) - len(active_items)

                if active_items:
                    avg_age = sum(now - v["last_access"] for v in active_items) / len(active_items)
                    stats["average_age"] = round(avg_age, 2)

                    oldest = min(v["last_access"] for v in active_items)
                    stats["oldest_item_age"] = round(now - oldest, 2)

            return stats


# ================ 執行常用命令工具 ================


def execute_command(command: List[str], timeout: int = 60, capture_output: bool = True) -> Tuple[int, str, str]:
    """執行系統命令

    參數:
        command: 命令列表
        timeout: 超時（秒）
        capture_output: 是否捕獲輸出

    回傳:
        (返回碼, 標準輸出, 標準錯誤)
    """
    import subprocess

    try:
        result = subprocess.run(command, timeout=timeout, capture_output=capture_output, text=True, check=False)

        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return -1, "", "Command timed out"
    except Exception as e:
        return -2, "", str(e)


def is_command_available(command: str) -> bool:
    """檢查命令是否可用

    參數:
        command: 命令名稱

    回傳:
        命令是否可用
    """
    import shutil

    return shutil.which(command) is not None


# ================ 初始化全局實例 ================

# 全局本地化管理器
locale_manager = LocaleManager()

# 全局記憶體快取
memory_cache = MemoryCache()

# 測試程式碼
if __name__ == "__main__":
    # 設定控制台日誌以便於查看輸出
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
    logger.addHandler(console_handler)

    print("===== 工具模組測試 =====")

    # 測試錯誤處理工具
    print("\n1. 測試錯誤處理工具")
    try:
        raise TranslationError("翻譯過程中發生錯誤", {"file": "test.srt", "line": 10})
    except AppError as e:
        print(f"捕獲應用錯誤: {e}")
        print(f"錯誤詳情: {e.to_dict()}")

    # 測試文本處理工具
    print("\n2. 測試文本處理工具")
    sample_text = "  這是一個   測試文本，包含多餘的空格。  "
    print(f"清理前: '{sample_text}'")
    print(f"清理後: '{clean_text(sample_text)}'")

    jp_text = "こんにちは、世界"
    print(f"文本 '{jp_text}' 的語言: {detect_language(jp_text)}")

    # 測試進度追踪工具
    print("\n3. 測試進度追踪工具")

    def progress_callback(current, total, description, elapsed, remaining):
        print(
            f"\r{description}: {current}/{total} ({current / total * 100:.1f}%) - "
            f"已用: {format_elapsed_time(elapsed)}, 剩餘: {format_elapsed_time(remaining)}",
            end="",
        )

    tracker = ProgressTracker(total=10, description="處理文件", callback=progress_callback)
    tracker.start()

    for i in range(10):
        time.sleep(0.2)  # 模擬處理時間
        tracker.increment()

    tracker.complete()
    print("\n進度完成!")

    # 測試系統信息
    print("\n4. 測試系統信息工具")
    system_info = get_system_info()
    print(f"操作系統: {system_info['system']} {system_info['version']}")
    print(f"Python版本: {system_info['python_version']}")
    print(
        f"記憶體: {system_info['memory']['available_formatted']} 可用 / {system_info['memory']['total_formatted']} 總計"
    )

    # 測試本地化工具
    print("\n5. 測試本地化工具")
    locale_manager.add_translation("welcome", "歡迎使用翻譯工具")
    locale_manager.add_translation("hello_user", "你好，{name}！")

    print(locale_manager.get_text("welcome"))
    print(locale_manager.get_text("hello_user", name="使用者"))

    print("\n===== 測試完成 =====")
