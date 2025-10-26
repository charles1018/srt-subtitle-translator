"""測試 errors 模組"""

import pytest
from datetime import datetime

from srt_translator.utils.errors import (
    AppError,
    ConfigError,
    ModelError,
    TranslationError,
    FileError,
    NetworkError,
)


class TestAppError:
    """測試 AppError 基礎異常類"""

    def test_app_error_basic(self):
        """測試基本的錯誤建立與訊息"""
        error = AppError("Test error message")
        assert str(error) == "[1000] Test error message"
        assert error.message == "Test error message"
        assert error.error_code == 1000
        assert error.details == {}

    def test_app_error_with_code(self):
        """測試自定義錯誤代碼"""
        error = AppError("Custom error", error_code=9999)
        assert str(error) == "[9999] Custom error"
        assert error.error_code == 9999

    def test_app_error_with_details(self):
        """測試附帶詳細信息的錯誤"""
        details = {"file": "test.srt", "line": 42}
        error = AppError("Error with details", details=details)
        assert error.details == details

    def test_app_error_to_dict(self):
        """測試錯誤轉換為字典格式"""
        error = AppError("Test error", error_code=1234, details={"key": "value"})
        error_dict = error.to_dict()

        assert error_dict["error_code"] == 1234
        assert error_dict["message"] == "Test error"
        assert error_dict["details"] == {"key": "value"}
        assert "timestamp" in error_dict
        # 驗證時間戳格式
        datetime.fromisoformat(error_dict["timestamp"])


class TestSpecificErrors:
    """測試特定錯誤類別"""

    def test_config_error(self):
        """測試 ConfigError"""
        error = ConfigError("Configuration failed")
        assert error.error_code == 1100
        assert "Configuration failed" in str(error)

    def test_model_error(self):
        """測試 ModelError"""
        error = ModelError("Model loading failed")
        assert error.error_code == 1200
        assert "Model loading failed" in str(error)

    def test_translation_error(self):
        """測試 TranslationError"""
        error = TranslationError("Translation failed")
        assert error.error_code == 1300
        assert "Translation failed" in str(error)

    def test_file_error(self):
        """測試 FileError"""
        error = FileError("File not found")
        assert error.error_code == 1400
        assert "File not found" in str(error)

    def test_network_error(self):
        """測試 NetworkError"""
        error = NetworkError("Connection timeout")
        assert error.error_code == 1500
        assert "Connection timeout" in str(error)

    def test_error_inheritance(self):
        """測試錯誤繼承關係"""
        config_error = ConfigError("Test")
        assert isinstance(config_error, AppError)
        assert isinstance(config_error, Exception)

    def test_error_with_details(self):
        """測試所有錯誤類型都支援 details 參數"""
        details = {"context": "test"}
        errors = [
            ConfigError("test", details),
            ModelError("test", details),
            TranslationError("test", details),
            FileError("test", details),
            NetworkError("test", details),
        ]

        for error in errors:
            assert error.details == details
