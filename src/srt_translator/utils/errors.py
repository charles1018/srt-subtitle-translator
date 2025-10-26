"""錯誤與例外類別

定義專案中使用的自訂例外類別。
"""

from datetime import datetime
from typing import Dict, Any

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


