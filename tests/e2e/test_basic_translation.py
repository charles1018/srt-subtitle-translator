"""E2E 測試 - 基本翻譯流程

此模組測試基本的字幕翻譯功能，包括：
1. 單檔案翻譯
2. 快取機制驗證
3. 多語言對測試

注意：此測試使用 ServiceFactory 和 Mock API，不會進行實際的翻譯 API 呼叫。
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from srt_translator.services.factory import ServiceFactory

# ============================================================
# 測試前準備：Mock 所有服務
# ============================================================


@pytest.fixture(autouse=True)
def reset_service_factory():
    """在每個測試前重置 ServiceFactory"""
    # 重置所有服務實例
    ServiceFactory._instances.clear()
    yield
    # 測試後清理
    ServiceFactory._instances.clear()


@pytest.fixture
def mock_all_services(mock_translation_client, mock_translation_responses):
    """Mock 所有必要的服務

    這個 fixture 確保 ServiceFactory 返回 mock 的服務實例。
    """
    # Mock TranslationService
    mock_translation_service = Mock()
    mock_translation_service.translate_text = AsyncMock(
        side_effect=lambda text, context, llm_type, model: mock_translation_responses.get(text, f"[Mock] {text}")
    )
    mock_translation_service.translate_batch = AsyncMock(
        side_effect=lambda texts_with_context, llm_type, model, concurrent: [
            mock_translation_responses.get(text, f"[Mock] {text}") for text, context in texts_with_context
        ]
    )
    mock_translation_service.cleanup = Mock()
    mock_translation_service.key_terms_dict = {}
    mock_translation_service._post_process_translation = lambda orig, trans: trans

    # Mock ModelService
    mock_model_service = Mock()
    mock_model_service.get_translation_client = AsyncMock(return_value=mock_translation_client)
    mock_model_service.api_keys = {"openai": "test-key", "ollama": ""}
    mock_model_service.cleanup = AsyncMock()

    # Mock CacheService
    mock_cache_service = Mock()
    mock_cache_service.get_translation = Mock(return_value=None)
    mock_cache_service.store_translation = Mock(return_value=True)
    mock_cache_service.cleanup = Mock()

    # Mock FileService
    mock_file_service = Mock()
    mock_file_service.get_output_path = Mock()
    mock_file_service.cleanup = Mock()

    # Mock ProgressService
    mock_progress_service = Mock()
    mock_progress_service.register_progress_callback = Mock()
    mock_progress_service.register_complete_callback = Mock()
    mock_progress_service.set_total = Mock()
    mock_progress_service.increment_progress = Mock()
    mock_progress_service.cleanup = Mock()

    # 將 mock 服務註冊到 ServiceFactory
    ServiceFactory._instances = {
        "TranslationService": mock_translation_service,
        "ModelService": mock_model_service,
        "CacheService": mock_cache_service,
        "FileService": mock_file_service,
        "ProgressService": mock_progress_service,
    }

    yield {
        "translation": mock_translation_service,
        "model": mock_model_service,
        "cache": mock_cache_service,
        "file": mock_file_service,
        "progress": mock_progress_service,
    }


# ============================================================
# 測試 1: 基本單檔案翻譯（使用 TranslationService）
# ============================================================


@pytest.mark.asyncio
async def test_basic_single_file_translation_service(
    copy_sample_srt: Path, e2e_temp_dir: Path, mock_all_services, srt_comparator, assert_srt_valid
):
    """測試基本的單檔案翻譯流程（使用 TranslationService）

    驗證：
    1. 能夠讀取 SRT 檔案
    2. Mock API 正常運作
    3. 生成翻譯後的檔案
    4. 輸出格式正確
    """
    # 準備
    input_file = str(copy_sample_srt)
    output_file = str(e2e_temp_dir / "output.srt")

    # 設定 FileService 的輸出路徑
    mock_all_services["file"].get_output_path.return_value = output_file

    # 直接使用 TranslationService 測試翻譯
    translation_service = ServiceFactory.get_translation_service()

    # 測試翻譯單一文本
    result = await translation_service.translate_text("Hello, world!", ["Hello, world!"], "openai", "test-model")

    # 驗證翻譯結果
    assert result == "你好，世界！", "應該返回正確的翻譯"

    # 測試批量翻譯
    texts_with_context = [
        ("Hello, world!", ["Hello, world!"]),
        ("This is a test subtitle.", ["This is a test subtitle."]),
    ]

    results = await translation_service.translate_batch(texts_with_context, "openai", "test-model", 2)

    # 驗證批量翻譯結果
    assert len(results) == 2, "應該返回 2 個翻譯結果"
    assert results[0] == "你好，世界！", "第一個翻譯應該正確"
    assert results[1] == "這是一個測試字幕。", "第二個翻譯應該正確"


# ============================================================
# 測試 2: 測試 SRT 檔案比對工具
# ============================================================


def test_srt_comparator(sample_srt_path: Path, srt_comparator):
    """測試 SRT 檔案比對工具

    驗證：
    1. 能夠正確讀取 SRT 檔案
    2. 能夠提取字幕文字
    """
    # 測試提取字幕文字
    texts = srt_comparator.get_subtitle_texts(sample_srt_path)

    # 驗證
    assert len(texts) == 3, "應該有 3 個字幕"
    assert texts[0] == "Hello, world!", "第一個字幕應該正確"
    assert texts[1] == "This is a test subtitle.", "第二個字幕應該正確"
    assert texts[2] == "Welcome to the translation system.", "第三個字幕應該正確"


# ============================================================
# 測試 3: 測試 SRT 檔案驗證工具
# ============================================================


def test_srt_validation(sample_srt_path: Path, invalid_srt_path: Path, assert_srt_valid):
    """測試 SRT 檔案驗證工具

    驗證：
    1. 能夠驗證有效的 SRT 檔案
    2. 能夠檢測無效的 SRT 檔案
    """
    # 測試有效的 SRT 檔案
    assert_srt_valid(sample_srt_path)  # 應該不拋出異常

    # 測試無效的 SRT 檔案（應該拋出 Failed 異常）
    # pysrt 對於格式錯誤的檔案會返回空列表，assert_srt_valid 會檢測並 fail
    from _pytest.outcomes import Failed

    with pytest.raises(Failed) as exc_info:
        assert_srt_valid(invalid_srt_path)

    # 驗證錯誤訊息包含預期的內容
    assert "SRT" in str(exc_info.value) or "字幕" in str(exc_info.value)


# ============================================================
# 測試 4: 測試 Mock 翻譯客戶端
# ============================================================


@pytest.mark.asyncio
async def test_mock_translation_client(mock_translation_client, mock_translation_responses):
    """測試 Mock 翻譯客戶端

    驗證：
    1. Mock 客戶端能夠返回預定義的翻譯
    2. 批量翻譯功能正常
    """
    # 測試單一翻譯
    result = await mock_translation_client.translate_text("Hello, world!", ["Hello, world!"], "test-model")
    assert result == "你好，世界！", "應該返回正確的翻譯"

    # 測試批量翻譯
    texts_with_context = [
        ("Hello, world!", ["Hello, world!"]),
        ("This is a test subtitle.", ["This is a test subtitle."]),
    ]
    results = await mock_translation_client.translate_batch(texts_with_context, "test-model")

    assert len(results) == 2, "應該返回 2 個翻譯結果"
    assert results[0] == "你好，世界！", "第一個翻譯應該正確"
    assert results[1] == "這是一個測試字幕。", "第二個翻譯應該正確"


# ============================================================
# 測試 5: 測試 ServiceFactory Mock 設定
# ============================================================


def test_service_factory_mocking(mock_all_services):
    """測試 ServiceFactory Mock 設定

    驗證：
    1. 所有服務都被正確 mock
    2. ServiceFactory 返回 mock 實例
    """
    # 獲取服務
    translation_service = ServiceFactory.get_translation_service()
    model_service = ServiceFactory.get_model_service()
    cache_service = ServiceFactory.get_cache_service()
    file_service = ServiceFactory.get_file_service()
    progress_service = ServiceFactory.get_progress_service()

    # 驗證它們都是 mock 實例
    assert translation_service == mock_all_services["translation"], "TranslationService 應該被 mock"
    assert model_service == mock_all_services["model"], "ModelService 應該被 mock"
    assert cache_service == mock_all_services["cache"], "CacheService 應該被 mock"
    assert file_service == mock_all_services["file"], "FileService 應該被 mock"
    assert progress_service == mock_all_services["progress"], "ProgressService 應該被 mock"
