"""E2E 測試 - 翻譯流程測試

此模組測試完整的翻譯流程，包括：
1. 單檔案翻譯（3 個測試）
2. 快取機制驗證（2 個測試）
3. 多語言對測試（3 個測試）

對應階段三任務 2 - 基本翻譯流程測試
"""

from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pysrt
import pytest

from srt_translator.services.factory import ServiceFactory

# ============================================================
# 測試前準備：Mock 所有服務
# ============================================================


@pytest.fixture(autouse=True)
def reset_service_factory():
    """在每個測試前重置 ServiceFactory"""
    ServiceFactory._instances.clear()
    yield
    ServiceFactory._instances.clear()


@pytest.fixture
def mock_all_services_for_workflow(mock_translation_client, mock_translation_responses):
    """為翻譯流程測試準備完整的 Mock 服務"""

    # Mock TranslationService 的翻譯邏輯
    async def mock_translate_text(text, context, llm_type, model):
        return mock_translation_responses.get(text, f"[Mock翻譯] {text}")

    async def mock_translate_batch(texts_with_context, llm_type, model, concurrent_limit=5):
        return [mock_translation_responses.get(text, f"[Mock翻譯] {text}") for text, context in texts_with_context]

    # 建立 Mock TranslationService
    mock_translation_service = Mock()
    mock_translation_service.translate_text = AsyncMock(side_effect=mock_translate_text)
    mock_translation_service.translate_batch = AsyncMock(side_effect=mock_translate_batch)
    mock_translation_service.cleanup = Mock()
    mock_translation_service.stats = {
        "total_translations": 0,
        "cached_translations": 0,
        "failed_translations": 0,
    }

    # Mock ModelService
    mock_model_service = Mock()
    mock_model_service.get_translation_client = AsyncMock(return_value=mock_translation_client)
    mock_model_service.api_keys = {"openai": "test-key", "ollama": ""}
    mock_model_service.cleanup = AsyncMock()

    # Mock CacheService（可追蹤快取行為）
    cache_storage = {}  # 用於追蹤快取

    def mock_get_translation(source_text, context_texts, model_name):
        key = f"{source_text}:{model_name}"
        return cache_storage.get(key)

    def mock_store_translation(source_text, target_text, context_texts, model_name):
        key = f"{source_text}:{model_name}"
        cache_storage[key] = target_text
        return True

    mock_cache_service = Mock()
    mock_cache_service.get_translation = Mock(side_effect=mock_get_translation)
    mock_cache_service.store_translation = Mock(side_effect=mock_store_translation)
    mock_cache_service.cleanup = Mock()
    mock_cache_service._storage = cache_storage  # 暴露給測試檢查

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

    # 註冊到 ServiceFactory
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
# 單檔案翻譯測試（3 個測試）
# ============================================================


@pytest.mark.asyncio
async def test_single_file_translation_basic(
    sample_srt_path: Path, e2e_temp_dir: Path, mock_all_services_for_workflow, srt_comparator
):
    """測試 1：基本單檔案翻譯

    驗證：
    1. 能夠讀取 SRT 檔案
    2. 翻譯所有字幕
    3. 生成正確的輸出檔案
    """
    # 準備
    output_file = e2e_temp_dir / "output.srt"
    translation_service = ServiceFactory.get_translation_service()

    # 讀取輸入檔案
    input_subs = pysrt.open(str(sample_srt_path), encoding="utf-8")
    assert len(input_subs) == 3, "輸入檔案應有 3 個字幕"

    # 翻譯每個字幕
    translated_texts = []
    for sub in input_subs:
        translation = await translation_service.translate_text(sub.text, [sub.text], "openai", "test-model")
        translated_texts.append(translation)

    # 驗證翻譯結果
    assert len(translated_texts) == 3, "應該有 3 個翻譯結果"
    assert translated_texts[0] == "你好，世界！", "第一個翻譯應該正確"
    assert translated_texts[1] == "這是一個測試字幕。", "第二個翻譯應該正確"
    assert translated_texts[2] == "歡迎使用翻譯系統。", "第三個翻譯應該正確"


@pytest.mark.asyncio
async def test_single_file_translation_with_output(
    sample_srt_path: Path, e2e_temp_dir: Path, mock_all_services_for_workflow, assert_srt_valid
):
    """測試 2：單檔案翻譯並生成輸出檔案

    驗證：
    1. 翻譯流程正常
    2. 輸出檔案格式正確
    3. 時間軸保持不變
    """
    # 準備
    output_file = e2e_temp_dir / "translated.srt"
    translation_service = ServiceFactory.get_translation_service()

    # 讀取輸入檔案
    input_subs = pysrt.open(str(sample_srt_path), encoding="utf-8")
    output_subs = pysrt.SubRipFile()

    # 翻譯並建立輸出
    for sub in input_subs:
        translation = await translation_service.translate_text(sub.text, [sub.text], "openai", "test-model")

        # 建立新字幕（保持時間軸）
        new_sub = pysrt.SubRipItem(index=sub.index, start=sub.start, end=sub.end, text=translation)
        output_subs.append(new_sub)

    # 儲存輸出檔案
    output_subs.save(str(output_file), encoding="utf-8")

    # 驗證輸出檔案
    assert output_file.exists(), "輸出檔案應該存在"
    assert_srt_valid(output_file)

    # 驗證時間軸保持不變
    for i, (input_sub, output_sub) in enumerate(zip(input_subs, output_subs)):
        assert output_sub.start == input_sub.start, f"字幕 {i + 1} 開始時間應該相同"
        assert output_sub.end == input_sub.end, f"字幕 {i + 1} 結束時間應該相同"


@pytest.mark.asyncio
async def test_single_file_batch_translation(
    large_sample_srt_path: Path, e2e_temp_dir: Path, mock_all_services_for_workflow
):
    """測試 3：單檔案批量翻譯（較大檔案）

    驗證：
    1. 批量翻譯功能正常
    2. 能夠處理較多字幕（10 個）
    3. 翻譯結果完整
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 讀取輸入檔案
    input_subs = pysrt.open(str(large_sample_srt_path), encoding="utf-8")
    assert len(input_subs) == 10, "輸入檔案應有 10 個字幕"

    # 準備批量翻譯
    texts_with_context = [(sub.text, [sub.text]) for sub in input_subs]

    # 批量翻譯
    translations = await translation_service.translate_batch(
        texts_with_context, "openai", "test-model", concurrent_limit=3
    )

    # 驗證結果
    assert len(translations) == 10, "應該有 10 個翻譯結果"
    assert all(isinstance(t, str) for t in translations), "所有翻譯都應該是字串"
    assert all(len(t) > 0 for t in translations), "所有翻譯都不應該為空"

    # 驗證第一個和最後一個翻譯
    assert translations[0] == "歡迎使用字幕翻譯器。", "第一個翻譯應該正確"
    assert translations[9] == "享受您的翻譯體驗！", "最後一個翻譯應該正確"


# ============================================================
# 快取機制驗證測試（2 個測試）
# ============================================================


@pytest.mark.asyncio
async def test_cache_hit_scenario(sample_srt_path: Path, mock_all_services_for_workflow):
    """測試 4：快取命中場景

    驗證：
    1. 第一次翻譯：無快取，呼叫翻譯服務
    2. 第二次翻譯：快取命中，不呼叫翻譯服務
    3. 快取儲存與讀取正常
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()
    cache_service = ServiceFactory.get_cache_service()

    test_text = "Hello, world!"
    context = [test_text]
    model_name = "test-model"

    # 第一次翻譯（快取未命中）
    result1 = cache_service.get_translation(test_text, context, model_name)
    assert result1 is None, "第一次應該快取未命中"

    # 執行翻譯並儲存快取
    translation1 = await translation_service.translate_text(test_text, context, "openai", model_name)
    assert translation1 == "你好，世界！", "翻譯結果應該正確"

    # 儲存到快取
    cache_service.store_translation(test_text, translation1, context, model_name)

    # 第二次翻譯（快取命中）
    result2 = cache_service.get_translation(test_text, context, model_name)
    assert result2 == "你好，世界！", "第二次應該快取命中"
    assert result2 == translation1, "快取結果應該與第一次翻譯相同"


@pytest.mark.asyncio
async def test_cache_for_multiple_texts(mock_all_services_for_workflow):
    """測試 5：多個文本的快取

    驗證：
    1. 不同文本有獨立的快取
    2. 快取能夠區分不同的文本
    3. 快取儲存機制正常
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()
    cache_service = ServiceFactory.get_cache_service()

    model_name = "test-model"

    # 測試多個文本
    test_data = [
        ("Hello, world!", "你好，世界！"),
        ("This is a test subtitle.", "這是一個測試字幕。"),
        ("Welcome to the translation system.", "歡迎使用翻譯系統。"),
    ]

    # 第一輪：翻譯並儲存快取
    for text, expected_translation in test_data:
        translation = await translation_service.translate_text(text, [text], "openai", model_name)
        assert translation == expected_translation, f"翻譯 '{text}' 應該正確"
        cache_service.store_translation(text, translation, [text], model_name)

    # 第二輪：從快取讀取
    for text, expected_translation in test_data:
        cached = cache_service.get_translation(text, [text], model_name)
        assert cached == expected_translation, f"快取 '{text}' 應該正確"


# ============================================================
# 多語言對測試（3 個測試）
# ============================================================


@pytest.mark.asyncio
async def test_english_to_chinese_translation(sample_srt_path: Path, mock_all_services_for_workflow):
    """測試 6：英文 -> 繁體中文翻譯

    驗證：
    1. 英文到中文的翻譯正常
    2. 翻譯結果包含中文字符
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 讀取英文 SRT 檔案
    input_subs = pysrt.open(str(sample_srt_path), encoding="utf-8")

    # 翻譯第一個字幕
    translation = await translation_service.translate_text(
        input_subs[0].text, [input_subs[0].text], "openai", "test-model"
    )

    # 驗證翻譯結果
    assert translation == "你好，世界！", "英文到中文翻譯應該正確"

    # 驗證包含中文字符
    has_chinese = any("\u4e00" <= char <= "\u9fff" for char in translation)
    assert has_chinese, "翻譯結果應該包含中文字符"


@pytest.mark.asyncio
async def test_japanese_to_chinese_translation(sample_japanese_srt_path: Path, mock_all_services_for_workflow):
    """測試 7：日文 -> 繁體中文翻譯

    驗證：
    1. 日文到中文的翻譯正常
    2. 翻譯結果正確
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 讀取日文 SRT 檔案
    input_subs = pysrt.open(str(sample_japanese_srt_path), encoding="utf-8")
    assert len(input_subs) == 3, "日文檔案應有 3 個字幕"

    # 翻譯所有字幕
    translations = []
    for sub in input_subs:
        translation = await translation_service.translate_text(sub.text, [sub.text], "openai", "test-model")
        translations.append(translation)

    # 驗證翻譯結果
    assert translations[0] == "你好，世界！", "日文 '你好世界' 翻譯應該正確"
    assert translations[1] == "這是測試字幕。", "日文 '這是測試字幕' 翻譯應該正確"
    assert translations[2] == "歡迎使用翻譯系統。", "日文 '歡迎' 翻譯應該正確"


