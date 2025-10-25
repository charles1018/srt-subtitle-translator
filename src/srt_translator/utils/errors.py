"""錯誤與例外類別

定義專案中使用的自訂例外類別。
"""

import os
import re
import json
import logging
import hashlib
import traceback
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple, Union, Callable

# ================ 錯誤處理類 ================

class AppError(Exception):
    """應用程式自定義基礎異常類"""

    def __init__(self, message: str, error_code: int = 1000, details: Dict[str, Any] = None):
        """初始化應用程式異常

        參數:
            message: 錯誤訊息
            error_code: 錯誤代碼
            details: 詳細信息字典
        """
        self.message = message
        self.error_code = error_code
        self.details = details or {}
        super().__init__(message)

    def __str__(self) -> str:
        """格式化錯誤訊息"""
        return f"[{self.error_code}] {self.message}"

    def to_dict(self) -> Dict[str, Any]:
        """轉換為字典格式"""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "details": self.details,
            "timestamp": datetime.now().isoformat()
        }


class ConfigError(AppError):
    """配置相關錯誤"""

    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, 1100, details)


class ModelError(AppError):
    """模型相關錯誤"""

    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, 1200, details)


class TranslationError(AppError):
    """翻譯相關錯誤"""

    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, 1300, details)


class FileError(AppError):
    """檔案相關錯誤"""

    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, 1400, details)


class NetworkError(AppError):
    """網路相關錯誤"""

    def __init__(self, message: str, details: Dict[str, Any] = None):
        super().__init__(message, 1500, details)


# ================ 工具函數 ================

def format_exception(e: Exception) -> str:
    """格式化例外訊息為可讀的字串

    參數:
        e: 例外物件

    回傳:
        格式化後的例外訊息
    """
    if isinstance(e, AppError):
        return f"{e.__class__.__name__}: {e.message}"
    else:
        return f"{e.__class__.__name__}: {str(e)}"


def safe_execute(func: Callable, *args, default_return=None, **kwargs) -> Any:
    """安全執行函數，捕捉例外並返回預設值

    參數:
        func: 要執行的函數
        *args: 位置參數
        default_return: 例外時的預設返回值
        **kwargs: 關鍵字參數

    回傳:
        函數執行結果或預設值
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logging.error(f"函數執行失敗 {func.__name__}: {format_exception(e)}")
        return default_return
