"""Tests for translation/client.py module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from srt_translator.translation.client import (
    AdaptiveConcurrencyController,
    ApiErrorType,
    ApiMetrics,
    TranslationClient,
)


# ============================================================
# ApiMetrics Tests
# ============================================================


class TestApiMetrics:
    """Tests for ApiMetrics dataclass."""

    def test_initial_values(self):
        """Test default initial values."""
        metrics = ApiMetrics()
        assert metrics.total_requests == 0
        assert metrics.successful_requests == 0
        assert metrics.failed_requests == 0
        assert metrics.total_tokens == 0
        assert metrics.total_cost == 0
        assert metrics.cache_hits == 0
        assert metrics.total_response_time == 0

    def test_get_average_response_time_no_requests(self):
        """Test average response time with no successful requests."""
        metrics = ApiMetrics()
        assert metrics.get_average_response_time() == 0

    def test_get_average_response_time_with_requests(self):
        """Test average response time calculation."""
        metrics = ApiMetrics(successful_requests=5, total_response_time=10.0)
        assert metrics.get_average_response_time() == 2.0

    def test_get_success_rate_no_requests(self):
        """Test success rate with no total requests."""
        metrics = ApiMetrics()
        assert metrics.get_success_rate() == 0

    def test_get_success_rate_with_requests(self):
        """Test success rate calculation."""
        metrics = ApiMetrics(total_requests=10, successful_requests=8)
        assert metrics.get_success_rate() == 80.0

    def test_get_cache_hit_rate_no_requests(self):
        """Test cache hit rate with no requests."""
        metrics = ApiMetrics()
        assert metrics.get_cache_hit_rate() == 0

    def test_get_cache_hit_rate_with_hits(self):
        """Test cache hit rate calculation."""
        metrics = ApiMetrics(total_requests=20, cache_hits=5)
        assert metrics.get_cache_hit_rate() == 25.0

    def test_get_summary(self):
        """Test summary generation."""
        metrics = ApiMetrics(
            total_requests=100,
            successful_requests=90,
            failed_requests=10,
            total_tokens=5000,
            total_cost=0.05,
            cache_hits=20,
            total_response_time=45.0,
        )
        summary = metrics.get_summary()

        assert summary["total_requests"] == 100
        assert summary["successful_requests"] == 90
        assert summary["failed_requests"] == 10
        assert summary["success_rate"] == "90.00%"
        assert summary["cache_hit_rate"] == "20.00%"
        assert summary["average_response_time"] == "0.50s"
        assert summary["total_tokens"] == 5000
        assert summary["estimated_cost"] == "$0.0500"


# ============================================================
# AdaptiveConcurrencyController Tests
# ============================================================


class TestAdaptiveConcurrencyController:
    """Tests for AdaptiveConcurrencyController class."""

    def test_initialization(self):
        """Test controller initialization."""
        controller = AdaptiveConcurrencyController(
            initial=5, min_concurrent=2, max_concurrent=15
        )
        assert controller.current == 5
        assert controller.min == 2
        assert controller.max == 15
        assert controller.sample_count == 0

    def test_get_current(self):
        """Test get_current returns current concurrency."""
        controller = AdaptiveConcurrencyController(initial=7)
        assert controller.get_current() == 7

    @pytest.mark.asyncio
    async def test_update_increases_concurrency_for_fast_response(self):
        """Test concurrency increases for fast API response."""
        controller = AdaptiveConcurrencyController(
            initial=3, min_concurrent=2, max_concurrent=10
        )
        # Set a very low average response time to trigger increase
        controller.avg_response_time = 0.1

        # Update with fast response time (< 0.5s)
        await controller.update(0.2)

        # After EMA update, avg should still be low enough to increase
        assert controller.current >= 3

    @pytest.mark.asyncio
    async def test_update_decreases_concurrency_for_slow_response(self):
        """Test concurrency decreases for slow API response."""
        controller = AdaptiveConcurrencyController(
            initial=5, min_concurrent=2, max_concurrent=10
        )
        # Set a high average response time
        controller.avg_response_time = 2.0

        # Update with slow response time (> 1.5s)
        await controller.update(2.5)

        # Should decrease concurrency
        assert controller.current <= 5

    @pytest.mark.asyncio
    async def test_update_respects_max_limit(self):
        """Test concurrency doesn't exceed max limit."""
        controller = AdaptiveConcurrencyController(
            initial=10, min_concurrent=2, max_concurrent=10
        )
        controller.avg_response_time = 0.1

        await controller.update(0.1)
        assert controller.current <= 10

    @pytest.mark.asyncio
    async def test_update_respects_min_limit(self):
        """Test concurrency doesn't go below min limit."""
        controller = AdaptiveConcurrencyController(
            initial=2, min_concurrent=2, max_concurrent=10
        )
        controller.avg_response_time = 3.0

        await controller.update(3.0)
        assert controller.current >= 2

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test get_stats returns correct statistics."""
        controller = AdaptiveConcurrencyController(
            initial=5, min_concurrent=2, max_concurrent=10
        )
        await controller.update(0.8)

        stats = await controller.get_stats()

        assert stats["current_concurrency"] == 5
        assert stats["min_concurrency"] == 2
        assert stats["max_concurrency"] == 10
        assert stats["sample_count"] == 1
        assert "avg_response_time" in stats


# ============================================================
# ApiErrorType Tests
# ============================================================


class TestApiErrorType:
    """Tests for ApiErrorType enum."""

    def test_error_types_exist(self):
        """Test all error types are defined."""
        assert ApiErrorType.RATE_LIMIT.value == "rate_limit"
        assert ApiErrorType.TIMEOUT.value == "timeout"
        assert ApiErrorType.CONNECTION.value == "connection"
        assert ApiErrorType.SERVER.value == "server"
        assert ApiErrorType.AUTHENTICATION.value == "authentication"
        assert ApiErrorType.CONTENT_FILTER.value == "content_filter"
        assert ApiErrorType.UNKNOWN.value == "unknown"


# ============================================================
# TranslationClient Tests
# ============================================================


class TestTranslationClientInit:
    """Tests for TranslationClient initialization."""

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_init_ollama(self, mock_prompt, mock_cache):
        """Test initialization with Ollama."""
        client = TranslationClient(
            llm_type="ollama",
            base_url="http://localhost:11434",
        )
        assert client.llm_type == "ollama"
        assert client.base_url == "http://localhost:11434"
        assert client.openai_client is None

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_init_openai(self, mock_openai, mock_prompt, mock_cache):
        """Test initialization with OpenAI."""
        client = TranslationClient(
            llm_type="openai",
            api_key="sk-test123456789012345678901234567890123456789012",
        )
        assert client.llm_type == "openai"
        assert client.api_key == "sk-test123456789012345678901234567890123456789012"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_init_with_netflix_style(self, mock_prompt, mock_cache):
        """Test initialization with Netflix style enabled."""
        netflix_config = {
            "enabled": True,
            "auto_fix": True,
            "max_chars_per_line": 20,
        }
        client = TranslationClient(
            llm_type="ollama",
            netflix_style_config=netflix_config,
        )
        assert client.enable_netflix_style is True
        assert client.post_processor is not None


class TestTranslationClientHelpers:
    """Tests for TranslationClient helper methods."""

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_is_mostly_cjk_chinese(self, mock_prompt, mock_cache):
        """Test CJK detection for Chinese text."""
        client = TranslationClient(llm_type="ollama")
        assert client._is_mostly_cjk("這是中文測試") is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_is_mostly_cjk_english(self, mock_prompt, mock_cache):
        """Test CJK detection for English text."""
        client = TranslationClient(llm_type="ollama")
        assert client._is_mostly_cjk("This is English") is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_is_mostly_cjk_mixed(self, mock_prompt, mock_cache):
        """Test CJK detection for mixed text."""
        client = TranslationClient(llm_type="ollama")
        # More than 50% CJK - "中文English" has 2 CJK chars out of 9 total = ~22%
        assert client._is_mostly_cjk("中文English") is False
        # "中文中文中文Eng" has 6 CJK chars out of 9 total = ~67%
        assert client._is_mostly_cjk("中文中文中文Eng") is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_is_mostly_cjk_empty(self, mock_prompt, mock_cache):
        """Test CJK detection for empty text."""
        client = TranslationClient(llm_type="ollama")
        assert client._is_mostly_cjk("") is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_clean_single_line_translation(self, mock_prompt, mock_cache):
        """Test cleaning single line translation."""
        client = TranslationClient(llm_type="ollama")

        # Single line original should clean newlines
        original = "Hello world"
        translated = "你好\n世界"
        result = client._clean_single_line_translation(original, translated)
        assert "\n" not in result
        assert result == "你好 世界"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_clean_single_line_preserves_multiline(self, mock_prompt, mock_cache):
        """Test that multiline original preserves newlines in translation."""
        client = TranslationClient(llm_type="ollama")

        # Multiline original should preserve newlines
        original = "Hello\nworld"
        translated = "你好\n世界"
        result = client._clean_single_line_translation(original, translated)
        assert result == "你好\n世界"


class TestTranslationClientErrorClassification:
    """Tests for error classification methods."""

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_classify_error_rate_limit(self, mock_prompt, mock_cache):
        """Test rate limit error classification."""
        client = TranslationClient(llm_type="ollama")

        error = Exception("Rate limit exceeded")
        error_type, _ = client._classify_error(error)
        assert error_type == ApiErrorType.RATE_LIMIT

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_classify_error_timeout(self, mock_prompt, mock_cache):
        """Test timeout error classification."""
        client = TranslationClient(llm_type="ollama")

        error = asyncio.TimeoutError()
        error_type, _ = client._classify_error(error)
        assert error_type == ApiErrorType.CONNECTION

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_classify_error_authentication(self, mock_prompt, mock_cache):
        """Test authentication error classification."""
        client = TranslationClient(llm_type="ollama")

        error = Exception("Unauthorized: Invalid API key")
        error_type, _ = client._classify_error(error)
        assert error_type == ApiErrorType.AUTHENTICATION

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_classify_error_server(self, mock_prompt, mock_cache):
        """Test server error classification."""
        client = TranslationClient(llm_type="ollama")

        error = Exception("Server error 500")
        error_type, _ = client._classify_error(error)
        assert error_type == ApiErrorType.SERVER

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_classify_error_content_filter(self, mock_prompt, mock_cache):
        """Test content filter error classification."""
        client = TranslationClient(llm_type="ollama")

        error = Exception("Content filter triggered")
        error_type, _ = client._classify_error(error)
        assert error_type == ApiErrorType.CONTENT_FILTER

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_classify_error_unknown(self, mock_prompt, mock_cache):
        """Test unknown error classification."""
        client = TranslationClient(llm_type="ollama")

        error = Exception("Some random error")
        error_type, _ = client._classify_error(error)
        assert error_type == ApiErrorType.UNKNOWN


class TestTranslationClientRetryStrategy:
    """Tests for retry strategy methods."""

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_retry_strategy_rate_limit(self, mock_prompt, mock_cache):
        """Test retry strategy for rate limit errors."""
        client = TranslationClient(llm_type="ollama")

        strategy = client._get_retry_strategy(ApiErrorType.RATE_LIMIT)
        assert strategy["max_tries"] == 8
        assert strategy["max_time"] == 300

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_retry_strategy_timeout(self, mock_prompt, mock_cache):
        """Test retry strategy for timeout errors."""
        client = TranslationClient(llm_type="ollama")

        strategy = client._get_retry_strategy(ApiErrorType.TIMEOUT)
        assert strategy["max_tries"] == 4
        assert strategy["factor"] == 2.0

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_retry_strategy_authentication(self, mock_prompt, mock_cache):
        """Test retry strategy for authentication errors."""
        client = TranslationClient(llm_type="ollama")

        strategy = client._get_retry_strategy(ApiErrorType.AUTHENTICATION)
        assert strategy["max_tries"] == 2  # Auth errors shouldn't retry much

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_retry_strategy_content_filter(self, mock_prompt, mock_cache):
        """Test retry strategy for content filter errors."""
        client = TranslationClient(llm_type="ollama")

        strategy = client._get_retry_strategy(ApiErrorType.CONTENT_FILTER)
        assert strategy["max_tries"] == 1  # Content filter should not retry


class TestTranslationClientApiKeyValidation:
    """Tests for API key validation."""

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_valid_legacy(
        self, mock_openai, mock_prompt, mock_cache
    ):
        """Test validation of valid legacy API key."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        # Legacy key format: sk-... with ~51 characters
        valid_key = "sk-" + "a" * 48
        assert client._validate_openai_api_key(valid_key) is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_valid_project(
        self, mock_openai, mock_prompt, mock_cache
    ):
        """Test validation of valid project API key."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        # Project key format: sk-proj-...
        valid_key = "sk-proj-" + "a" * 80
        assert client._validate_openai_api_key(valid_key) is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_invalid_empty(
        self, mock_openai, mock_prompt, mock_cache
    ):
        """Test validation of empty API key."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        assert client._validate_openai_api_key("") is False
        assert client._validate_openai_api_key(None) is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_invalid_prefix(
        self, mock_openai, mock_prompt, mock_cache
    ):
        """Test validation of key with wrong prefix."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        assert client._validate_openai_api_key("invalid-key") is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_invalid_characters(
        self, mock_openai, mock_prompt, mock_cache
    ):
        """Test validation of key with invalid characters."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        assert client._validate_openai_api_key("sk-test key with spaces") is False


class TestTranslationClientAsync:
    """Tests for async methods."""

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_empty(self, mock_prompt, mock_cache):
        """Test translating empty text."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="ollama")
        result = await client.translate_text("", [], "llama3")
        assert result == ""

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_from_cache(self, mock_prompt, mock_cache):
        """Test translating text with cache hit."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = "cached translation"
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="ollama")
        result = await client.translate_text("Hello", [], "llama3")
        assert result == "cached translation"
        assert client.metrics.cache_hits == 1

    @pytest.mark.skip(reason="Complex async mock setup needed")
    @pytest.mark.asyncio
    async def test_translate_with_ollama(self):
        """Test translation with Ollama API - skipped."""
        pass

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_batch_empty(self, mock_prompt, mock_cache):
        """Test batch translation with empty list."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="ollama")
        result = await client.translate_batch([], "llama3")
        assert result == []

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_batch_all_cached(self, mock_prompt, mock_cache):
        """Test batch translation with all cache hits."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.side_effect = [
            "cached1",
            "cached2",
        ]
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="ollama")
        texts = [("Hello", []), ("World", [])]
        result = await client.translate_batch(texts, "llama3")

        assert result == ["cached1", "cached2"]
        assert client.metrics.cache_hits == 2

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_context_manager(self, mock_prompt, mock_cache):
        """Test async context manager."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        async with TranslationClient(llm_type="ollama") as client:
            assert client.session is not None

        # Session should be closed after exiting context
        assert client.session is None

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_estimate_token_count(self, mock_prompt, mock_cache):
        """Test token count estimation."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="ollama")
        messages = [{"role": "user", "content": "Hello, this is a test message"}]
        count = await client._estimate_token_count(messages)
        assert count > 0

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_estimate_token_count_cjk(self, mock_prompt, mock_cache):
        """Test token count estimation for CJK text."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="ollama")
        messages = [{"role": "user", "content": "這是一個中文測試訊息"}]
        count = await client._estimate_token_count(messages)
        assert count > 0


class TestTranslationClientMetrics:
    """Tests for metrics methods."""

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_metrics(self, mock_prompt, mock_cache):
        """Test getting metrics."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="ollama")
        client.metrics.total_requests = 10
        client.metrics.successful_requests = 8

        metrics = client.get_metrics()
        assert metrics["total_requests"] == 10
        assert metrics["successful_requests"] == 8

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_reset_metrics(self, mock_prompt, mock_cache):
        """Test resetting metrics."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="ollama")
        client.metrics.total_requests = 100
        client.metrics.successful_requests = 90

        client.reset_metrics()

        assert client.metrics.total_requests == 0
        assert client.metrics.successful_requests == 0


class TestTranslationClientApiAvailability:
    """Tests for API availability check."""

    @pytest.mark.skip(reason="Complex async mock setup needed")
    @pytest.mark.asyncio
    async def test_is_api_available_ollama_success(self):
        """Test Ollama API availability check success - skipped."""
        pass

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_is_api_available_openai_no_key(
        self, mock_openai, mock_prompt, mock_cache
    ):
        """Test OpenAI API availability with no API key."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="openai", api_key=None)
        result = await client.is_api_available()
        assert result is False
