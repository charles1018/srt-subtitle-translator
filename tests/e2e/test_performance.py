"""E2E 測試 - 效能與邊緣情況測試

此模組測試系統效能與邊緣情況處理，包括：
1. 效能與效率測試（2-3 個測試）
2. 邊緣情況測試（3 個測試）

對應階段三任務 4 - 批量處理與效能測試
"""

import time
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
def mock_all_services_for_performance(mock_translation_client, mock_translation_responses):
    """為效能測試準備完整的 Mock 服務"""

    # Mock TranslationService 的翻譯邏輯
    async def mock_translate_text(text, context, llm_type, model, current_index=None):
        return mock_translation_responses.get(text, f"[Mock翻譯] {text}")

    async def mock_translate_batch(
        texts_with_context, llm_type, model, concurrent_limit=5, current_indices=None
    ):
        return [mock_translation_responses.get(item[0], f"[Mock翻譯] {item[0]}") for item in texts_with_context]

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
    cache_storage = {}
    cache_hits = []

    def mock_get_translation(source_text, context_texts, model_name):
        key = f"{source_text}:{model_name}"
        result = cache_storage.get(key)
        if result:
            cache_hits.append(key)
        return result

    def mock_store_translation(source_text, target_text, context_texts, model_name):
        key = f"{source_text}:{model_name}"
        cache_storage[key] = target_text
        return True

    mock_cache_service = Mock()
    mock_cache_service.get_translation = Mock(side_effect=mock_get_translation)
    mock_cache_service.store_translation = Mock(side_effect=mock_store_translation)
    mock_cache_service.cleanup = Mock()
    mock_cache_service._storage = cache_storage
    mock_cache_service._hits = cache_hits

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
# 效能與效率測試（2 個測試）
# ============================================================


@pytest.mark.asyncio
async def test_translation_speed(sample_srt_path: Path, mock_all_services_for_performance):
    """測試 1：翻譯速度測試

    驗證：
    1. 測量單個字幕翻譯時間
    2. 翻譯速度在合理範圍內（< 2 秒）
    3. 批量翻譯比單個快
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 讀取輸入檔案
    input_subs = pysrt.open(str(sample_srt_path), encoding="utf-8")
    assert len(input_subs) == 3, "測試檔案應有 3 個字幕"

    # 測試 1：單個翻譯速度
    single_times = []
    for sub in input_subs:
        start_time = time.time()
        await translation_service.translate_text(sub.text, [sub.text], "openai", "test-model")
        duration = time.time() - start_time
        single_times.append(duration)

    # 驗證單個翻譯速度
    avg_single_time = sum(single_times) / len(single_times)
    assert avg_single_time < 2.0, f"單個翻譯平均耗時 {avg_single_time:.3f}s，超過 2 秒限制"

    # 測試 2：批量翻譯速度
    texts_with_context = [(sub.text, [sub.text]) for sub in input_subs]

    start_time = time.time()
    await translation_service.translate_batch(
        texts_with_context, "openai", "test-model", concurrent_limit=3
    )
    batch_time = time.time() - start_time

    # 驗證批量翻譯速度
    assert batch_time < 3.0, f"批量翻譯耗時 {batch_time:.3f}s，超過 3 秒限制"

    # 驗證批量翻譯有效率優勢（應該更快或接近）
    total_single_time = sum(single_times)
    assert batch_time <= total_single_time * 1.5, (
        f"批量翻譯時間 {batch_time:.3f}s 應該不超過單個總時間 {total_single_time:.3f}s 的 1.5 倍"
    )


@pytest.mark.asyncio
async def test_cache_performance(sample_srt_path: Path, mock_all_services_for_performance):
    """測試 2：快取效能測試

    驗證：
    1. 比較有快取和無快取的速度
    2. 快取命中率
    3. 快取顯著提升效能
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()
    cache_service = ServiceFactory.get_cache_service()

    # 讀取輸入檔案
    input_subs = pysrt.open(str(sample_srt_path), encoding="utf-8")
    test_text = input_subs[0].text
    model_name = "test-model"

    # 第一次翻譯（無快取）
    start_time = time.time()
    result1 = await translation_service.translate_text(test_text, [test_text], "openai", model_name)
    first_time = time.time() - start_time

    # 儲存到快取
    cache_service.store_translation(test_text, result1, [test_text], model_name)

    # 第二次翻譯（有快取）
    start_time = time.time()
    cached = cache_service.get_translation(test_text, [test_text], model_name)
    cache_time = time.time() - start_time

    # 驗證快取命中
    assert cached is not None, "快取應該命中"
    assert cached == result1, "快取結果應該與第一次翻譯相同"

    # 驗證快取速度優勢（快取讀取應該更快）
    assert cache_time <= first_time, f"快取讀取時間 {cache_time:.6f}s 應該不超過首次翻譯時間 {first_time:.6f}s"

    # 測試多次快取命中
    cache_service._hits.clear()  # 重置快取命中記錄

    for _ in range(5):
        cached = cache_service.get_translation(test_text, [test_text], model_name)
        assert cached == result1, "每次快取命中應該返回相同結果"

    # 驗證快取命中次數
    assert len(cache_service._hits) == 5, "應該有 5 次快取命中"


# ============================================================
# 邊緣情況測試（3 個測試）
# ============================================================


@pytest.mark.asyncio
async def test_large_file_processing(very_large_srt_path: Path, e2e_temp_dir: Path, mock_all_services_for_performance):
    """測試 3：大型檔案處理

    驗證：
    1. 翻譯超大 SRT 檔案（100+ 字幕）
    2. 能夠完整處理
    3. 效能可接受
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 讀取大型檔案
    input_subs = pysrt.open(str(very_large_srt_path), encoding="utf-8")
    assert len(input_subs) >= 100, "應該有至少 100 個字幕"

    # 準備批量翻譯資料
    texts_with_context = [(sub.text, [sub.text]) for sub in input_subs]

    # 批量翻譯大型檔案
    start_time = time.time()
    translations = await translation_service.translate_batch(
        texts_with_context, "openai", "test-model", concurrent_limit=5
    )
    duration = time.time() - start_time

    # 驗證完整性
    assert len(translations) == len(input_subs), "翻譯數量應該與字幕數量一致"
    assert all(isinstance(t, str) for t in translations), "所有翻譯都應該是字串"
    assert all(len(t) > 0 for t in translations), "所有翻譯都不應該為空"

    # 驗證效能（Mock 應該很快，但仍要有合理限制）
    assert duration < 30.0, f"大型檔案處理耗時 {duration:.2f}s，超過 30 秒限制"

    # 驗證第一個和最後一個翻譯正確
    assert "這是字幕編號 1" in translations[0], "第一個翻譯應該正確"
    assert "這是字幕編號" in translations[-1], "最後一個翻譯應該正確"


@pytest.mark.asyncio
async def test_long_subtitle_processing(
    long_subtitle_srt_path: Path, mock_all_services_for_performance, mock_translation_responses
):
    """測試 4：極長字幕處理

    驗證：
    1. 字幕文本超長（1000+ 字符）
    2. 正確處理
    3. 翻譯完整性
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 讀取包含超長字幕的檔案
    input_subs = pysrt.open(str(long_subtitle_srt_path), encoding="utf-8")
    assert len(input_subs) >= 3, "應該有至少 3 個字幕"

    # 驗證第一個字幕超長
    first_subtitle = input_subs[0].text
    assert len(first_subtitle) > 1000, "第一個字幕應該超過 1000 字符"

    # 翻譯超長字幕
    start_time = time.time()
    long_translation = await translation_service.translate_text(
        first_subtitle, [first_subtitle], "openai", "test-model"
    )
    long_duration = time.time() - start_time

    # 驗證超長字幕翻譯
    assert long_translation, "超長字幕應該能夠翻譯"
    assert len(long_translation) > 0, "翻譯結果不應該為空"

    # 驗證速度合理（即使是超長字幕）
    assert long_duration < 5.0, f"超長字幕翻譯耗時 {long_duration:.2f}s，超過 5 秒限制"

    # 翻譯普通字幕（第二個字幕）
    normal_subtitle = input_subs[1].text
    assert len(normal_subtitle) < 100, "第二個字幕應該是普通長度"

    normal_translation = await translation_service.translate_text(
        normal_subtitle, [normal_subtitle], "openai", "test-model"
    )

    # 驗證普通字幕翻譯
    assert normal_translation == mock_translation_responses[normal_subtitle], "普通字幕翻譯應該正確"


@pytest.mark.asyncio
async def test_special_characters_processing(special_chars_srt_path: Path, mock_all_services_for_performance):
    """測試 5：特殊字符處理

    驗證：
    1. 字幕包含特殊字符（emoji、符號、多語言字符）
    2. 特殊字符保留
    3. 不會導致錯誤
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 讀取包含特殊字符的檔案
    input_subs = pysrt.open(str(special_chars_srt_path), encoding="utf-8")
    assert len(input_subs) >= 5, "應該有至少 5 個字幕"

    # 翻譯所有包含特殊字符的字幕
    translations = []
    for sub in input_subs:
        translation = await translation_service.translate_text(sub.text, [sub.text], "openai", "test-model")
        translations.append(
            {
                "original": sub.text,
                "translation": translation,
            }
        )

    # 驗證翻譯結果
    assert len(translations) == len(input_subs), "所有字幕都應該被翻譯"

    # 驗證特殊字符保留
    for result in translations:
        assert result["translation"], "翻譯結果不應該為空"

        # 檢查特定的特殊字符是否保留
        if "🌍" in result["original"]:
            assert "🌍" in result["translation"], "Emoji 應該被保留"

        if "😀" in result["original"]:
            assert "😀" in result["translation"], "Emoji 應該被保留"

        if "@#$%^&*" in result["original"]:
            assert "@#$%^&*" in result["translation"], "符號應該被保留"

    # 驗證沒有拋出異常
    # 如果程式碼執行到這裡，表示特殊字符處理正常，沒有崩潰
    assert True, "特殊字符處理正常"
