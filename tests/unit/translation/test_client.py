"""Tests for translation/client.py module."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

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
        controller = AdaptiveConcurrencyController(initial=5, min_concurrent=2, max_concurrent=15)
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
        controller = AdaptiveConcurrencyController(initial=3, min_concurrent=2, max_concurrent=10)
        # Set a very low average response time to trigger increase
        controller.avg_response_time = 0.1

        # Update with fast response time (< 0.5s)
        await controller.update(0.2)

        # After EMA update, avg should still be low enough to increase
        assert controller.current >= 3

    @pytest.mark.asyncio
    async def test_update_decreases_concurrency_for_slow_response(self):
        """Test concurrency decreases for slow API response."""
        controller = AdaptiveConcurrencyController(initial=5, min_concurrent=2, max_concurrent=10)
        # Set a high average response time
        controller.avg_response_time = 2.0

        # Update with slow response time (> 1.5s)
        await controller.update(2.5)

        # Should decrease concurrency
        assert controller.current <= 5

    @pytest.mark.asyncio
    async def test_update_respects_max_limit(self):
        """Test concurrency doesn't exceed max limit."""
        controller = AdaptiveConcurrencyController(initial=10, min_concurrent=2, max_concurrent=10)
        controller.avg_response_time = 0.1

        await controller.update(0.1)
        assert controller.current <= 10

    @pytest.mark.asyncio
    async def test_update_respects_min_limit(self):
        """Test concurrency doesn't go below min limit."""
        controller = AdaptiveConcurrencyController(initial=2, min_concurrent=2, max_concurrent=10)
        controller.avg_response_time = 3.0

        await controller.update(3.0)
        assert controller.current >= 2

    @pytest.mark.asyncio
    async def test_get_stats(self):
        """Test get_stats returns correct statistics."""
        controller = AdaptiveConcurrencyController(initial=5, min_concurrent=2, max_concurrent=10)
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
    def test_init_llamacpp(self, mock_openai, mock_prompt, mock_cache):
        """Test initialization with llama.cpp."""
        client = TranslationClient(
            llm_type="llamacpp",
            base_url="http://localhost:8080/v1",
        )
        assert client.llm_type == "llamacpp"
        assert client.base_url == "http://localhost:8080"
        assert client.openai_client is not None

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

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_should_retry_untranslated_japanese_for_hiragana_output(self, mock_prompt, mock_cache):
        """Test untranslated Japanese detector catches hiragana-heavy outputs."""
        client = TranslationClient(llm_type="ollama")
        assert client._should_retry_untranslated_japanese("つけて", "つけて") is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_should_retry_untranslated_japanese_for_mixed_short_output(self, mock_prompt, mock_cache):
        """Test detector catches short outputs that only leak one hiragana character."""
        client = TranslationClient(llm_type="ollama")
        assert client._should_retry_untranslated_japanese("待ってる", "等て") is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_should_retry_untranslated_japanese_for_kanji_only_source_with_added_hiragana(
        self, mock_prompt, mock_cache
    ):
        """Test detector catches kanji-only source lines when output appends Japanese kana."""
        client = TranslationClient(llm_type="ollama")
        assert client._should_retry_untranslated_japanese("最近", "最近どう？") is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_should_not_retry_when_only_japanese_name_is_preserved(self, mock_prompt, mock_cache):
        """Test untranslated Japanese detector ignores preserved Japanese names."""
        client = TranslationClient(llm_type="ollama")
        assert client._should_retry_untranslated_japanese("イチロー君が来た", "我喜歡イチロー君") is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_should_not_retry_clean_chinese_for_kanji_only_source(self, mock_prompt, mock_cache):
        """Test detector does not retry clean Chinese output for kanji-only source lines."""
        client = TranslationClient(llm_type="ollama")
        assert client._should_retry_untranslated_japanese("最近", "最近怎麼樣？") is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_should_not_retry_identical_kanji_cognate_output(self, mock_prompt, mock_cache):
        """Test detector avoids retrying kanji-only cognates that are also valid Chinese."""
        client = TranslationClient(llm_type="ollama")
        assert client._should_retry_untranslated_japanese("乾杯!", "乾杯！") is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_extract_japanese_name_candidates_for_suffix_name(self, mock_prompt, mock_cache):
        """Test extracting Japanese names/nicknames with suffixes for protection."""
        client = TranslationClient(llm_type="ollama")

        assert client._extract_japanese_name_candidates("イチロー君のこと大好きだよ") == ["イチロー君"]
        assert client._extract_japanese_name_candidates("やばい、たっちゃん、あ、くそ") == ["たっちゃん"]

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_extract_japanese_name_candidates_ignores_common_nouns(self, mock_prompt, mock_cache):
        """Test name protection stays narrow and does not treat common nouns as names."""
        client = TranslationClient(llm_type="ollama")

        assert client._extract_japanese_name_candidates("チーズ欲しい") == []

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_protect_and_restore_japanese_names(self, mock_prompt, mock_cache):
        """Test Japanese names are replaced before generation and restored afterward."""
        client = TranslationClient(llm_type="ollama")

        protected_text, protected_contexts, restore_map = client._protect_japanese_names_in_inputs(
            "イチロー君のこと大好きだよ",
            ["前文", "イチロー君のこと大好きだよ", "後文"],
        )

        assert protected_text == "[[JN0]]のこと大好きだよ"
        assert protected_contexts[1] == "[[JN0]]のこと大好きだよ"
        assert restore_map == {"[[JN0]]": "イチロー君"}
        assert client._restore_protected_japanese_names("超喜歡[[ JN0 ]]啦", restore_map) == "超喜歡イチロー君啦"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_restore_japanese_names_with_placeholder_variants(self, mock_prompt, mock_cache):
        """Test placeholder restoration tolerates common bracket and bare-token variants."""
        client = TranslationClient(llm_type="ollama")
        restore_map = {"[[JN0]]": "イチロー君"}

        assert client._restore_protected_japanese_names("最喜歡 JN0 了", restore_map) == "最喜歡 イチロー君 了"
        assert client._restore_protected_japanese_names("[JN0] 很厲害呢", restore_map) == "イチロー君 很厲害呢"
        assert (
            client._restore_protected_japanese_names("好可怕，[[JN0]]，啊，該死了", restore_map)
            == "好可怕，イチロー君，啊，該死了"
        )

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_detect_ollama_model_family_qwen35_custom_name(self, mock_prompt, mock_cache):
        """Test Qwen3.5 family detection for custom Ollama model names."""
        client = TranslationClient(llm_type="ollama")
        family = client._detect_ollama_model_family("HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0")
        assert family == "qwen3.5"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_detect_ollama_model_family_gemma4_custom_name(self, mock_prompt, mock_cache):
        """Test Gemma 4 family detection for local GGUF file names."""
        client = TranslationClient(llm_type="ollama")
        family = client._detect_ollama_model_family("gemma-4-E4B-it-UD-Q8_K_XL.gguf")
        assert family == "gemma4"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_build_ollama_payload_qwen35_profile(self, mock_prompt, mock_cache):
        """Test Qwen3.5 uses the specialized Ollama payload profile."""
        client = TranslationClient(llm_type="ollama")
        messages = [{"role": "system", "content": "test"}]

        payload = client._build_ollama_payload(
            messages,
            "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0",
        )

        assert payload["think"] is False
        assert payload["keep_alive"] == "15m"
        assert payload["options"]["temperature"] == 0.7
        assert payload["options"]["top_p"] == 0.8
        assert payload["options"]["top_k"] == 20
        assert payload["options"]["min_p"] == 0.0
        assert payload["options"]["num_predict"] == 256

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_build_ollama_payload_qwen35_ud_profile(self, mock_prompt, mock_cache):
        """Test qwen3.5-ud uses a tighter Ollama payload profile."""
        client = TranslationClient(llm_type="ollama")
        messages = [{"role": "system", "content": "test"}]

        payload = client._build_ollama_payload(messages, "qwen3.5-ud:latest")

        assert payload["think"] is False
        assert payload["keep_alive"] == "15m"
        assert payload["options"]["temperature"] == 0.7
        assert payload["options"]["top_p"] == 0.8
        assert payload["options"]["top_k"] == 20
        assert payload["options"]["min_p"] == 0.0
        assert payload["options"]["num_predict"] == 96

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_llamacpp_model_profile_qwen35(self, mock_prompt, mock_cache):
        """Test Qwen3.5 uses the specialized llama.cpp profile."""
        client = TranslationClient(llm_type="ollama")

        profile = client._get_llamacpp_model_profile("HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0")

        assert profile["family"] == "qwen3.5"
        assert profile["options"]["temperature"] == 0.7
        assert profile["options"]["top_p"] == 0.8
        assert profile["options"]["max_tokens"] == 256
        assert profile["extra_body"]["cache_prompt"] is True
        assert profile["extra_body"]["reasoning_format"] == "deepseek"
        assert profile["extra_body"]["reasoning_budget_tokens"] == 0
        assert profile["extra_body"]["seed"] == 42
        assert profile["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
        assert profile["extra_body"]["presence_penalty"] == 1.5
        assert profile["extra_body"]["top_k"] == 20
        assert profile["extra_body"]["min_p"] == 0.0

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_llamacpp_model_profile_qwen35_ud(self, mock_prompt, mock_cache):
        """Test qwen3.5-ud uses the tighter llama.cpp profile."""
        client = TranslationClient(llm_type="ollama")

        profile = client._get_llamacpp_model_profile("qwen3.5-ud:latest")

        assert profile["family"] == "qwen3.5"
        assert profile["profile"] == "qwen3.5-ud"
        assert profile["options"]["temperature"] == 0.7
        assert profile["options"]["top_p"] == 0.8
        assert profile["options"]["max_tokens"] == 96
        assert profile["extra_body"]["cache_prompt"] is True
        assert profile["extra_body"]["reasoning_format"] == "deepseek"
        assert profile["extra_body"]["reasoning_budget_tokens"] == 0
        assert profile["extra_body"]["seed"] == 42
        assert profile["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
        assert profile["extra_body"]["presence_penalty"] == 1.5
        assert profile["extra_body"]["top_k"] == 20
        assert profile["extra_body"]["min_p"] == 0.0

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_llamacpp_model_profile_qwen3(self, mock_prompt, mock_cache):
        """Test Qwen3 uses the dedicated llama.cpp profile with Qwen3 recommended params."""
        client = TranslationClient(llm_type="ollama")

        profile = client._get_llamacpp_model_profile("qwen3:8b")

        assert profile["family"] == "qwen3"
        assert profile["options"]["temperature"] == 0.7
        assert profile["options"]["top_p"] == 0.8
        assert profile["options"]["max_tokens"] == 256
        assert profile["extra_body"]["cache_prompt"] is True
        assert profile["extra_body"]["reasoning_format"] == "deepseek"
        assert profile["extra_body"]["reasoning_budget_tokens"] == 0
        assert profile["extra_body"]["seed"] == 42
        assert profile["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
        assert profile["extra_body"]["presence_penalty"] == 1.5
        assert profile["extra_body"]["top_k"] == 20
        assert profile["extra_body"]["min_p"] == 0.0

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_llamacpp_model_profile_resolved_from_server(self, mock_prompt, mock_cache):
        """Test llama.cpp profile resolves generic 'local-model' via server model_path."""
        client = TranslationClient(llm_type="llamacpp", base_url="http://localhost:8080")

        # 未解析前，generic name 回退到 default profile
        profile_before = client._get_llamacpp_model_profile("local-model")
        assert profile_before["family"] == "default"
        assert profile_before["options"]["temperature"] == 0.1

        # 模擬 server /props 回報了實際模型路徑
        client._llamacpp_resolved_model_name = "Qwen3.5-27B-UD-Q4_K_XL.gguf"

        # 解析後，應偵測為 qwen3.5 family
        profile_after = client._get_llamacpp_model_profile("local-model")
        assert profile_after["family"] == "qwen3.5"
        assert profile_after["options"]["temperature"] == 0.7
        assert profile_after["extra_body"]["presence_penalty"] == 1.5

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_llamacpp_model_profile_gemma4(self, mock_prompt, mock_cache):
        """Test Gemma 4 uses official sampling params and reasoning=off."""
        client = TranslationClient(llm_type="ollama")

        profile = client._get_llamacpp_model_profile("gemma-4-E4B-it-UD-Q8_K_XL.gguf")

        assert profile["family"] == "gemma4"
        assert profile["options"]["temperature"] == 1.0
        assert profile["options"]["top_p"] == 0.95
        assert profile["options"]["max_tokens"] == 256
        assert profile["extra_body"]["cache_prompt"] is True
        assert profile["extra_body"]["reasoning_format"] == "none"
        assert profile["extra_body"]["reasoning"] == "off"
        assert profile["extra_body"]["seed"] == 42
        assert profile["extra_body"]["top_k"] == 64
        assert "reasoning_budget_tokens" not in profile["extra_body"]
        assert "chat_template_kwargs" not in profile["extra_body"]

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_sanitize_ollama_translation_removes_think_and_chatml(self, mock_prompt, mock_cache):
        """Test cleaning residual thinking blocks and ChatML assistant markers."""
        client = TranslationClient(llm_type="ollama")
        raw = "<think>internal</think>\n<|im_start|>assistant\n你好世界<|im_end|>"

        result = client._sanitize_ollama_translation(raw)

        assert result == "你好世界"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_extract_llamacpp_structured_translation(self, mock_prompt, mock_cache):
        """Test extracting the translation field from llama.cpp structured output."""
        client = TranslationClient(llm_type="ollama")

        result = client._extract_llamacpp_structured_translation('{"translation":"保留原文換行"}')

        assert result == "保留原文換行"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_extract_llamacpp_structured_translation_with_reasoning_leak(self, mock_prompt, mock_cache):
        """Test extracting translation when reasoning text leaks before JSON."""
        client = TranslationClient(llm_type="ollama")

        result = client._extract_llamacpp_structured_translation('一些推理文字\n{"translation":"翻譯結果"}')

        assert result == "翻譯結果"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_extract_llamacpp_structured_translation_with_think_tags(self, mock_prompt, mock_cache):
        """Test extracting translation when think tags appear before JSON."""
        client = TranslationClient(llm_type="ollama")

        result = client._extract_llamacpp_structured_translation('<think>思考中...</think>\n{"translation":"翻譯結果"}')

        assert result == "翻譯結果"

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_ollama_batch_size_limits_qwen35_to_one(self, mock_prompt, mock_cache):
        """Test Qwen3.5 batch concurrency is capped to 1 for Ollama stability."""
        client = TranslationClient(llm_type="ollama")

        batch_size = client._get_ollama_batch_size(
            "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0",
            concurrent_limit=5,
            adaptive_concurrency=4,
            pending=8,
        )

        assert batch_size == 1

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_get_effective_batch_size_limits_llamacpp_to_server_slots(self, mock_openai, mock_prompt, mock_cache):
        """Test llama.cpp batch concurrency respects detected server slot count."""
        client = TranslationClient(llm_type="llamacpp", base_url="http://localhost:8080")
        client._get_llamacpp_server_diagnostics = AsyncMock(  # type: ignore[method-assign]
            return_value={"available": True, "total_slots": 2}
        )

        batch_size = await client._get_effective_batch_size(
            "llama3.2",
            concurrent_limit=6,
            adaptive_concurrency=5,
            pending=8,
        )

        assert batch_size == 2

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_get_effective_batch_size_qwen35_ud_respects_server_slots(self, mock_openai, mock_prompt, mock_cache):
        """Test qwen3.5-ud llamacpp concurrency is capped by server slots, not hard-coded to 1."""
        client = TranslationClient(llm_type="llamacpp", base_url="http://localhost:8080")
        client._get_llamacpp_server_diagnostics = AsyncMock(  # type: ignore[method-assign]
            return_value={"available": True, "total_slots": 2}
        )

        batch_size = await client._get_effective_batch_size(
            "Qwen3.5-9B-UD-Q8_K_XL",
            concurrent_limit=4,
            adaptive_concurrency=3,
            pending=8,
        )

        assert batch_size == 2

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_get_effective_batch_size_fallback_when_diagnostics_fail(self, mock_openai, mock_prompt, mock_cache):
        """Test conservative fallback when server diagnostics cannot determine total_slots."""
        client = TranslationClient(llm_type="llamacpp", base_url="http://localhost:8080")
        client._get_llamacpp_server_diagnostics = AsyncMock(  # type: ignore[method-assign]
            return_value={"available": False, "total_slots": None}
        )

        batch_size = await client._get_effective_batch_size(
            "Qwen3.5-9B-UD-Q8_K_XL",
            concurrent_limit=6,
            adaptive_concurrency=5,
            pending=8,
        )

        assert batch_size == client._LLAMACPP_FALLBACK_SLOTS

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_fallback_models_uses_qwen35_family(self, mock_prompt, mock_cache):
        """Test custom Qwen3.5 model names can reuse family-based fallback config."""
        client = TranslationClient(llm_type="ollama")

        fallback_models = client._get_fallback_models("HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0")

        assert fallback_models == ["qwen3", "llama3.2", "gemma3"]

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    def test_get_fallback_models_qwen35_ud_prefers_uncensored_variant(self, mock_prompt, mock_cache):
        """Test qwen3.5-ud falls back to uncensored sibling before generic family fallbacks."""
        client = TranslationClient(llm_type="ollama")

        fallback_models = client._get_fallback_models("qwen3.5-ud:latest")

        assert fallback_models[0] == "qwen3.5-uncensored:latest"
        assert "qwen3" in fallback_models
        assert "llama3.2" in fallback_models


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
    def test_validate_openai_api_key_valid_legacy(self, mock_openai, mock_prompt, mock_cache):
        """Test validation of valid legacy API key."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        # Legacy key format: sk-... with ~51 characters
        valid_key = "sk-" + "a" * 48
        assert client._validate_openai_api_key(valid_key) is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_valid_project(self, mock_openai, mock_prompt, mock_cache):
        """Test validation of valid project API key."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        # Project key format: sk-proj-...
        valid_key = "sk-proj-" + "a" * 80
        assert client._validate_openai_api_key(valid_key) is True

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_invalid_empty(self, mock_openai, mock_prompt, mock_cache):
        """Test validation of empty API key."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        assert client._validate_openai_api_key("") is False
        assert client._validate_openai_api_key(None) is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_invalid_prefix(self, mock_openai, mock_prompt, mock_cache):
        """Test validation of key with wrong prefix."""
        client = TranslationClient(llm_type="openai", api_key="sk-test")
        assert client._validate_openai_api_key("invalid-key") is False

    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    def test_validate_openai_api_key_invalid_characters(self, mock_openai, mock_prompt, mock_cache):
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

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_ignores_invalid_cached_translation(self, mock_prompt, mock_cache):
        """Test invalid cached Japanese leakage is ignored and refreshed."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = "最近どう？"
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.current_content_type = "general"
        mock_prompt_instance.get_prompt_version.return_value = "retryv2"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]1", "最近"]
        mock_prompt_instance.get_optimized_message.return_value = [
            {"role": "system", "content": "Base prompt"},
            {"role": "user", "content": "[CURRENT]\n最近"},
        ]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        client._translate_with_ollama = AsyncMock(return_value="最近怎麼樣？")

        result = await client.translate_text("最近", ["前文", "最近", "後文"], "llama3")

        assert result == "最近怎麼樣？"
        assert client.metrics.cache_hits == 0
        assert client._translate_with_ollama.await_count == 1
        mock_cache_instance.store_translation.assert_called_once_with(
            "最近",
            "最近怎麼樣？",
            ["[CURRENT_INDEX]1", "最近"],
            "llama3",
            "standard",
            "retryv2",
            current_index=None,
            lookup_source="translation_client_store",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_from_cache_uses_prompt_version(self, mock_prompt, mock_cache):
        """Test translating text from cache includes style and prompt version in cache lookup."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = "cached translation"
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "qwen35udv1"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]0"]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        result = await client.translate_text("Hello", [], "qwen3.5-ud:latest")

        assert result == "cached translation"
        mock_cache_instance.get_cached_translation.assert_called_once_with(
            "Hello",
            ["[CURRENT_INDEX]0"],
            "qwen3.5-ud:latest",
            "standard",
            "qwen35udv1",
            current_index=None,
            lookup_source="translation_client",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_passes_current_index_to_effective_cache_context(self, mock_prompt, mock_cache):
        """Test current_index is forwarded to prompt manager cache-context helper."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = "cached translation"
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "qwen35udv2"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]2", "Hello"]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        result = await client.translate_text(
            "Hello",
            ["前一行", "Hello", "Hello", "後一行"],
            "qwen3.5-ud:latest",
            current_index=2,
        )

        assert result == "cached translation"
        mock_prompt_instance.get_effective_cache_context_texts.assert_called_once_with(
            "Hello",
            ["前一行", "Hello", "Hello", "後一行"],
            "ollama",
            "qwen3.5-ud:latest",
            current_index=2,
        )
        mock_cache_instance.get_cached_translation.assert_called_once_with(
            "Hello",
            ["[CURRENT_INDEX]2", "Hello"],
            "qwen3.5-ud:latest",
            "standard",
            "qwen35udv2",
            current_index=2,
            lookup_source="translation_client",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_protects_and_restores_japanese_names_for_qwen35_ud(self, mock_prompt, mock_cache):
        """Test qwen3.5-ud adult path protects Japanese names before generation and restores them afterward."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = None
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.current_content_type = "adult"
        mock_prompt_instance.get_prompt_version.return_value = "qwen35udv3"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = [
            "[CACHE_MODE]qwen35_ud_short_utterance_v1"
        ]
        mock_prompt_instance.get_optimized_message.return_value = [{"role": "user", "content": "protected"}]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        client._translate_with_ollama = AsyncMock(return_value="超喜歡[[JN0]]啦")

        result = await client.translate_text(
            "イチロー君のこと大好きだよ",
            ["前文", "イチロー君のこと大好きだよ", "後文"],
            "qwen3.5-ud:latest",
            current_index=1,
        )

        assert result == "超喜歡イチロー君啦"
        mock_prompt_instance.get_optimized_message.assert_called_once_with(
            "[[JN0]]のこと大好きだよ",
            ["前文", "[[JN0]]のこと大好きだよ", "後文"],
            "ollama",
            "qwen3.5-ud:latest",
            current_index=1,
        )
        mock_cache_instance.store_translation.assert_called_once_with(
            "イチロー君のこと大好きだよ",
            "超喜歡イチロー君啦",
            ["[CACHE_MODE]qwen35_ud_short_utterance_v1"],
            "qwen3.5-ud:latest",
            "standard",
            "qwen35udv3",
            current_index=1,
            lookup_source="translation_client_store",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_translate_text_protects_and_restores_japanese_names_for_qwen35_ud_llamacpp(
        self, mock_openai_cls, mock_prompt, mock_cache
    ):
        """Test qwen3.5-ud protection path also applies to llama.cpp local models."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = None
        mock_cache.return_value = mock_cache_instance

        mock_openai_client = MagicMock()
        mock_openai_cls.return_value = mock_openai_client

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.current_content_type = "adult"
        mock_prompt_instance.get_prompt_version.return_value = "qwen35udv3"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = [
            "[CACHE_MODE]qwen35_ud_short_utterance_v1"
        ]
        mock_prompt_instance.get_optimized_message.return_value = [{"role": "user", "content": "protected"}]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="llamacpp", base_url="http://localhost:8080")
        client._translate_with_openai = AsyncMock(return_value="超喜歡[[JN0]]啦")

        result = await client.translate_text(
            "イチロー君のこと大好きだよ",
            ["前文", "イチロー君のこと大好きだよ", "後文"],
            "qwen3.5-ud:latest",
            current_index=1,
        )

        assert result == "超喜歡イチロー君啦"
        mock_prompt_instance.get_optimized_message.assert_called_once_with(
            "[[JN0]]のこと大好きだよ",
            ["前文", "[[JN0]]のこと大好きだよ", "後文"],
            "llamacpp",
            "qwen3.5-ud:latest",
            current_index=1,
        )
        mock_cache_instance.store_translation.assert_called_once_with(
            "イチロー君のこと大好きだよ",
            "超喜歡イチロー君啦",
            ["[CACHE_MODE]qwen35_ud_short_utterance_v1"],
            "qwen3.5-ud:latest",
            "standard",
            "qwen35udv3",
            current_index=1,
            lookup_source="translation_client_store",
        )

    @pytest.mark.skip(reason="Complex async mock setup needed")
    @pytest.mark.asyncio
    async def test_translate_with_ollama(self):
        """Test translation with Ollama API - skipped."""
        pass

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_with_ollama_qwen35_payload_and_cleanup(self, mock_prompt, mock_cache):
        """Test Qwen3.5 Ollama request payload and response cleanup."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(
            return_value={
                "message": {
                    "role": "assistant",
                    "content": "<think>analysis</think>\n<|im_start|>assistant\n翻譯結果<|im_end|>",
                    "thinking": "analysis",
                }
            }
        )

        mock_context_manager = MagicMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_context_manager

        client = TranslationClient(llm_type="ollama")
        client.session = mock_session

        result = await client._translate_with_ollama(
            [{"role": "user", "content": "test"}],
            "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0",
        )

        request_payload = mock_session.post.call_args.kwargs["json"]
        assert request_payload["think"] is False
        assert request_payload["keep_alive"] == "15m"
        assert request_payload["options"]["temperature"] == 0.7
        assert request_payload["options"]["top_p"] == 0.8
        assert request_payload["options"]["top_k"] == 20
        assert request_payload["options"]["min_p"] == 0.0
        assert result == "翻譯結果"

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_with_ollama_qwen35_ud_payload(self, mock_prompt, mock_cache):
        """Test qwen3.5-ud Ollama request uses tightened profile."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        mock_resp = AsyncMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json = AsyncMock(return_value={"message": {"role": "assistant", "content": "翻譯結果"}})

        mock_context_manager = MagicMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.post.return_value = mock_context_manager

        client = TranslationClient(llm_type="ollama")
        client.session = mock_session

        result = await client._translate_with_ollama(
            [{"role": "user", "content": "test"}],
            "qwen3.5-ud:latest",
        )

        request_payload = mock_session.post.call_args.kwargs["json"]
        assert request_payload["keep_alive"] == "15m"
        assert request_payload["options"]["temperature"] == 0.7
        assert request_payload["options"]["num_predict"] == 96
        assert result == "翻譯結果"

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_translate_with_llamacpp_qwen35_payload(self, mock_openai_cls, mock_prompt, mock_cache):
        """Test Qwen3.5 llama.cpp request payload disables thinking explicitly."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"translation":"翻譯結果"}'))]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=6)

        mock_openai_client = MagicMock()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_openai_client

        client = TranslationClient(llm_type="llamacpp", base_url="http://localhost:8080")
        result = await client._translate_with_openai(
            [{"role": "user", "content": "test"}],
            "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0",
        )

        request_payload = mock_openai_client.chat.completions.create.call_args.kwargs
        assert request_payload["temperature"] == 0.7
        assert request_payload["top_p"] == 0.8
        assert request_payload["max_tokens"] == 256
        assert request_payload["response_format"]["type"] == "json_object"
        assert request_payload["response_format"]["schema"]["required"] == ["translation"]
        assert request_payload["extra_body"]["cache_prompt"] is True
        assert request_payload["extra_body"]["reasoning_format"] == "deepseek"
        assert request_payload["extra_body"]["seed"] == 42
        assert request_payload["extra_body"]["chat_template_kwargs"]["enable_thinking"] is False
        assert request_payload["extra_body"]["presence_penalty"] == 1.5
        assert request_payload["extra_body"]["top_k"] == 20
        assert request_payload["extra_body"]["min_p"] == 0.0
        assert result == "翻譯結果"

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_translate_with_llamacpp_gemma4_payload(self, mock_openai_cls, mock_prompt, mock_cache):
        """Test Gemma 4 llama.cpp request payload uses reasoning=off without template kwargs."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content='{"translation":"翻譯結果"}'))]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=6)

        mock_openai_client = MagicMock()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_openai_client

        client = TranslationClient(llm_type="llamacpp", base_url="http://localhost:8080")
        result = await client._translate_with_openai(
            [{"role": "user", "content": "test"}],
            "gemma-4-E4B-it-UD-Q8_K_XL.gguf",
        )

        request_payload = mock_openai_client.chat.completions.create.call_args.kwargs
        assert request_payload["temperature"] == 1.0
        assert request_payload["top_p"] == 0.95
        assert request_payload["max_tokens"] == 256
        assert request_payload["response_format"]["type"] == "json_object"
        assert request_payload["response_format"]["schema"]["required"] == ["translation"]
        assert request_payload["extra_body"]["cache_prompt"] is True
        assert request_payload["extra_body"]["reasoning_format"] == "none"
        assert request_payload["extra_body"]["reasoning"] == "off"
        assert request_payload["extra_body"]["seed"] == 42
        assert request_payload["extra_body"]["top_k"] == 64
        assert "reasoning_budget_tokens" not in request_payload["extra_body"]
        assert "chat_template_kwargs" not in request_payload["extra_body"]
        assert result == "翻譯結果"

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_translate_with_openai_batch_request_expands_max_tokens(
        self, mock_openai_cls, mock_prompt, mock_cache
    ):
        """Test structured batch requests raise max_tokens and lower temperature."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="第一行\n第二行\n第三行\n第四行\n第五行"))]
        mock_response.usage = MagicMock(prompt_tokens=10, completion_tokens=12)

        mock_openai_client = MagicMock()
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_response)
        mock_openai_cls.return_value = mock_openai_client

        client = TranslationClient(llm_type="openai", api_key="sk-test-key")
        await client._translate_with_openai(
            [
                {
                    "role": "user",
                    "content": "[BATCH: 5 lines — translate each line, output exactly 5 lines]\nA\nB\nC\nD\nE",
                }
            ],
            "gpt-4o-mini",
        )

        request_payload = mock_openai_client.chat.completions.create.call_args.kwargs
        assert request_payload["max_tokens"] > 150
        assert request_payload["temperature"] == 0.0

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_retries_once_when_output_still_contains_japanese(self, mock_prompt, mock_cache):
        """Test translate_text performs one reinforced retry for untranslated Japanese output."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = None
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.current_content_type = "general"
        mock_prompt_instance.get_prompt_version.return_value = "retryv1"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]1", "つけて"]
        mock_prompt_instance.get_optimized_message.return_value = [
            {"role": "system", "content": "Base prompt"},
            {"role": "user", "content": "[CURRENT]\nつけて"},
        ]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        client._translate_with_ollama = AsyncMock(side_effect=["つけて", "戴上"])

        result = await client.translate_text("つけて", ["前文", "つけて", "後文"], "llama3")

        assert result == "戴上"
        assert client._translate_with_ollama.await_count == 2
        second_call_messages = client._translate_with_ollama.await_args_list[1].args[0]
        assert "CRITICAL RETRY INSTRUCTION" in second_call_messages[0]["content"]
        mock_cache_instance.store_translation.assert_called_once_with(
            "つけて",
            "戴上",
            ["[CURRENT_INDEX]1", "つけて"],
            "llama3",
            "standard",
            "retryv1",
            current_index=None,
            lookup_source="translation_client_store",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_does_not_store_invalid_translation_in_cache(self, mock_prompt, mock_cache):
        """Test final output with unresolved Japanese leakage is not cached."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = None
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.current_content_type = "general"
        mock_prompt_instance.get_prompt_version.return_value = "retryv3"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]1", "最近"]
        mock_prompt_instance.get_optimized_message.return_value = [
            {"role": "system", "content": "Base prompt"},
            {"role": "user", "content": "[CURRENT]\n最近"},
        ]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        client._translate_with_ollama = AsyncMock(side_effect=["最近どう？", "最近どう？"])

        result = await client.translate_text("最近", ["前文", "最近", "後文"], "llama3")

        assert result == "最近どう？"
        assert client._translate_with_ollama.await_count == 2
        mock_cache_instance.store_translation.assert_not_called()

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_text_skips_cache_when_disabled(self, mock_prompt, mock_cache):
        """Test use_cache=False bypasses client-level cache lookup and storage."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.current_content_type = "general"
        mock_prompt_instance.get_prompt_version.return_value = "nocachev1"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]0", "Hello"]
        mock_prompt_instance.get_optimized_message.return_value = [{"role": "user", "content": "Hello"}]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        client._translate_with_ollama = AsyncMock(return_value="新翻譯")

        result = await client.translate_text("Hello", [], "llama3", use_cache=False)

        assert result == "新翻譯"
        mock_cache_instance.get_cached_translation.assert_not_called()
        mock_cache_instance.store_translation.assert_not_called()
        client._translate_with_ollama.assert_awaited_once()

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
    async def test_translate_batch_ignores_invalid_cached_precheck_result(self, mock_prompt, mock_cache):
        """Test batch precheck ignores cached Japanese leakage and re-requests that item."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.side_effect = ["最近どう？", "cached translation"]
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "batchv1"
        mock_prompt_instance.get_effective_cache_context_texts.side_effect = [["ctx-recent"], ["ctx-hello"]]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        client.translate_with_retry = AsyncMock(return_value="最近怎麼樣？")
        client._get_effective_batch_size = AsyncMock(return_value=1)

        result = await client.translate_batch([("最近", []), ("Hello", [])], "llama3")

        assert result == ["最近怎麼樣？", "cached translation"]
        assert client.metrics.cache_hits == 1
        client.translate_with_retry.assert_awaited_once_with("最近", [], "llama3", current_index=None)

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_batch_passes_current_index_to_cache_lookup(self, mock_prompt, mock_cache):
        """Test batch cache precheck records current_index diagnostics."""
        mock_cache_instance = MagicMock()
        mock_cache_instance.get_cached_translation.return_value = "cached translation"
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "qwen35udv3"
        mock_prompt_instance.get_effective_cache_context_texts.return_value = ["[CURRENT_INDEX]3", "更多"]
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        result = await client.translate_batch(
            [("更多", ["前一行", "更多", "更多", "後一行"])],
            "qwen3.5-ud:latest",
            current_indices=[3],
        )

        assert result == ["cached translation"]
        mock_cache_instance.get_cached_translation.assert_called_once_with(
            "更多",
            ["[CURRENT_INDEX]3", "更多"],
            "qwen3.5-ud:latest",
            "standard",
            "qwen35udv3",
            current_index=3,
            lookup_source="translation_client_batch_precheck",
        )

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    async def test_translate_batch_skips_cache_when_disabled(self, mock_prompt, mock_cache):
        """Test batch translation bypasses cache precheck when use_cache=False."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        mock_prompt_instance = MagicMock()
        mock_prompt_instance.current_style = "standard"
        mock_prompt_instance.get_prompt_version.return_value = "nocache-batch-v1"
        mock_prompt.return_value = mock_prompt_instance

        client = TranslationClient(llm_type="ollama")
        client.translate_with_retry = AsyncMock(side_effect=["甲", "乙"])
        client._get_effective_batch_size = AsyncMock(return_value=2)

        result = await client.translate_batch([("Hello", []), ("World", [])], "llama3", use_cache=False)

        assert result == ["甲", "乙"]
        mock_cache_instance.get_cached_translation.assert_not_called()
        client.translate_with_retry.assert_has_awaits(
            [
                call("Hello", [], "llama3", current_index=None, use_cache=False),
                call("World", [], "llama3", current_index=None, use_cache=False),
            ]
        )

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
    async def test_is_api_available_openai_no_key(self, mock_openai, mock_prompt, mock_cache):
        """Test OpenAI API availability with no API key."""
        mock_cache_instance = MagicMock()
        mock_cache.return_value = mock_cache_instance

        client = TranslationClient(llm_type="openai", api_key=None)
        result = await client.is_api_available()
        assert result is False

    @pytest.mark.asyncio
    @patch("srt_translator.translation.client.CacheManager")
    @patch("srt_translator.translation.client.PromptManager")
    @patch("srt_translator.translation.client.AsyncOpenAI")
    @patch("srt_translator.translation.client.OPENAI_AVAILABLE", True)
    async def test_is_api_available_llamacpp_success(self, mock_openai, mock_prompt, mock_cache):
        """Test llama.cpp availability check delegates to server diagnostics."""
        client = TranslationClient(llm_type="llamacpp", base_url="http://localhost:8080")
        client._get_llamacpp_server_diagnostics = AsyncMock(  # type: ignore[method-assign]
            return_value={"available": True, "total_slots": 1}
        )

        result = await client.is_api_available()

        assert result is True
