"""測試 errors 模組"""

import json
from datetime import datetime

from srt_translator.utils.errors import (
    APIKeyError,
    AppError,
    CacheError,
    ConfigError,
    FileError,
    ModelError,
    ModelNotFoundError,
    NetworkError,
    TimeoutError,
    TranslationError,
    ValidationError,
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


class TestNewErrorTypes:
    """測試新增的錯誤類別"""

    def test_api_key_error(self):
        """測試 APIKeyError"""
        error = APIKeyError("Invalid API key")
        assert error.error_code == 1600
        assert "Invalid API key" in str(error)
        assert isinstance(error, AppError)

    def test_model_not_found_error(self):
        """測試 ModelNotFoundError"""
        error = ModelNotFoundError("Model 'gpt-4' not found")
        assert error.error_code == 1700
        assert "Model 'gpt-4' not found" in str(error)
        assert isinstance(error, AppError)

    def test_cache_error(self):
        """測試 CacheError"""
        error = CacheError("Cache write failed")
        assert error.error_code == 1800
        assert "Cache write failed" in str(error)
        assert isinstance(error, AppError)

    def test_validation_error(self):
        """測試 ValidationError"""
        error = ValidationError("Invalid SRT format")
        assert error.error_code == 1900
        assert "Invalid SRT format" in str(error)
        assert isinstance(error, AppError)

    def test_timeout_error(self):
        """測試 TimeoutError"""
        error = TimeoutError("Request timeout after 30s")
        assert error.error_code == 2000
        assert "Request timeout after 30s" in str(error)
        assert isinstance(error, AppError)

    def test_new_errors_with_details(self):
        """測試新錯誤類型都支援 details 參數"""
        details = {"key": "value"}
        errors = [
            APIKeyError("test", details),
            ModelNotFoundError("test", details),
            CacheError("test", details),
            ValidationError("test", details),
            TimeoutError("test", details),
        ]

        for error in errors:
            assert error.details == details


class TestJSONSerialization:
    """測試 JSON 序列化功能"""

    def test_to_json_basic(self):
        """測試基本的 JSON 序列化"""
        error = AppError("Test error")
        json_str = error.to_json()

        # 驗證可以解析為 JSON
        error_data = json.loads(json_str)
        assert error_data["error_code"] == 1000
        assert error_data["message"] == "Test error"
        assert error_data["details"] == {}
        assert "timestamp" in error_data

    def test_to_json_with_details(self):
        """測試帶詳細信息的 JSON 序列化"""
        details = {"file": "test.srt", "line": 42, "severity": "high"}
        error = AppError("Error with details", details=details)
        json_str = error.to_json()

        error_data = json.loads(json_str)
        assert error_data["details"] == details

    def test_to_json_chinese_characters(self):
        """測試 JSON 序列化中文字符（ensure_ascii=False）"""
        error = AppError("錯誤訊息：找不到檔案")
        json_str = error.to_json()

        # 確保中文字符沒有被轉義
        assert "錯誤訊息" in json_str
        assert "找不到檔案" in json_str

        # 驗證可以正確解析
        error_data = json.loads(json_str)
        assert error_data["message"] == "錯誤訊息：找不到檔案"

    def test_to_json_all_error_types(self):
        """測試所有錯誤類型都支援 JSON 序列化"""
        errors = [
            ConfigError("Config error"),
            ModelError("Model error"),
            TranslationError("Translation error"),
            FileError("File error"),
            NetworkError("Network error"),
            APIKeyError("API key error"),
            ModelNotFoundError("Model not found"),
            CacheError("Cache error"),
            ValidationError("Validation error"),
            TimeoutError("Timeout error"),
        ]

        for error in errors:
            json_str = error.to_json()
            error_data = json.loads(json_str)
            assert "error_code" in error_data
            assert "message" in error_data
            assert "timestamp" in error_data

    def test_to_json_formatting(self):
        """測試 JSON 格式化（縮排）"""
        error = AppError("Test")
        json_str = error.to_json()

        # 驗證 JSON 有縮排（indent=2）
        assert "\n" in json_str
        lines = json_str.split("\n")
        assert len(lines) > 1  # 多行輸出
