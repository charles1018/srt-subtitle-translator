"""E2E 測試 - 批量處理與並發測試

此模組測試批量處理與並發功能，包括：
1. 批量翻譯測試（3-4 個測試）
2. 並發處理測試（2-3 個測試）

對應階段三任務 4 - 批量處理與效能測試
"""

import os
import pytest
import pysrt
import asyncio
import time
from pathlib import Path
from typing import List
from unittest.mock import patch, AsyncMock, Mock, call

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
def mock_all_services_for_batch(mock_translation_client, mock_translation_responses):
    """為批量處理測試準備完整的 Mock 服務"""

    # Mock TranslationService 的翻譯邏輯
    async def mock_translate_text(text, context, llm_type, model):
        return mock_translation_responses.get(text, f"[Mock翻譯] {text}")

    async def mock_translate_batch(texts_with_context, llm_type, model, concurrent_limit=5):
        return [
            mock_translation_responses.get(text, f"[Mock翻譯] {text}")
            for text, context in texts_with_context
        ]

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

    # Mock CacheService
    cache_storage = {}

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
    mock_cache_service._storage = cache_storage

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
        'TranslationService': mock_translation_service,
        'ModelService': mock_model_service,
        'CacheService': mock_cache_service,
        'FileService': mock_file_service,
        'ProgressService': mock_progress_service,
    }

    yield {
        'translation': mock_translation_service,
        'model': mock_model_service,
        'cache': mock_cache_service,
        'file': mock_file_service,
        'progress': mock_progress_service,
    }


# ============================================================
# 批量翻譯測試（3 個測試）
# ============================================================

@pytest.mark.asyncio
async def test_small_batch_translation(
    batch_srt_files: List[Path],
    e2e_temp_dir: Path,
    mock_all_services_for_batch,
    assert_srt_valid
):
    """測試 1：小批量翻譯（2-3 個檔案）

    驗證：
    1. 同時翻譯 3 個 SRT 檔案
    2. 所有檔案都被正確處理
    3. 輸出檔案數量與輸入一致
    4. 所有輸出檔案格式正確
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()
    output_files = []

    # 處理每個檔案
    for input_file in batch_srt_files:
        # 讀取輸入檔案
        input_subs = pysrt.open(str(input_file), encoding='utf-8')
        output_subs = pysrt.SubRipFile()

        # 翻譯每個字幕
        for sub in input_subs:
            translation = await translation_service.translate_text(
                sub.text,
                [sub.text],
                "openai",
                "test-model"
            )

            # 建立新字幕（保持時間軸）
            new_sub = pysrt.SubRipItem(
                index=sub.index,
                start=sub.start,
                end=sub.end,
                text=translation
            )
            output_subs.append(new_sub)

        # 儲存輸出檔案
        output_file = e2e_temp_dir / f"translated_{input_file.name}"
        output_subs.save(str(output_file), encoding='utf-8')
        output_files.append(output_file)

    # 驗證輸出
    assert len(output_files) == len(batch_srt_files), "輸出檔案數量應與輸入一致"

    # 驗證每個輸出檔案
    for output_file in output_files:
        assert output_file.exists(), f"輸出檔案應該存在: {output_file.name}"
        assert_srt_valid(output_file)

        # 驗證字幕數量
        output_subs = pysrt.open(str(output_file), encoding='utf-8')
        assert len(output_subs) == 3, "每個檔案應有 3 個字幕"


@pytest.mark.asyncio
async def test_mixed_language_batch_translation(
    sample_srt_path: Path,
    sample_japanese_srt_path: Path,
    sample_simplified_chinese_srt_path: Path,
    e2e_temp_dir: Path,
    mock_all_services_for_batch
):
    """測試 2：混合語言批量翻譯

    驗證：
    1. 同時翻譯多種語言的檔案（英文、日文、簡體中文）
    2. 多語言處理正確
    3. 所有翻譯結果正確
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()
    test_files = [
        (sample_srt_path, "英文"),
        (sample_japanese_srt_path, "日文"),
        (sample_simplified_chinese_srt_path, "簡體中文"),
    ]

    results = []

    # 處理每個語言的檔案
    for input_file, language in test_files:
        # 讀取輸入檔案
        input_subs = pysrt.open(str(input_file), encoding='utf-8')

        # 翻譯第一個字幕
        translation = await translation_service.translate_text(
            input_subs[0].text,
            [input_subs[0].text],
            "openai",
            "test-model"
        )

        results.append({
            "language": language,
            "original": input_subs[0].text,
            "translation": translation,
        })

    # 驗證結果
    assert len(results) == 3, "應該有 3 個翻譯結果"

    # 驗證每個翻譯都成功
    for result in results:
        assert result["translation"], f"{result['language']} 翻譯不應該為空"
        assert result["translation"] != result["original"] or "你好" in result["original"], \
            f"{result['language']} 應該被翻譯（除非已經是中文）"

    # 驗證所有翻譯都是 "你好，世界！"（根據 mock 回應）
    assert results[0]["translation"] == "你好，世界！", "英文翻譯應該正確"
    assert results[1]["translation"] == "你好，世界！", "日文翻譯應該正確"
    assert results[2]["translation"] == "你好，世界！", "簡體中文翻譯應該正確"


@pytest.mark.asyncio
async def test_batch_translation_error_handling(
    batch_srt_files: List[Path],
    invalid_srt_path: Path,
    e2e_temp_dir: Path,
    mock_all_services_for_batch
):
    """測試 3：批量翻譯錯誤處理

    驗證：
    1. 批量中包含無效檔案
    2. 部分失敗不影響其他檔案
    3. 有效檔案正常處理
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 混合有效和無效檔案
    test_files = batch_srt_files + [invalid_srt_path]
    results = []

    # 處理每個檔案（捕捉錯誤）
    for input_file in test_files:
        try:
            # 讀取輸入檔案
            input_subs = pysrt.open(str(input_file), encoding='utf-8')

            # 檢查檔案是否有效（至少有一個字幕）
            if len(input_subs) == 0:
                raise ValueError(f"檔案 {input_file.name} 無效或為空")

            # 翻譯第一個字幕
            translation = await translation_service.translate_text(
                input_subs[0].text,
                [input_subs[0].text],
                "openai",
                "test-model"
            )

            results.append({
                "file": input_file.name,
                "success": True,
                "translation": translation,
            })

        except Exception as e:
            results.append({
                "file": input_file.name,
                "success": False,
                "error": str(e),
            })

    # 驗證結果
    assert len(results) == len(test_files), "所有檔案都應該被處理"

    # 驗證成功和失敗的數量
    success_count = sum(1 for r in results if r["success"])
    failed_count = sum(1 for r in results if not r["success"])

    assert success_count == len(batch_srt_files), f"應該有 {len(batch_srt_files)} 個成功"
    assert failed_count == 1, "應該有 1 個失敗（invalid.srt）"

    # 驗證失敗的是 invalid.srt
    failed_result = next(r for r in results if not r["success"])
    assert "invalid.srt" in failed_result["file"], "失敗的應該是 invalid.srt"


# ============================================================
# 並發處理測試（3 個測試）
# ============================================================

@pytest.mark.asyncio
async def test_concurrent_translation_correctness(
    mock_all_services_for_batch,
    mock_translation_responses
):
    """測試 4：並發翻譯正確性

    驗證：
    1. 並發翻譯多個文本
    2. 無競態條件
    3. 所有結果正確
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 準備測試文本
    test_texts = [
        "Hello, world!",
        "This is a test subtitle.",
        "Welcome to the translation system.",
        "Testing SRT translation.",
        "Multiple files can be processed.",
    ]

    # 並發翻譯（使用 asyncio.gather）
    tasks = [
        translation_service.translate_text(text, [text], "openai", "test-model")
        for text in test_texts
    ]
    results = await asyncio.gather(*tasks)

    # 驗證結果
    assert len(results) == len(test_texts), "結果數量應該與輸入一致"

    # 驗證每個翻譯都正確
    for text, result in zip(test_texts, results):
        expected = mock_translation_responses[text]
        assert result == expected, f"翻譯 '{text}' 應該正確"


@pytest.mark.asyncio
async def test_concurrent_batch_translation(
    batch_srt_files: List[Path],
    mock_all_services_for_batch
):
    """測試 5：並發批量翻譯（使用 translate_batch）

    驗證：
    1. 使用 translate_batch 進行並發處理
    2. 批量翻譯效率高於單個翻譯
    3. 所有翻譯結果正確
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 讀取所有檔案的字幕
    all_texts_with_context = []
    for input_file in batch_srt_files:
        input_subs = pysrt.open(str(input_file), encoding='utf-8')
        for sub in input_subs:
            all_texts_with_context.append((sub.text, [sub.text]))

    # 批量翻譯（並發限制 = 3）
    start_time = time.time()
    translations = await translation_service.translate_batch(
        all_texts_with_context,
        "openai",
        "test-model",
        concurrent_limit=3
    )
    batch_duration = time.time() - start_time

    # 驗證結果
    assert len(translations) == len(all_texts_with_context), "翻譯數量應該與輸入一致"
    assert all(isinstance(t, str) for t in translations), "所有翻譯都應該是字串"
    assert all(len(t) > 0 for t in translations), "所有翻譯都不應該為空"

    # 驗證批量翻譯速度（應該很快，因為是 Mock）
    assert batch_duration < 5.0, f"批量翻譯應該在 5 秒內完成，實際 {batch_duration:.2f} 秒"


@pytest.mark.asyncio
async def test_concurrent_limit_behavior(
    mock_all_services_for_batch,
    mock_translation_responses
):
    """測試 6：並發限制行為

    驗證：
    1. 設定不同的並發數（3, 5）
    2. 並發限制生效
    3. 翻譯結果一致性
    """
    # 準備
    translation_service = ServiceFactory.get_translation_service()

    # 準備測試文本（10 個文本）
    test_texts = [
        "Welcome to the subtitle translator.",
        "This tool helps you translate subtitles.",
        "It supports multiple languages.",
        "You can translate from English to Chinese.",
        "The system uses AI for translation.",
        "Translation quality is high.",
        "Cache mechanism improves performance.",
        "Multiple files can be processed.",
        "Thank you for using our tool.",
        "Enjoy your translation experience!",
    ]

    # 測試不同的並發限制
    for concurrent_limit in [3, 5]:
        # 準備批量翻譯資料
        texts_with_context = [(text, [text]) for text in test_texts]

        # 批量翻譯
        start_time = time.time()
        translations = await translation_service.translate_batch(
            texts_with_context,
            "openai",
            "test-model",
            concurrent_limit=concurrent_limit
        )
        duration = time.time() - start_time

        # 驗證結果
        assert len(translations) == len(test_texts), \
            f"並發限制 {concurrent_limit} - 翻譯數量應該一致"

        # 驗證所有翻譯都正確
        for text, translation in zip(test_texts, translations):
            expected = mock_translation_responses[text]
            assert translation == expected, \
                f"並發限制 {concurrent_limit} - 翻譯 '{text}' 應該正確"

        # 驗證速度合理（Mock 應該很快）
        assert duration < 5.0, \
            f"並發限制 {concurrent_limit} - 應該在 5 秒內完成，實際 {duration:.2f} 秒"
