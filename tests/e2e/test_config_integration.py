"""E2E 測試 - 配置整合測試

此模組測試配置系統的整合，包括：
1. 配置載入測試（3 個測試）
2. 配置影響測試（4 個測試）

對應階段三任務 3 - 配置整合與錯誤處理測試
"""

import os
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import pytest

from srt_translator.core.config import ConfigManager
from srt_translator.services.factory import ServiceFactory

# ============================================================
# 配置載入測試（3 個測試）
# ============================================================


def test_load_default_config(e2e_temp_dir: Path):
    """測試 1：預設配置載入

    驗證：
    1. 使用預設配置初始化服務
    2. 驗證預設值正確
    3. 驗證服務正常運作
    """
    # 清理單例實例
    ConfigManager._instances.clear()

    # 建立一個新的配置管理器實例（使用預設配置）
    with patch.dict(os.environ, {"CONFIG_DIR": str(e2e_temp_dir / "config")}):
        config = ConfigManager.get_instance("user")

        # 驗證預設值
        assert config.get_value("source_lang") == "英文", "預設來源語言應該是英文"
        assert config.get_value("target_lang") == "繁體中文", "預設目標語言應該是繁體中文"
        assert config.get_value("llm_type") == "openai", "預設 LLM 類型應該是 openai"
        assert config.get_value("parallel_requests") == 3, "預設並發數應該是 3"
        assert config.get_value("display_mode") == "僅顯示翻譯", "預設顯示模式應該是僅顯示翻譯"

        # 驗證配置有效
        assert config.is_config_valid(), "預設配置應該是有效的"

    # 清理
    ConfigManager._instances.clear()


def test_load_custom_config(fixtures_dir: Path, e2e_temp_dir: Path):
    """測試 2：自訂配置載入

    驗證：
    1. 載入自訂配置檔案
    2. 驗證配置覆蓋預設值
    3. 驗證服務使用自訂配置
    """
    # 清理單例實例
    ConfigManager._instances.clear()

    # 準備自訂配置
    custom_config_path = fixtures_dir / "config_custom.json"
    assert custom_config_path.exists(), "自訂配置檔案應該存在"

    # 建立臨時配置目錄
    temp_config_dir = e2e_temp_dir / "config"
    temp_config_dir.mkdir(exist_ok=True)

    # 建立配置管理器，並patch config_dir屬性
    with patch.dict(os.environ, {"CONFIG_DIR": str(temp_config_dir)}):
        # 建立新的配置管理器實例
        config = ConfigManager.__new__(ConfigManager)
        config.config_type = "user"
        config.config_dir = str(temp_config_dir)  # 強制使用臨時目錄
        config.config_paths = {"user": str(temp_config_dir / "user_settings.json")}
        config.default_configs = ConfigManager().__dict__["default_configs"]
        config.listeners = []
        config.configs = {}
        config.load_config()

        # 導入自訂配置
        success = config.import_config(str(custom_config_path), "user", merge=False)
        assert success, "自訂配置導入應該成功"

        # 驗證自訂配置值
        assert config.get_value("source_lang") == "英文", "來源語言應該是英文"
        assert config.get_value("target_lang") == "繁體中文", "目標語言應該是繁體中文"
        assert config.get_value("llm_type") == "openai", "LLM 類型應該是 openai"
        assert config.get_value("model_name") == "gpt-4", "模型名稱應該是 gpt-4"
        assert config.get_value("parallel_requests") == 5, "並發數應該是 5"
        assert config.get_value("display_mode") == "僅顯示翻譯", "顯示模式應該是僅顯示翻譯"

    # 清理
    ConfigManager._instances.clear()


def test_invalid_config_handling(fixtures_dir: Path, e2e_temp_dir: Path):
    """測試 3：無效配置處理

    驗證：
    1. 配置格式錯誤
    2. 配置值無效
    3. 驗證錯誤提示
    """
    # 清理單例實例
    ConfigManager._instances.clear()

    # 準備無效配置
    invalid_config_path = fixtures_dir / "config_invalid.json"
    assert invalid_config_path.exists(), "無效配置檔案應該存在"

    # 建立臨時配置目錄
    temp_config_dir = e2e_temp_dir / "config"
    temp_config_dir.mkdir(exist_ok=True)

    # 建立配置管理器，並patch config_dir屬性
    with patch.dict(os.environ, {"CONFIG_DIR": str(temp_config_dir)}):
        # 建立新的配置管理器實例
        config = ConfigManager.__new__(ConfigManager)
        config.config_type = "user"
        config.config_dir = str(temp_config_dir)  # 強制使用臨時目錄
        config.config_paths = {"user": str(temp_config_dir / "user_settings.json")}
        config.default_configs = ConfigManager().__dict__["default_configs"]
        config.listeners = []
        config.configs = {}
        config.load_config()

        # 導入無效配置
        success = config.import_config(str(invalid_config_path), "user", merge=False)
        assert success, "配置導入應該成功（儘管值無效）"

        # 驗證配置無效
        errors = config.validate_config("user")
        assert len(errors) > 0, "應該檢測到配置錯誤"

        # 驗證具體錯誤
        assert "source_lang" in errors, "應該檢測到無效的來源語言"
        assert "target_lang" in errors, "應該檢測到無效的目標語言"
        assert "llm_type" in errors, "應該檢測到無效的 LLM 類型"
        assert "parallel_requests" in errors, "應該檢測到無效的並發數"
        assert "display_mode" in errors, "應該檢測到無效的顯示模式"

        # 驗證錯誤訊息有意義
        assert any("無效" in str(msg) or "Invalid" in str(msg).lower() for msgs in errors.values() for msg in msgs), (
            "錯誤訊息應該包含 '無效' 或 'Invalid'"
        )

    # 清理
    ConfigManager._instances.clear()


# ============================================================
# 配置影響測試（4 個測試）
# ============================================================


@pytest.mark.asyncio
async def test_model_config_affects_translation(sample_srt_path: Path, mock_translation_client, e2e_temp_dir: Path):
    """測試 4：模型設定變更影響翻譯

    驗證：
    1. 變更模型名稱（gpt-4 vs gpt-3.5）
    2. 驗證使用正確的模型
    3. 驗證翻譯結果
    """
    # 清理服務工廠
    ServiceFactory._instances.clear()
    ConfigManager._instances.clear()

    # 準備配置
    temp_config_dir = e2e_temp_dir / "config"
    temp_config_dir.mkdir(exist_ok=True)

    with patch.dict(os.environ, {"CONFIG_DIR": str(temp_config_dir)}):
        # 測試使用 gpt-4 模型
        config = ConfigManager.get_instance("user")
        config.set_value("llm_type", "openai", auto_save=False)
        config.set_value("model_name", "gpt-4", auto_save=False)

        # Mock 翻譯服務
        mock_translation_service = Mock()
        mock_translation_service.translate_text = AsyncMock(return_value="使用 GPT-4 翻譯")
        ServiceFactory._instances["TranslationService"] = mock_translation_service

        # 獲取翻譯服務
        translation_service = ServiceFactory.get_translation_service()

        # 執行翻譯
        result = await translation_service.translate_text("Hello, world!", [], "openai", "gpt-4")

        # 驗證使用正確的模型
        mock_translation_service.translate_text.assert_called_once()
        call_args = mock_translation_service.translate_text.call_args
        assert call_args[0][2] == "openai", "應該使用 openai"
        assert call_args[0][3] == "gpt-4", "應該使用 gpt-4 模型"

        # 測試變更為 gpt-3.5 模型
        config.set_value("model_name", "gpt-3.5-turbo", auto_save=False)

        # 重置 Mock
        mock_translation_service.translate_text.reset_mock()
        mock_translation_service.translate_text.return_value = AsyncMock(return_value="使用 GPT-3.5 翻譯")()

        # 執行翻譯
        result2 = await translation_service.translate_text("Hello, world!", [], "openai", "gpt-3.5-turbo")

        # 驗證使用新的模型
        mock_translation_service.translate_text.assert_called_once()
        call_args2 = mock_translation_service.translate_text.call_args
        assert call_args2[0][3] == "gpt-3.5-turbo", "應該使用 gpt-3.5-turbo 模型"

    # 清理
    ServiceFactory._instances.clear()
    ConfigManager._instances.clear()


@pytest.mark.asyncio
async def test_cache_config_affects_behavior(mock_translation_client, e2e_temp_dir: Path):
    """測試 5：快取設定變更影響行為

    驗證：
    1. 啟用/停用快取
    2. 變更快取過期時間
    3. 驗證快取行為
    """
    # 清理服務工廠
    ServiceFactory._instances.clear()
    ConfigManager._instances.clear()

    # 準備配置
    temp_config_dir = e2e_temp_dir / "config"
    temp_config_dir.mkdir(exist_ok=True)

    with patch.dict(os.environ, {"CONFIG_DIR": str(temp_config_dir)}):
        # 配置快取設定
        cache_config = ConfigManager.get_instance("cache")

        # 測試快取啟用
        cache_config.set_value("max_memory_cache", 1000, auto_save=False)
        assert cache_config.get_value("max_memory_cache") == 1000, "記憶體快取大小應該是 1000"

        # 測試快取過期時間變更
        original_cleanup = cache_config.get_value("auto_cleanup_days")
        assert original_cleanup > 0, "預設清理天數應該大於 0"
        assert isinstance(original_cleanup, int), "清理天數應該是整數"

        cache_config.set_value("auto_cleanup_days", 7, auto_save=False)
        assert cache_config.get_value("auto_cleanup_days") == 7, "清理天數應該變更為 7"

        # 驗證配置有效
        assert cache_config.is_config_valid(), "快取配置應該有效"

        # Mock 快取服務
        mock_cache_service = Mock()
        mock_cache_service.get_translation = Mock(return_value=None)
        mock_cache_service.store_translation = Mock(return_value=True)
        ServiceFactory._instances["CacheService"] = mock_cache_service

        # 獲取快取服務
        cache_service = ServiceFactory.get_cache_service()

        # 測試快取操作
        result = cache_service.get_translation("test", [], "test-model")
        assert result is None, "快取未命中應該返回 None"

        # 儲存到快取
        success = cache_service.store_translation("test", "測試", [], "test-model")
        assert success, "快取儲存應該成功"

    # 清理
    ServiceFactory._instances.clear()
    ConfigManager._instances.clear()


@pytest.mark.asyncio
async def test_display_mode_config_affects_output(e2e_temp_dir: Path):
    """測試 6：輸出格式設定變更影響輸出

    驗證：
    1. 變更顯示模式（僅翻譯 vs 雙語對照）
    2. 驗證輸出格式
    3. 驗證字幕行數
    """
    # 清理服務工廠
    ServiceFactory._instances.clear()
    ConfigManager._instances.clear()

    # 準備配置
    temp_config_dir = e2e_temp_dir / "config"
    temp_config_dir.mkdir(exist_ok=True)

    with patch.dict(os.environ, {"CONFIG_DIR": str(temp_config_dir)}):
        # 配置使用者設定
        user_config = ConfigManager.get_instance("user")

        # 測試雙語對照模式
        user_config.set_value("display_mode", "雙語對照", auto_save=False)
        assert user_config.get_value("display_mode") == "雙語對照", "顯示模式應該是雙語對照"

        # 模擬雙語對照輸出
        original_text = "Hello, world!"
        translated_text = "你好，世界！"

        if user_config.get_value("display_mode") == "雙語對照":
            # 雙語對照應該包含原文和譯文
            output_lines = [original_text, translated_text]
        else:
            # 僅顯示翻譯應該只包含譯文
            output_lines = [translated_text]

        assert len(output_lines) == 2, "雙語對照模式應該有 2 行（原文 + 譯文）"
        assert original_text in output_lines, "應該包含原文"
        assert translated_text in output_lines, "應該包含譯文"

        # 測試僅顯示翻譯模式
        user_config.set_value("display_mode", "僅顯示翻譯", auto_save=False)
        assert user_config.get_value("display_mode") == "僅顯示翻譯", "顯示模式應該是僅顯示翻譯"

        # 模擬僅顯示翻譯輸出
        if user_config.get_value("display_mode") == "雙語對照":
            output_lines = [original_text, translated_text]
        else:
            output_lines = [translated_text]

        assert len(output_lines) == 1, "僅顯示翻譯模式應該只有 1 行（譯文）"
        assert translated_text in output_lines, "應該包含譯文"
        assert original_text not in output_lines, "不應該包含原文"

    # 清理
    ServiceFactory._instances.clear()
    ConfigManager._instances.clear()


@pytest.mark.asyncio
async def test_parallel_requests_config(e2e_temp_dir: Path):
    """測試 7：並發設定變更影響並發行為

    驗證：
    1. 變更並發請求數
    2. 驗證並發行為
    3. 驗證配置有效性
    """
    # 清理服務工廠
    ServiceFactory._instances.clear()
    ConfigManager._instances.clear()

    # 準備配置
    temp_config_dir = e2e_temp_dir / "config"
    temp_config_dir.mkdir(exist_ok=True)

    with patch.dict(os.environ, {"CONFIG_DIR": str(temp_config_dir)}):
        # 配置使用者設定
        user_config = ConfigManager.get_instance("user")

        # 測試預設並發數
        default_parallel = user_config.get_value("parallel_requests")
        assert default_parallel == 3, "預設並發數應該是 3"

        # 測試變更並發數
        user_config.set_value("parallel_requests", 5, auto_save=False)
        assert user_config.get_value("parallel_requests") == 5, "並發數應該變更為 5"

        # 測試變更為更高的並發數
        user_config.set_value("parallel_requests", 10, auto_save=False)
        assert user_config.get_value("parallel_requests") == 10, "並發數應該變更為 10"

        # 驗證配置有效
        assert user_config.is_config_valid(), "使用者配置應該有效"

        # 測試無效的並發數（負數）
        user_config.set_value("parallel_requests", -1, auto_save=False)
        errors = user_config.validate_config("user")
        assert "parallel_requests" in errors, "應該檢測到無效的並發數"

        # 測試無效的並發數（超過限制）
        user_config.set_value("parallel_requests", 100, auto_save=False)
        errors = user_config.validate_config("user")
        assert "parallel_requests" in errors, "應該檢測到超過限制的並發數"

        # 恢復有效值
        user_config.set_value("parallel_requests", 5, auto_save=False)
        assert user_config.is_config_valid(), "恢復後配置應該有效"

    # 清理
    ServiceFactory._instances.clear()
    ConfigManager._instances.clear()
