"""錯誤與例外類別

定義專案中使用的自訂例外類別，提供統一的錯誤處理與日誌記錄。

錯誤碼規範：
    1000: AppError - 基礎應用程式錯誤
    1100: ConfigError - 配置相關錯誤
    1200: ModelError - 模型相關錯誤
    1300: TranslationError - 翻譯相關錯誤
    1400: FileError - 檔案相關錯誤
    1500: NetworkError - 網路相關錯誤
    1600: APIKeyError - API 金鑰相關錯誤
    1700: ModelNotFoundError - 模型未找到錯誤
    1800: CacheError - 快取操作錯誤
    1900: ValidationError - 資料驗證錯誤
    2000: TimeoutError - 操作超時錯誤

使用範例：
    >>> try:
    ...     # 執行某個操作
    ...     raise APIKeyError("API 金鑰無效", details={"key_prefix": "sk-xxx"})
    ... except AppError as e:
    ...     # 取得錯誤訊息
    ...     print(str(e))  # [1600] API 金鑰無效
    ...
    ...     # 轉換為字典格式
    ...     error_dict = e.to_dict()
    ...
    ...     # 轉換為 JSON 格式（用於結構化日誌）
    ...     error_json = e.to_json()
"""

import json
from datetime import datetime
from typing import Any, Dict, Optional

# ================ 錯誤處理類 ================


class AppError(Exception):
    """應用程式自定義基礎異常類"""

    def __init__(self, message: str, error_code: int = 1000, details: Optional[Dict[str, Any]] = None):
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
            "timestamp": datetime.now().isoformat(),
        }

    def to_json(self) -> str:
        """轉換為 JSON 格式字串

        返回:
            JSON 格式的錯誤訊息字串
        """
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


class ConfigError(AppError):
    """配置相關錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1100, details)


class ModelError(AppError):
    """模型相關錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1200, details)


class TranslationError(AppError):
    """翻譯相關錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1300, details)


class FileError(AppError):
    """檔案相關錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1400, details)


class NetworkError(AppError):
    """網路相關錯誤"""

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1500, details)


class APIKeyError(AppError):
    """API 金鑰相關錯誤

    當 API 金鑰遺失、無效或權限不足時拋出此例外。
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1600, details)


class ModelNotFoundError(AppError):
    """模型未找到錯誤

    當請求的翻譯模型不存在或無法載入時拋出此例外。
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1700, details)


class CacheError(AppError):
    """快取操作錯誤

    當快取讀取、寫入或清除操作失敗時拋出此例外。
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1800, details)


class ValidationError(AppError):
    """資料驗證錯誤

    當輸入資料格式不正確或驗證失敗時拋出此例外。
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 1900, details)


class TimeoutError(AppError):
    """操作超時錯誤

    當操作執行時間超過預設時限時拋出此例外。
    """

    def __init__(self, message: str, details: Optional[Dict[str, Any]] = None):
        super().__init__(message, 2000, details)
