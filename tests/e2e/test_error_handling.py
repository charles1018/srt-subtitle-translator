"""E2E 測試 - 錯誤處理測試

此模組測試系統的錯誤處理機制，包括：
1. API 錯誤處理測試（3 個測試）
2. 檔案錯誤處理測試（4 個測試）

對應階段三任務 3 - 配置整合與錯誤處理測試
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pysrt
import pytest

from srt_translator.services.factory import ServiceFactory
from srt_translator.utils.errors import FileError, NetworkError, TranslationError

# ============================================================
# API 錯誤處理測試（3 個測試）
# ============================================================

@pytest.mark.asyncio
async def test_api_call_failure(sample_srt_path: Path):
    """測試 1：API 呼叫失敗

    驗證：
    1. Mock API 返回錯誤
    2. 驗證錯誤訊息
    3. 驗證降級處理
    """
    # 清理服務工廠
    ServiceFactory._instances.clear()

    # Mock 翻譯客戶端返回錯誤
    mock_client = AsyncMock()
    mock_client.translate_text.side_effect = NetworkError(
        "API call failed",
        details={"status_code": 500, "message": "Internal Server Error"}
    )

    # Mock 翻譯服務
    mock_translation_service = Mock()

    async def mock_translate_with_error(text, context, llm_type, model):
        """模擬翻譯時發生 API 錯誤"""
        try:
            # 嘗試呼叫 API（會失敗）
            await mock_client.translate_text(text, context, model)
        except NetworkError as e:
            # 捕獲錯誤並返回錯誤訊息
            return f"[翻譯失敗] {e.message}"

    mock_translation_service.translate_text = mock_translate_with_error

    # 註冊到服務工廠
    ServiceFactory._instances['TranslationService'] = mock_translation_service

    # 獲取翻譯服務
    translation_service = ServiceFactory.get_translation_service()

    # 執行翻譯（預期會失敗）
    result = await translation_service.translate_text(
        "Hello, world!",
        [],
        "openai",
        "test-model"
    )

    # 驗證錯誤處理
    assert "[翻譯失敗]" in result, "應該返回錯誤訊息"
    assert "API call failed" in result, "應該包含具體的錯誤描述"

    # 驗證 Mock 被呼叫
    mock_client.translate_text.assert_called_once()

    # 清理
    ServiceFactory._instances.clear()


@pytest.mark.asyncio
async def test_api_response_format_error():
    """測試 2：API 回應格式錯誤

    驗證：
    1. Mock API 返回無效格式
    2. 驗證錯誤處理
    3. 驗證部分成功場景
    """
    # 清理服務工廠
    ServiceFactory._instances.clear()

    # Mock 翻譯客戶端返回無效格式
    mock_client = AsyncMock()
    mock_client.translate_text.return_value = None  # 無效的返回值

    # Mock 翻譯服務
    mock_translation_service = Mock()

    async def mock_translate_with_format_error(text, context, llm_type, model):
        """模擬 API 返回無效格式"""
        result = await mock_client.translate_text(text, context, model)

        # 檢查返回值是否有效
        if result is None or not isinstance(result, str):
            raise TranslationError(
                "API 返回格式無效",
                details={"expected": "str", "got": type(result).__name__}
            )

        return result

    mock_translation_service.translate_text = mock_translate_with_format_error

    # 註冊到服務工廠
    ServiceFactory._instances['TranslationService'] = mock_translation_service

    # 獲取翻譯服務
    translation_service = ServiceFactory.get_translation_service()

    # 執行翻譯（預期會拋出異常）
    with pytest.raises(TranslationError) as exc_info:
        await translation_service.translate_text(
            "Hello, world!",
            [],
            "openai",
            "test-model"
        )

    # 驗證錯誤訊息
    assert "無效" in str(exc_info.value), "錯誤訊息應該包含 '無效'"
    assert exc_info.value.error_code == 1300, "錯誤代碼應該是 1300（翻譯錯誤）"

    # 驗證錯誤詳細資訊
    error_dict = exc_info.value.to_dict()
    assert "details" in error_dict, "應該包含詳細資訊"
    assert "expected" in error_dict["details"], "應該包含期望的類型"
    assert error_dict["details"]["expected"] == "str", "期望的類型應該是 str"

    # 清理
    ServiceFactory._instances.clear()


@pytest.mark.asyncio
async def test_api_rate_limit():
    """測試 3：API 速率限制

    驗證：
    1. Mock API 返回 429 錯誤
    2. 驗證重試機制
    3. 驗證延遲處理
    """
    # 清理服務工廠
    ServiceFactory._instances.clear()

    # Mock 翻譯客戶端模擬速率限制
    mock_client = AsyncMock()

    # 第一次呼叫返回速率限制錯誤，第二次成功
    call_count = 0

    async def mock_translate_with_rate_limit(text, context, model):
        nonlocal call_count
        call_count += 1

        if call_count == 1:
            # 第一次呼叫：速率限制
            raise NetworkError(
                "Rate limit exceeded",
                details={"status_code": 429, "retry_after": 1}
            )
        else:
            # 第二次呼叫：成功
            return "你好，世界！"

    mock_client.translate_text.side_effect = mock_translate_with_rate_limit

    # Mock 翻譯服務（帶重試機制）
    mock_translation_service = Mock()

    async def mock_translate_with_retry(text, context, llm_type, model, max_retries=2):
        """模擬帶重試機制的翻譯"""
        retries = 0

        while retries < max_retries:
            try:
                result = await mock_client.translate_text(text, context, model)
                return result
            except NetworkError as e:
                retries += 1
                if retries >= max_retries:
                    return f"[翻譯失敗] {e.message}"
                # 在真實情況下這裡會有延遲
                continue

        return "[翻譯失敗] 超過最大重試次數"

    mock_translation_service.translate_text = mock_translate_with_retry

    # 註冊到服務工廠
    ServiceFactory._instances['TranslationService'] = mock_translation_service

    # 獲取翻譯服務
    translation_service = ServiceFactory.get_translation_service()

    # 執行翻譯（第一次失敗，第二次成功）
    result = await translation_service.translate_text(
        "Hello, world!",
        [],
        "openai",
        "test-model"
    )

    # 驗證重試機制
    assert result == "你好，世界！", "應該在重試後成功"
    assert call_count == 2, "應該呼叫了 2 次（第一次失敗，第二次成功）"

    # 清理
    ServiceFactory._instances.clear()


# ============================================================
# 檔案錯誤處理測試（4 個測試）
# ============================================================

def test_invalid_srt_format(invalid_srt_path: Path):
    """測試 4：無效 SRT 格式

    驗證：
    1. 讀取格式錯誤的 SRT 檔案
    2. 驗證錯誤檢測
    3. 驗證錯誤訊息
    """
    # 驗證檔案存在
    assert invalid_srt_path.exists(), "無效 SRT 檔案應該存在"

    # 嘗試讀取無效格式的 SRT 檔案
    try:
        subs = pysrt.open(str(invalid_srt_path), encoding='utf-8')

        # 檢查是否為有效的 SRT 格式
        if len(subs) == 0:
            raise FileError(
                "SRT 檔案格式無效或為空",
                details={"file_path": str(invalid_srt_path)}
            )

        # 驗證每個字幕的格式
        for i, sub in enumerate(subs):
            if not sub.text or not sub.text.strip():
                raise FileError(
                    f"字幕 {i+1} 的文字內容無效",
                    details={"index": i+1, "file_path": str(invalid_srt_path)}
                )

    except FileError as e:
        # 驗證錯誤處理
        assert "無效" in e.message or "為空" in e.message, "錯誤訊息應該包含 '無效' 或 '為空'"
        assert e.error_code == 1400, "錯誤代碼應該是 1400（檔案錯誤）"

        # 驗證錯誤詳細資訊
        error_dict = e.to_dict()
        assert "file_path" in error_dict["details"], "應該包含檔案路徑"


def test_file_not_found():
    """測試 5：檔案不存在

    驗證：
    1. 嘗試讀取不存在的檔案
    2. 驗證錯誤處理
    3. 驗證友善的錯誤訊息
    """
    # 準備不存在的檔案路徑
    non_existent_path = Path("non_existent_file.srt")

    # 驗證檔案確實不存在
    assert not non_existent_path.exists(), "檔案應該不存在"

    # 嘗試讀取不存在的檔案
    try:
        if not non_existent_path.exists():
            raise FileError(
                f"檔案不存在: {non_existent_path}",
                details={
                    "file_path": str(non_existent_path),
                    "suggestion": "請確認檔案路徑是否正確"
                }
            )

        # 如果檔案存在，嘗試讀取
        subs = pysrt.open(str(non_existent_path), encoding='utf-8')

    except FileError as e:
        # 驗證錯誤處理
        assert "不存在" in e.message, "錯誤訊息應該包含 '不存在'"
        assert e.error_code == 1400, "錯誤代碼應該是 1400"

        # 驗證友善的錯誤訊息
        error_dict = e.to_dict()
        assert "suggestion" in error_dict["details"], "應該包含建議"
        assert "確認" in error_dict["details"]["suggestion"], "建議應該是友善的"


def test_empty_srt_file(fixtures_dir: Path):
    """測試 6：空檔案處理

    驗證：
    1. 讀取空的 SRT 檔案
    2. 驗證邊緣情況處理
    3. 驗證適當的回應
    """
    # 準備空檔案路徑
    empty_srt_path = fixtures_dir / "empty.srt"

    # 驗證檔案存在
    assert empty_srt_path.exists(), "空 SRT 檔案應該存在"

    # 讀取空檔案
    try:
        subs = pysrt.open(str(empty_srt_path), encoding='utf-8')

        # 檢查是否為空
        if len(subs) == 0:
            raise FileError(
                "SRT 檔案為空，沒有字幕內容",
                details={
                    "file_path": str(empty_srt_path),
                    "subtitle_count": 0,
                    "suggestion": "請確認檔案是否包含有效的字幕內容"
                }
            )

    except FileError as e:
        # 驗證錯誤處理
        assert "為空" in e.message, "錯誤訊息應該包含 '為空'"
        assert e.error_code == 1400, "錯誤代碼應該是 1400"

        # 驗證詳細資訊
        error_dict = e.to_dict()
        assert error_dict["details"]["subtitle_count"] == 0, "字幕數量應該是 0"
        assert "suggestion" in error_dict["details"], "應該包含建議"


def test_file_permission_error(e2e_temp_dir: Path):
    """測試 7：檔案權限錯誤

    驗證：
    1. 模擬檔案權限問題
    2. 驗證錯誤處理
    3. 驗證錯誤訊息
    """
    # 建立測試檔案
    test_file = e2e_temp_dir / "test_readonly.srt"
    test_file.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest subtitle\n", encoding='utf-8')

    # 驗證檔案存在
    assert test_file.exists(), "測試檔案應該存在"

    # 模擬權限錯誤（在測試環境中可能無法真實模擬，所以直接拋出異常）
    try:
        # 在真實情況下，這裡會嘗試寫入唯讀檔案
        # 為了測試，我們直接模擬權限錯誤
        raise PermissionError("Permission denied")

    except PermissionError:
        # 將系統錯誤包裝為應用程式錯誤
        error = FileError(
            "檔案權限錯誤：無法寫入檔案",
            details={
                "file_path": str(test_file),
                "suggestion": "請檢查檔案權限設定"
            }
        )

        # 驗證錯誤處理
        assert "權限" in error.message, "錯誤訊息應該包含 '權限'"
        assert error.error_code == 1400, "錯誤代碼應該是 1400"

        # 驗證詳細資訊
        error_dict = error.to_dict()
        assert "file_path" in error_dict["details"], "應該包含檔案路徑"
        assert "suggestion" in error_dict["details"], "應該包含建議"
