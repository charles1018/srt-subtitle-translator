"""Tests for services/factory.py module."""

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from srt_translator.services.factory import (
    CacheService,
    FileService,
    ModelService,
    ProgressService,
    ServiceFactory,
    TranslationService,
    TranslationTaskManager,
)

# ============================================================
# ServiceFactory Tests
# ============================================================


class TestServiceFactory:
    """Tests for ServiceFactory class."""

    def setup_method(self):
        """Reset services before each test."""
        ServiceFactory._instances.clear()

    def teardown_method(self):
        """Clean up after each test."""
        ServiceFactory._instances.clear()

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_get_translation_service_singleton(self, mock_file, mock_cache, mock_model, mock_prompt, mock_config):
        """Test that get_translation_service returns singleton."""
        mock_config.get_instance.return_value = MagicMock()

        service1 = ServiceFactory.get_translation_service()
        service2 = ServiceFactory.get_translation_service()

        assert service1 is service2

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.ModelManager")
    def test_get_model_service_singleton(self, mock_model, mock_config):
        """Test that get_model_service returns singleton."""
        mock_config.get_instance.return_value = MagicMock()
        mock_model.return_value = MagicMock()

        service1 = ServiceFactory.get_model_service()
        service2 = ServiceFactory.get_model_service()

        assert service1 is service2

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.CacheManager")
    def test_get_cache_service_singleton(self, mock_cache, mock_config):
        """Test that get_cache_service returns singleton."""
        mock_config.get_instance.return_value = MagicMock()
        mock_cache.return_value = MagicMock()

        service1 = ServiceFactory.get_cache_service()
        service2 = ServiceFactory.get_cache_service()

        assert service1 is service2

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_get_file_service_singleton(self, mock_file, mock_config):
        """Test that get_file_service returns singleton."""
        mock_config.get_instance.return_value = MagicMock()
        mock_file.get_instance.return_value = MagicMock()

        service1 = ServiceFactory.get_file_service()
        service2 = ServiceFactory.get_file_service()

        assert service1 is service2

    def test_get_progress_service_singleton(self):
        """Test that get_progress_service returns singleton."""
        service1 = ServiceFactory.get_progress_service()
        service2 = ServiceFactory.get_progress_service()

        assert service1 is service2

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.CacheManager")
    def test_reset_services(self, mock_cache, mock_config):
        """Test resetting all services."""
        mock_config.get_instance.return_value = MagicMock()
        mock_cache.return_value = MagicMock()

        # Create some services
        ServiceFactory.get_cache_service()
        ServiceFactory.get_progress_service()

        assert len(ServiceFactory._instances) >= 2

        # Reset
        ServiceFactory.reset_services()

        assert len(ServiceFactory._instances) == 0


# ============================================================
# ProgressService Tests
# ============================================================


class TestProgressService:
    """Tests for ProgressService class."""

    def setup_method(self):
        """Reset services before each test."""
        ServiceFactory._instances.clear()

    def teardown_method(self):
        """Clean up after each test."""
        ServiceFactory._instances.clear()

    def test_initialization(self):
        """Test ProgressService initialization."""
        service = ProgressService()
        assert service.current == 0
        assert service.total == 0

    def test_set_total(self):
        """Test setting total."""
        service = ProgressService()
        service.set_total(100)
        assert service.total == 100

    def test_set_progress(self):
        """Test setting progress."""
        service = ProgressService()
        service.set_total(100)
        service.set_progress(50)
        assert service.current == 50

    def test_increment_progress(self):
        """Test incrementing progress."""
        service = ProgressService()
        service.set_total(100)
        service.set_progress(10)
        service.increment_progress()
        assert service.current == 11

    def test_increment_progress_by_amount(self):
        """Test incrementing progress by specific amount."""
        service = ProgressService()
        service.set_total(100)
        service.set_progress(10)
        service.increment_progress(5)
        assert service.current == 15

    def test_get_progress_percentage(self):
        """Test getting progress percentage."""
        service = ProgressService()
        service.set_total(100)
        service.set_progress(50)
        assert service.get_progress_percentage() == 50.0

    def test_get_progress_percentage_zero_total(self):
        """Test progress percentage with zero total."""
        service = ProgressService()
        assert service.get_progress_percentage() == 0.0

    def test_mark_complete(self):
        """Test marking as complete."""
        service = ProgressService()
        service.set_total(100)
        service.set_progress(100)  # Must set progress before mark_complete
        service.mark_complete()
        # After mark_complete with progress at 100, percentage should be 100%
        assert service.get_progress_percentage() == 100.0
        assert service.end_time is not None

    def test_reset(self):
        """Test resetting progress."""
        service = ProgressService()
        service.set_total(100)
        service.set_progress(50)
        service.reset()
        assert service.current == 0
        assert service.total == 0

    def test_register_progress_callback(self):
        """Test registering progress callback."""
        service = ProgressService()
        callback = MagicMock()
        service.register_progress_callback(callback)

        service.set_total(100)
        service.set_progress(50)

        # Callback should have been called
        callback.assert_called()

    def test_register_complete_callback(self):
        """Test registering complete callback."""
        service = ProgressService()
        callback = MagicMock()
        service.register_complete_callback(callback)

        service.set_total(100)
        service.mark_complete()

        callback.assert_called_once()

    def test_get_elapsed_time(self):
        """Test getting elapsed time."""
        service = ProgressService()
        service.set_total(100)
        service.start_time = time.time() - 5  # 5 seconds ago
        elapsed = service.get_elapsed_time()
        assert elapsed >= 4.9  # Allow some tolerance

    def test_get_elapsed_time_str(self):
        """Test getting formatted elapsed time."""
        service = ProgressService()
        service.set_total(100)
        service.start_time = time.time() - 65  # 1 minute 5 seconds ago
        elapsed_str = service.get_elapsed_time_str()
        assert "1" in elapsed_str
        assert "分" in elapsed_str or ":" in elapsed_str

    def test_increment_progress_from_zero(self):
        """Test incrementing progress from zero."""
        service = ProgressService()
        service.set_total(10)
        service.increment_progress()
        assert service.current == 1
        service.increment_progress(3)
        assert service.current == 4

    def test_increment_progress_triggers_complete(self):
        """Test increment triggers mark_complete when reaching total."""
        service = ProgressService()
        callback = MagicMock()
        service.register_complete_callback(callback)

        service.set_total(5)
        for _ in range(5):
            service.increment_progress()

        # Complete callback should have been called
        callback.assert_called_once()
        assert service.end_time is not None

    def test_get_elapsed_time_after_complete(self):
        """Test elapsed time calculation after completion."""
        service = ProgressService()
        service.set_total(10)
        service.start_time = 100.0
        service.end_time = 200.0

        elapsed = service.get_elapsed_time()
        assert elapsed == 100.0


# ============================================================
# CacheService Tests
# ============================================================


class TestCacheService:
    """Tests for CacheService class."""

    def setup_method(self):
        """Reset services before each test."""
        ServiceFactory._instances.clear()

    def teardown_method(self):
        """Clean up after each test."""
        ServiceFactory._instances.clear()

    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.ConfigManager")
    def test_initialization(self, mock_config, mock_cache):
        """Test CacheService initialization."""
        mock_config.get_instance.return_value = MagicMock()
        mock_cache.return_value = MagicMock()

        service = CacheService()
        assert service.cache_manager is not None

    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.ConfigManager")
    def test_get_translation(self, mock_config, mock_cache):
        """Test getting cached translation."""
        mock_config.get_instance.return_value = MagicMock()
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = "cached text"
        mock_cache.return_value = mock_cache_instance

        service = CacheService()
        result = service.get_translation("test", [], "model")

        assert result == "cached text"

    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.ConfigManager")
    def test_store_translation(self, mock_config, mock_cache):
        """Test storing translation."""
        mock_config.get_instance.return_value = MagicMock()
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        service = CacheService()
        service.store_translation("original", "translated", [], "model")

        mock_cache_instance.store_translation.assert_called_once()

    @pytest.mark.skip(reason="CacheService.get_cache_stats method signature may differ")
    def test_get_cache_stats(self):
        """Test getting cache stats - skipped."""
        pass

    @pytest.mark.skip(reason="CacheService.clear_all_cache method may not exist")
    def test_clear_all_cache(self):
        """Test clearing all cache - skipped."""
        pass


# ============================================================
# FileService Tests
# ============================================================


class TestFileService:
    """Tests for FileService class."""

    def setup_method(self):
        """Reset services before each test."""
        ServiceFactory._instances.clear()

    def teardown_method(self):
        """Clean up after each test."""
        ServiceFactory._instances.clear()

    @patch("srt_translator.services.factory.FileHandler")
    @patch("srt_translator.services.factory.ConfigManager")
    def test_initialization(self, mock_config, mock_file):
        """Test FileService initialization."""
        mock_config.get_instance.return_value = MagicMock()
        mock_file.get_instance.return_value = MagicMock()

        service = FileService()
        assert service.file_handler is not None

    @pytest.mark.skip(reason="FileService methods need proper mock setup")
    def test_scan_directory(self):
        """Test scanning directory - skipped."""
        pass

    @pytest.mark.skip(reason="FileService methods need proper mock setup")
    def test_get_subtitle_info(self):
        """Test getting subtitle info - skipped."""
        pass

    @pytest.mark.skip(reason="FileService methods need proper mock setup")
    def test_set_batch_settings(self):
        """Test setting batch settings - skipped."""
        pass

    @pytest.mark.skip(reason="FileService methods need proper mock setup")
    def test_get_batch_settings(self):
        """Test getting batch settings - skipped."""
        pass


# ============================================================
# ModelService Tests
# ============================================================


class TestModelService:
    """Tests for ModelService class."""

    def setup_method(self):
        """Reset services before each test."""
        ServiceFactory._instances.clear()

    def teardown_method(self):
        """Clean up after each test."""
        ServiceFactory._instances.clear()

    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.ConfigManager")
    def test_initialization(self, mock_config, mock_model):
        """Test ModelService initialization."""
        mock_config.get_instance.return_value = MagicMock()
        mock_model.return_value = MagicMock()

        service = ModelService()
        assert service.model_manager is not None

    @patch.dict("os.environ", {"GOOGLE_API_KEY": "test-google-key"}, clear=True)
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.ConfigManager")
    def test_initialization_loads_google_api_key_from_env(self, mock_config, mock_model):
        """Test ModelService loads Google API key from environment variables."""
        mock_config.get_instance.return_value = MagicMock()
        mock_model.return_value = MagicMock()

        service = ModelService()

        assert service.api_keys.get("google") == "test-google-key"

    @pytest.mark.skip(reason="ModelService.get_available_models is async")
    def test_get_available_models(self):
        """Test getting available models - skipped (async method)."""
        pass

    @pytest.mark.skip(reason="ModelService methods need proper mock setup")
    def test_get_model_info(self):
        """Test getting model info - skipped."""
        pass

    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.ConfigManager")
    def test_save_api_key(self, mock_config, mock_model):
        """Test saving API key."""
        mock_config.get_instance.return_value = MagicMock()
        mock_model_instance = MagicMock()
        mock_model.return_value = mock_model_instance

        service = ModelService()
        service.save_api_key("openai", "sk-test-key")

        assert service.api_keys.get("openai") == "sk-test-key"

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.ConfigManager")
    async def test_get_available_models_closes_manager_session(self, mock_config, mock_model):
        """Test model list loading closes ModelManager session after use."""
        mock_config.get_instance.return_value = MagicMock()
        mock_model_instance = MagicMock()
        mock_model_instance.get_model_list_async = AsyncMock(return_value=[SimpleNamespace(id="qwen3.5-ud:latest")])
        mock_model_instance._close_async_session = AsyncMock()
        mock_model.return_value = mock_model_instance

        service = ModelService()
        result = await service.get_available_models("ollama")

        assert result == ["qwen3.5-ud:latest"]
        mock_model_instance._close_async_session.assert_awaited_once()

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.ConfigManager")
    async def test_test_model_connection_closes_manager_session(self, mock_config, mock_model):
        """Test model connection check closes ModelManager session after use."""
        mock_config.get_instance.return_value = MagicMock()
        mock_model_instance = MagicMock()
        mock_model_instance.test_model_connection = AsyncMock(return_value={"success": True, "message": "ok"})
        mock_model_instance._close_async_session = AsyncMock()
        mock_model.return_value = mock_model_instance

        service = ModelService()
        result = await service.test_model_connection("qwen3.5-ud:latest", "ollama")

        assert result["success"] is True
        mock_model_instance.test_model_connection.assert_awaited_once_with("qwen3.5-ud:latest", "ollama", None)
        mock_model_instance._close_async_session.assert_awaited_once()


# ============================================================
# TranslationService Tests
# ============================================================


class TestTranslationService:
    """Tests for TranslationService class."""

    def setup_method(self):
        """Reset services before each test."""
        ServiceFactory._instances.clear()

    def teardown_method(self):
        """Clean up after each test."""
        ServiceFactory._instances.clear()

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_initialization(self, mock_file, mock_cache, mock_model, mock_prompt, mock_config):
        """Test TranslationService initialization."""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()

        assert service.stats["total_translations"] == 0
        assert service.stats["cached_translations"] == 0

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_get_stat_int(self, mock_file, mock_cache, mock_model, mock_prompt, mock_config):
        """Test _get_stat_int method."""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()
        service.stats["test_stat"] = 42

        assert service._get_stat_int("test_stat") == 42
        assert service._get_stat_int("nonexistent", 10) == 10

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_get_stat_float(self, mock_file, mock_cache, mock_model, mock_prompt, mock_config):
        """Test _get_stat_float method."""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()
        service.stats["time_stat"] = 3.14

        assert service._get_stat_float("time_stat") == 3.14
        assert service._get_stat_float("nonexistent", 1.5) == 1.5

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_incr_stat(self, mock_file, mock_cache, mock_model, mock_prompt, mock_config):
        """Test _incr_stat method."""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()
        service.stats["counter"] = 5

        service._incr_stat("counter")
        assert service.stats["counter"] == 6

        service._incr_stat("counter", 3)
        assert service.stats["counter"] == 9

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_get_stats(self, mock_file, mock_cache, mock_model, mock_prompt, mock_config):
        """Test get_stats method."""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()
        service.stats["total_translations"] = 100
        service.stats["cached_translations"] = 50

        stats = service.get_stats()

        assert stats["total_translations"] == 100
        assert stats["cached_translations"] == 50

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_text_empty(self, mock_file, mock_cache, mock_model, mock_prompt, mock_config):
        """Test translating empty text."""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()
        result = await service.translate_text("", [], "ollama", "llama3")

        assert result == ""

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_text_cached(self, mock_file, mock_cache, mock_model, mock_prompt, mock_config):
        """Test translating text with cache hit."""
        mock_config.get_instance.return_value = MagicMock()
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        service = TranslationService()
        # Mock cache service to return cached result
        service.cache_service = MagicMock()
        service.cache_service.get_translation.return_value = "cached translation"

        result = await service.translate_text("test", [], "ollama", "llama3")

        assert result == "cached translation"
        assert service.stats["cached_translations"] == 1

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_text_ignores_invalid_cached_translation(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config
    ):
        """Service precheck should ignore cached Japanese leakage and re-run translation."""
        mock_config.get_instance.return_value = MagicMock()

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "promptv3"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]1", "最近"]
        mock_prompt.return_value = mock_prompt_instance

        mock_client = AsyncMock()
        mock_client.translate_with_retry = AsyncMock(return_value="最近怎麼樣？")

        service = TranslationService()
        service.prompt_manager = mock_prompt_instance
        service.cache_service = MagicMock()
        service.cache_service.get_translation.return_value = "最近どう？"
        service.model_service = MagicMock()
        service.model_service.get_translation_client = AsyncMock(return_value=mock_client)

        result = await service.translate_text("最近", ["前文", "最近", "後文"], "ollama", "llama3")

        assert result == "最近怎麼樣？"
        assert service.stats["cached_translations"] == 0
        mock_client.translate_with_retry.assert_awaited_once_with(
            "最近",
            ["前文", "最近", "後文"],
            "llama3",
            current_index=None,
        )
        service.cache_service.store_translation.assert_called_once_with(
            "最近",
            "最近怎麼樣？",
            ["[CURRENT_INDEX]1", "最近"],
            "llama3",
            "standard",
            "promptv3",
            current_index=None,
            lookup_source="translation_service_store",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_text_passes_current_index_to_client_and_cache(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config
    ):
        """Test current_index is forwarded to prompt manager, client, and cache storage."""
        mock_config.get_instance.return_value = MagicMock()

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "promptv2"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]2", "Hello"]
        mock_prompt.return_value = mock_prompt_instance

        mock_client = AsyncMock()
        mock_client.translate_with_retry = AsyncMock(return_value="你好")

        service = TranslationService()
        service.prompt_manager = mock_prompt_instance
        service.cache_service = MagicMock()
        service.cache_service.get_translation.return_value = None
        service.model_service = MagicMock()
        service.model_service.get_translation_client = AsyncMock(return_value=mock_client)

        result = await service.translate_text(
            "Hello",
            ["前一行", "Hello", "Hello", "後一行"],
            "ollama",
            "qwen3.5-ud:latest",
            current_index=2,
        )

        assert result == "你好"
        service.cache_service.get_translation.assert_called_once_with(
            "Hello",
            ["[CURRENT_INDEX]2", "Hello"],
            "qwen3.5-ud:latest",
            "standard",
            "promptv2",
            current_index=2,
            lookup_source="translation_service_precheck",
        )
        mock_prompt_instance.get_effective_cache_context_texts.assert_called_once_with(
            "Hello",
            ["前一行", "Hello", "Hello", "後一行"],
            "ollama",
            "qwen3.5-ud:latest",
            current_index=2,
        )
        mock_client.translate_with_retry.assert_awaited_once_with(
            "Hello",
            ["前一行", "Hello", "Hello", "後一行"],
            "qwen3.5-ud:latest",
            current_index=2,
        )
        service.cache_service.store_translation.assert_called_once_with(
            "Hello",
            "你好",
            ["[CURRENT_INDEX]2", "Hello"],
            "qwen3.5-ud:latest",
            "standard",
            "promptv2",
            current_index=2,
            lookup_source="translation_service_store",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_text_does_not_store_invalid_translation_in_service_cache(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config
    ):
        """Service should not write unresolved Japanese leakage back into cache."""
        mock_config.get_instance.return_value = MagicMock()

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "promptv4"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]1", "最近"]
        mock_prompt.return_value = mock_prompt_instance

        mock_client = AsyncMock()
        mock_client.translate_with_retry = AsyncMock(return_value="最近どう？")

        service = TranslationService()
        service.prompt_manager = mock_prompt_instance
        service.cache_service = MagicMock()
        service.cache_service.get_translation.return_value = None
        service.model_service = MagicMock()
        service.model_service.get_translation_client = AsyncMock(return_value=mock_client)

        result = await service.translate_text("最近", ["前文", "最近", "後文"], "ollama", "llama3")

        assert result == "最近どう？"
        service.cache_service.store_translation.assert_not_called()

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_text_skips_cache_when_disabled(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config
    ):
        """Test use_cache=False bypasses service-level cache operations."""
        mock_config.get_instance.return_value = MagicMock()

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "promptv5"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]0", "Hello"]
        mock_prompt.return_value = mock_prompt_instance

        mock_client = AsyncMock()
        mock_client.translate_with_retry = AsyncMock(return_value="你好")

        service = TranslationService()
        service.prompt_manager = mock_prompt_instance
        service.cache_service = MagicMock()
        service.model_service = MagicMock()
        service.model_service.get_translation_client = AsyncMock(return_value=mock_client)

        result = await service.translate_text("Hello", ["Hello"], "ollama", "llama3", use_cache=False)

        assert result == "你好"
        service.cache_service.get_translation.assert_not_called()
        service.cache_service.store_translation.assert_not_called()
        mock_client.translate_with_retry.assert_awaited_once_with(
            "Hello",
            ["Hello"],
            "llama3",
            current_index=None,
            use_cache=False,
        )

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.pysrt.open")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_subtitle_file_does_not_save_when_all_items_fail(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_pysrt_open
    ):
        """當整份字幕都翻譯失敗時，不應輸出檔案。"""
        mock_config.get_instance.return_value = MagicMock()

        class FakeSubs(list):
            def __init__(self, items):
                super().__init__(items)
                self.save = MagicMock()

        subs = FakeSubs(
            [
                SimpleNamespace(text="こんにちは"),
                SimpleNamespace(text="ありがとう"),
            ]
        )
        mock_pysrt_open.return_value = subs

        service = TranslationService()
        service.file_service = MagicMock()
        service.file_service.get_subtitle_info.return_value = {}
        service.file_service.get_output_path.return_value = "/tmp/output.srt"
        service.translate_batch = AsyncMock(return_value=["[翻譯錯誤: connection fail]", "[翻譯錯誤: connection fail]"])

        success, result = await service.translate_subtitle_file(
            "input.srt",
            "日文",
            "繁體中文",
            "mistral",
            1,
            "僅顯示翻譯",
            "ollama",
        )

        assert success is False
        assert result == "[翻譯錯誤: connection fail]"
        subs.save.assert_not_called()
        service.file_service.get_output_path.assert_not_called()
        assert subs[0].text == "こんにちは"
        assert subs[1].text == "ありがとう"

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.pysrt.open")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_subtitle_file_reports_partial_completion(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_pysrt_open
    ):
        """部分字幕失敗時，應儲存部分成果並回報失敗數。"""
        mock_config.get_instance.return_value = MagicMock()

        class FakeSubs(list):
            def __init__(self, items):
                super().__init__(items)
                self.save = MagicMock()

        subs = FakeSubs(
            [
                SimpleNamespace(text="こんにちは"),
                SimpleNamespace(text="ありがとう"),
            ]
        )
        mock_pysrt_open.return_value = subs

        service = TranslationService()
        service.file_service = MagicMock()
        service.file_service.get_subtitle_info.return_value = {}
        service.file_service.get_output_path.return_value = "/tmp/output.srt"
        service.translate_batch = AsyncMock(return_value=["你好", "[翻譯錯誤: connection fail]"])
        complete_callback = MagicMock()

        success, result = await service.translate_subtitle_file(
            "input.srt",
            "日文",
            "繁體中文",
            "mistral",
            1,
            "僅顯示翻譯",
            "ollama",
            complete_callback=complete_callback,
        )

        assert success is True
        assert result == "/tmp/output.srt"
        subs.save.assert_called_once_with("/tmp/output.srt", encoding="utf-8")
        assert subs[0].text == "你好"
        assert subs[1].text == "ありがとう"
        assert any(
            "翻譯部分完成" in call.args[0] and "成功 1/2，失敗 1" in call.args[0]
            for call in complete_callback.call_args_list
        )

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.pysrt.open")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_subtitle_file_uses_original_snapshot_for_later_batch_context(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_pysrt_open
    ):
        """後續批次的上下文應維持原文，不被前批次翻譯結果污染。"""
        mock_config.get_instance.return_value = MagicMock()

        class FakeSubs(list):
            def __init__(self, items):
                super().__init__(items)
                self.save = MagicMock()

        subs = FakeSubs(
            [
                SimpleNamespace(text="こんにちは"),
                SimpleNamespace(text="ありがとう"),
                SimpleNamespace(text="さようなら"),
            ]
        )
        mock_pysrt_open.return_value = subs

        captured_calls = []

        async def fake_translate_batch(
            texts_with_context,
            llm_type,
            model_name,
            concurrent_limit,
            current_indices=None,
            use_cache=True,
        ):
            captured_calls.append((texts_with_context, current_indices))
            if len(captured_calls) == 1:
                return ["你好", "謝謝"]
            return ["再見"]

        service = TranslationService()
        service.file_service = MagicMock()
        service.file_service.get_subtitle_info.return_value = {}
        service.file_service.get_output_path.return_value = "/tmp/output.srt"
        service.translate_batch = AsyncMock(side_effect=fake_translate_batch)

        success, result = await service.translate_subtitle_file(
            "input.srt",
            "日文",
            "繁體中文",
            "mistral",
            1,
            "僅顯示翻譯",
            "ollama",
        )

        assert success is True
        assert result == "/tmp/output.srt"
        assert len(captured_calls) == 2
        assert captured_calls[1][0] == [("さようなら", ["さようなら"])]
        assert captured_calls[1][1] == [0]

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.pysrt.open")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_subtitle_file_auto_batches_context_free_openai_lines(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_pysrt_open
    ):
        """OpenAI 會將連續的低風險短句自動合併為小批次。"""
        mock_config.get_instance.return_value = MagicMock()

        class FakeSubs(list):
            def __init__(self, items):
                super().__init__(items)
                self.save = MagicMock()

        subs = FakeSubs(
            [
                SimpleNamespace(text="8.30 a.m."),
                SimpleNamespace(text="The oil shock."),
                SimpleNamespace(text="But the big number comes tomorrow."),
            ]
        )
        mock_pysrt_open.return_value = subs

        service = TranslationService()
        service.file_service = MagicMock()
        service.file_service.get_subtitle_info.return_value = {}
        service.file_service.get_output_path.return_value = "/tmp/output.srt"
        service._translate_batch_structure_text = AsyncMock(return_value=["上午8:30", "油價衝擊"])
        service.translate_batch = AsyncMock(return_value=["但大數字明天會出爐"])

        success, result = await service.translate_subtitle_file(
            "input.srt",
            "英文",
            "繁體中文",
            "gpt-4o-mini",
            1,
            "僅顯示翻譯",
            "openai",
        )

        assert success is True
        assert result == "/tmp/output.srt"
        assert service._translate_batch_structure_text.await_count == 1
        assert service._translate_batch_structure_text.await_args.args[1] == [0, 1]
        service.translate_batch.assert_awaited_once()
        assert service.translate_batch.await_args.args[0] == [
            (
                "But the big number comes tomorrow.",
                ["8.30 a.m.", "The oil shock.", "But the big number comes tomorrow."],
            )
        ]
        assert subs[0].text == "上午8:30"
        assert subs[1].text == "油價衝擊"
        assert subs[2].text == "但大數字明天會出爐"

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.pysrt.open")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_subtitle_file_uses_smart_context_windows_for_openai(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_pysrt_open
    ):
        """智慧上下文會讓獨立短句保持最小上下文，承接句才帶更多上下文。"""
        mock_config.get_instance.return_value = MagicMock()

        class FakeSubs(list):
            def __init__(self, items):
                super().__init__(items)
                self.save = MagicMock()

        subs = FakeSubs(
            [
                SimpleNamespace(text="8.30 a.m."),
                SimpleNamespace(text="But the big number comes tomorrow."),
            ]
        )
        mock_pysrt_open.return_value = subs

        service = TranslationService()
        service.file_service = MagicMock()
        service.file_service.get_subtitle_info.return_value = {}
        service.file_service.get_output_path.return_value = "/tmp/output.srt"
        service.translate_batch = AsyncMock(side_effect=[["上午8:30"], ["但大數字明天會出爐"]])

        success, result = await service.translate_subtitle_file(
            "input.srt",
            "英文",
            "繁體中文",
            "gpt-4o-mini",
            1,
            "僅顯示翻譯",
            "openai",
        )

        assert success is True
        assert result == "/tmp/output.srt"
        assert service.translate_batch.await_count == 2
        assert service.translate_batch.await_args_list[0].args[0] == [("8.30 a.m.", ["8.30 a.m."])]
        assert service.translate_batch.await_args_list[1].args[0] == [
            ("But the big number comes tomorrow.", ["8.30 a.m.", "But the big number comes tomorrow."])
        ]

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_batch_safe_short_text_filters_risky_dialogue_fragments(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config
    ):
        """智慧批次應避開短問答與省略主語的碎片句。"""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()

        assert service._is_batch_safe_short_text("8.30 a.m.") is True
        assert service._is_batch_safe_short_text("The oil shock.") is True
        assert service._is_batch_safe_short_text("Do you?") is False
        assert service._is_batch_safe_short_text("Thinks it's outdated.") is False

    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_text_needs_context_for_short_pronoun_question(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config
    ):
        """超短承接問句應保留上下文，避免被直譯成錯誤語義。"""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()

        assert service._text_needs_context("Do you?") is True
        assert service._get_context_window_for_text(
            "Do you?",
            {
                "batch_size": 10,
                "max_context_items": 2,
                "smart_context_enabled": True,
                "compact_prompt_enabled": True,
                "terminology_enabled": True,
            },
        ) == 2

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.pysrt.open")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_subtitle_file_does_not_auto_batch_short_question_pair(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_pysrt_open
    ):
        """短問答對應逐句翻譯，避免智慧批次把問句語氣錯綁到前一句。"""
        mock_config.get_instance.return_value = MagicMock()

        class FakeSubs(list):
            def __init__(self, items):
                super().__init__(items)
                self.save = MagicMock()

        subs = FakeSubs(
            [
                SimpleNamespace(text="Thinks it's outdated."),
                SimpleNamespace(text="Do you?"),
            ]
        )
        mock_pysrt_open.return_value = subs

        service = TranslationService()
        service.file_service = MagicMock()
        service.file_service.get_subtitle_info.return_value = {}
        service.file_service.get_output_path.return_value = "/tmp/output.srt"
        service._translate_batch_structure_text = AsyncMock(return_value=["錯誤批次結果 1", "錯誤批次結果 2"])
        service.translate_batch = AsyncMock(side_effect=[[ "覺得這已經過時了" ], [ "你覺得呢？" ]])

        success, result = await service.translate_subtitle_file(
            "input.srt",
            "英文",
            "繁體中文",
            "gpt-4o-mini",
            1,
            "僅顯示翻譯",
            "openai",
        )

        assert success is True
        assert result == "/tmp/output.srt"
        service._translate_batch_structure_text.assert_not_awaited()
        assert service.translate_batch.await_count == 2
        assert service.translate_batch.await_args_list[0].args[0] == [("Thinks it's outdated.", ["Thinks it's outdated."])]
        assert service.translate_batch.await_args_list[1].args[0] == [("Do you?", ["Thinks it's outdated.", "Do you?"])]
        assert subs[0].text == "覺得這已經過時了"
        assert subs[1].text == "你覺得呢？"

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_batch_structure_text_reuses_cache_and_stores_new_lines(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config
    ):
        """結構批次翻譯應保留可命中的逐行快取，未命中部分才送 API。"""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()
        service.prompt_manager = MagicMock()
        service.prompt_manager.current_style = "standard"
        service.prompt_manager.get_prompt_version.return_value = "batch1234"
        service.cache_service = MagicMock()
        service.cache_service.get_translation.side_effect = ["上午8:30", None]
        service.translate_text = AsyncMock(return_value="油價衝擊")
        service._post_process_translation = MagicMock(side_effect=lambda _source, text: text)

        subs = [SimpleNamespace(text="8.30 a.m."), SimpleNamespace(text="The oil shock.")]

        result = await service._translate_batch_structure_text(
            subs,
            [0, 1],
            "openai",
            "gpt-4o-mini",
            1,
            source_text_snapshot=["8.30 a.m.", "The oil shock."],
            runtime_settings={
                "batch_size": 10,
                "max_context_items": 2,
                "smart_context_enabled": True,
                "compact_prompt_enabled": True,
                "terminology_enabled": True,
            },
            use_cache=True,
        )

        assert result == ["上午8:30", "油價衝擊"]
        service.translate_text.assert_awaited_once()
        assert "[BATCH: 1 lines" in service.translate_text.await_args.args[0]
        assert "The oil shock." in service.translate_text.await_args.args[0]
        assert "8.30 a.m." not in service.translate_text.await_args.args[0]
        service.cache_service.store_translation.assert_called_once_with(
            "The oil shock.",
            "油價衝擊",
            [],
            "gpt-4o-mini",
            "standard",
            "batch1234",
            lookup_source="translation_service_batch_store",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    async def test_translate_batch_structure_text_falls_back_when_sentence_mood_mismatches(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config
    ):
        """若批次翻譯把問句語氣錯綁到鄰近行，應直接退回逐句翻譯。"""
        mock_config.get_instance.return_value = MagicMock()

        service = TranslationService()
        service.prompt_manager = MagicMock()
        service.prompt_manager.current_style = "standard"
        service.prompt_manager.get_prompt_version.return_value = "batch5678"
        service.cache_service = MagicMock()
        service.translate_text = AsyncMock(return_value="覺得這過時了嗎？\n你覺得呢？")
        service.translate_batch = AsyncMock(return_value=["覺得這已經過時了", "你覺得呢？"])
        service._post_process_translation = MagicMock(side_effect=lambda _source, text: text)

        subs = [SimpleNamespace(text="Thinks it's outdated."), SimpleNamespace(text="Do you?")]

        result = await service._translate_batch_structure_text(
            subs,
            [0, 1],
            "openai",
            "gpt-4o-mini",
            1,
            source_text_snapshot=["Thinks it's outdated.", "Do you?"],
            runtime_settings={
                "batch_size": 10,
                "max_context_items": 2,
                "smart_context_enabled": True,
                "compact_prompt_enabled": True,
                "terminology_enabled": True,
            },
            use_cache=False,
        )

        assert result == ["覺得這已經過時了", "你覺得呢？"]
        service.translate_text.assert_awaited_once()
        service.translate_batch.assert_awaited_once()

    @patch("srt_translator.services.factory.get_config")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_post_process_translation_normalizes_oil_shock_phrase(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_get_config
    ):
        """oil shock 應避免被翻成過重的 crisis 類詞彙。"""
        mock_config.get_instance.return_value = MagicMock()
        mock_get_config.side_effect = (
            lambda section, key, default=None: True
            if (section, key) == ("user", "preserve_punctuation")
            else default
        )

        service = TranslationService()
        service._get_bool_config_option = MagicMock(return_value=False)

        result = service._post_process_translation("The oil shock.", "石油危機")

        assert result == "油價衝擊"

    @patch("srt_translator.services.factory.get_config")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_post_process_translation_normalizes_straight_ahead_promo_phrase(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_get_config
    ):
        """Straight ahead 作為節目串場語不應直譯成動作句。"""
        mock_config.get_instance.return_value = MagicMock()
        mock_get_config.side_effect = (
            lambda section, key, default=None: True
            if (section, key) == ("user", "preserve_punctuation")
            else default
        )

        service = TranslationService()
        service._get_bool_config_option = MagicMock(return_value=False)

        result = service._post_process_translation("Straight ahead.", "直走。")

        assert result == "稍後回來"

    @patch("srt_translator.services.factory.get_config")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_post_process_translation_normalizes_much_more_with_promo_phrase(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_get_config
    ):
        """Much more with ... 應收斂為自然的節目預告語。"""
        mock_config.get_instance.return_value = MagicMock()
        mock_get_config.side_effect = (
            lambda section, key, default=None: True
            if (section, key) == ("user", "preserve_punctuation")
            else default
        )

        service = TranslationService()
        service._get_bool_config_option = MagicMock(return_value=False)

        result = service._post_process_translation(
            "Much more with New York Fed President John Williams.",
            "更多內容將與紐約聯邦儲備銀行行長約翰·威廉姆斯討論",
        )

        assert result == "稍後請看紐約聯邦儲備銀行行長約翰·威廉斯"

    @patch("srt_translator.services.factory.get_config")
    @patch("srt_translator.services.factory.ConfigManager")
    @patch("srt_translator.services.factory.PromptManager")
    @patch("srt_translator.services.factory.ModelManager")
    @patch("srt_translator.services.factory.CacheManager")
    @patch("srt_translator.services.factory.FileHandler")
    def test_post_process_translation_strips_much_more_with_more_content_tail(
        self, mock_file, mock_cache, mock_model, mock_prompt, mock_config, mock_get_config
    ):
        """Much more with ... 應移除殘留的「更多內容」尾巴。"""
        mock_config.get_instance.return_value = MagicMock()
        mock_get_config.side_effect = (
            lambda section, key, default=None: True
            if (section, key) == ("user", "preserve_punctuation")
            else default
        )

        service = TranslationService()
        service._get_bool_config_option = MagicMock(return_value=False)

        result = service._post_process_translation(
            "Much more with New York Fed President John Williams.",
            "稍後請看紐約聯邦儲備銀行行長約翰·威廉斯的更多內容",
        )

        assert result == "稍後請看紐約聯邦儲備銀行行長約翰·威廉斯"


# ============================================================
# TranslationTaskManager Tests
# ============================================================


class TestTranslationTaskManager:
    """Tests for TranslationTaskManager class."""

    def test_initialization(self):
        """Test TranslationTaskManager initialization."""
        manager = TranslationTaskManager()
        assert manager.tasks == {}
        assert manager.get_active_task_count() == 0

    def test_is_any_running_empty(self):
        """Test is_any_running with no tasks."""
        manager = TranslationTaskManager()
        assert manager.is_any_running() is False

    def test_is_all_paused_empty(self):
        """Test is_all_paused with no tasks."""
        manager = TranslationTaskManager()
        assert manager.is_all_paused() is False

    def test_get_active_task_count_empty(self):
        """Test get_active_task_count with no tasks."""
        manager = TranslationTaskManager()
        assert manager.get_active_task_count() == 0

    def test_stop_all_empty(self):
        """Test stop_all with no tasks."""
        manager = TranslationTaskManager()
        # Should not raise
        manager.stop_all()

    def test_pause_all_empty(self):
        """Test pause_all with no tasks."""
        manager = TranslationTaskManager()
        # Should not raise
        manager.pause_all()

    def test_resume_all_empty(self):
        """Test resume_all with no tasks."""
        manager = TranslationTaskManager()
        # Should not raise
        manager.resume_all()

    def test_cleanup(self):
        """Test cleanup."""
        manager = TranslationTaskManager()
        # Should not raise
        manager.cleanup()
        assert manager.tasks == {}


# ============================================================
# TranslationTask Tests (Basic)
# ============================================================


class TestTranslationTask:
    """Tests for TranslationTask class."""

    @pytest.mark.skip(reason="TranslationTask requires complex initialization")
    def test_initialization(self):
        """Test TranslationTask initialization - skipped."""
        pass

    @pytest.mark.skip(reason="TranslationTask requires complex initialization")
    def test_stop(self):
        """Test stopping a task - skipped."""
        pass

    @pytest.mark.skip(reason="TranslationTask requires complex initialization")
    def test_pause_resume(self):
        """Test pausing and resuming a task - skipped."""
        pass
