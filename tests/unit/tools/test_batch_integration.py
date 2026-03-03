"""Tests for batch structure-text separation integration in factory and manager."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from srt_translator.tools.srt_tools import batch_string_to_texts, texts_to_batch_string


# ============================================================
# TranslationService._translate_batch_structure_text Tests
# ============================================================


class TestTranslationServiceStructureText:
    """Tests for TranslationService._translate_batch_structure_text."""

    def _make_mock_subs(self, texts: list[str]) -> list:
        """Create mock subtitle objects."""
        subs = []
        for text in texts:
            sub = MagicMock()
            sub.text = text
            subs.append(sub)
        return subs

    def _make_service(self):
        """Create a TranslationService with mocked dependencies."""
        with patch(
            "srt_translator.services.factory.TranslationService.__init__",
            return_value=None,
        ):
            from srt_translator.services.factory import TranslationService

            service = TranslationService()
            service.prompt_manager = MagicMock()
            service.prompt_manager.get_batch_line_mapping_instruction.return_value = (
                "Translate each line 1:1."
            )
            service._post_process_translation = MagicMock(
                side_effect=lambda orig, trans: trans
            )
            service.translate_text = AsyncMock()
            service.translate_batch = AsyncMock()
            return service

    @pytest.mark.asyncio
    async def test_successful_batch_translation(self):
        """Test successful batch translation with correct line count."""
        service = self._make_service()
        subs = self._make_mock_subs(["Hello", "World", "Goodbye"])
        batch_indices = [0, 1, 2]

        # Mock translate_text to return correct 3-line translation
        service.translate_text.return_value = "你好\n世界\n再見"

        result = await service._translate_batch_structure_text(
            subs, batch_indices, "ollama", "test-model", 5
        )

        assert result == ["你好", "世界", "再見"]
        service.translate_text.assert_called_once()
        service.translate_batch.assert_not_called()

    @pytest.mark.asyncio
    async def test_multiline_subtitle_batch(self):
        """Test batch translation with multi-line subtitles."""
        service = self._make_service()
        subs = self._make_mock_subs(["Hello\nWorld", "Goodbye\nFriend"])
        batch_indices = [0, 1]

        # Multi-line subtitles use literal \n in batch string
        expected_batch = texts_to_batch_string(["Hello\nWorld", "Goodbye\nFriend"])
        assert expected_batch == "Hello\\nWorld\nGoodbye\\nFriend"

        # Translation should also use literal \n
        service.translate_text.return_value = "你好\\n世界\n再見\\n朋友"

        result = await service._translate_batch_structure_text(
            subs, batch_indices, "ollama", "test-model", 5
        )

        assert result == ["你好\n世界", "再見\n朋友"]

    @pytest.mark.asyncio
    async def test_fallback_on_line_count_mismatch(self):
        """Test fallback to standard translation when line count doesn't match."""
        service = self._make_service()
        subs = self._make_mock_subs(["Hello", "World", "Goodbye"])
        batch_indices = [0, 1, 2]

        # Return wrong number of lines — both attempts
        service.translate_text.return_value = "你好\n世界"  # 2 lines instead of 3

        # Fallback should use translate_batch
        service.translate_batch.return_value = ["你好", "世界", "再見"]

        result = await service._translate_batch_structure_text(
            subs, batch_indices, "ollama", "test-model", 5
        )

        # Should have fallen back to translate_batch
        assert service.translate_text.call_count == 2  # 2 retries
        service.translate_batch.assert_called_once()
        assert result == ["你好", "世界", "再見"]

    @pytest.mark.asyncio
    async def test_fallback_on_error_response(self):
        """Test fallback when translation returns error marker."""
        service = self._make_service()
        subs = self._make_mock_subs(["Hello", "World"])
        batch_indices = [0, 1]

        # Return error marker
        service.translate_text.return_value = "[翻譯錯誤: API 失敗]"

        service.translate_batch.return_value = ["你好", "世界"]

        result = await service._translate_batch_structure_text(
            subs, batch_indices, "ollama", "test-model", 5
        )

        assert service.translate_text.call_count == 2
        service.translate_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_fallback_on_empty_response(self):
        """Test fallback when translation returns empty string."""
        service = self._make_service()
        subs = self._make_mock_subs(["Hello"])
        batch_indices = [0]

        service.translate_text.return_value = ""
        service.translate_batch.return_value = ["你好"]

        result = await service._translate_batch_structure_text(
            subs, batch_indices, "ollama", "test-model", 5
        )

        assert result == ["你好"]

    @pytest.mark.asyncio
    async def test_fallback_on_exception(self):
        """Test fallback when translate_text raises exception."""
        service = self._make_service()
        subs = self._make_mock_subs(["Hello", "World"])
        batch_indices = [0, 1]

        service.translate_text.side_effect = RuntimeError("API error")
        service.translate_batch.return_value = ["你好", "世界"]

        result = await service._translate_batch_structure_text(
            subs, batch_indices, "ollama", "test-model", 5
        )

        assert result == ["你好", "世界"]

    @pytest.mark.asyncio
    async def test_post_process_called(self):
        """Test that post-processing is applied to each translation."""
        service = self._make_service()
        service._post_process_translation = MagicMock(
            side_effect=lambda orig, trans: f"[{trans}]"
        )
        subs = self._make_mock_subs(["Hello", "World"])
        batch_indices = [0, 1]

        service.translate_text.return_value = "你好\n世界"

        result = await service._translate_batch_structure_text(
            subs, batch_indices, "ollama", "test-model", 5
        )

        assert result == ["[你好]", "[世界]"]
        assert service._post_process_translation.call_count == 2

    @pytest.mark.asyncio
    async def test_retry_then_succeed(self):
        """Test retry: first attempt fails, second succeeds."""
        service = self._make_service()
        subs = self._make_mock_subs(["Hello", "World"])
        batch_indices = [0, 1]

        # First call: wrong line count, second call: correct
        service.translate_text.side_effect = [
            "只有一行",  # 1 line instead of 2
            "你好\n世界",  # correct 2 lines
        ]

        result = await service._translate_batch_structure_text(
            subs, batch_indices, "ollama", "test-model", 5
        )

        assert result == ["你好", "世界"]
        assert service.translate_text.call_count == 2
        service.translate_batch.assert_not_called()


# ============================================================
# TranslationManager._process_batch_structure_text Tests
# ============================================================


class TestTranslationManagerStructureText:
    """Tests for TranslationManager structure-text separation mode."""

    def _make_mock_manager(self):
        """Create a TranslationManager with mocked dependencies."""
        manager = MagicMock()
        manager.translated_indices = set()
        manager.stats = MagicMock()
        manager.stats.total_chars = 0
        manager.stats.translated_count = 0
        manager.stats.total_subtitles = 10
        manager.max_retries = 2
        manager.retry_delay = 0.01
        manager.progress_callback = None
        manager.display_mode = "僅顯示翻譯"
        manager.llm_type = "ollama"
        manager.model_name = "test-model"

        # Mock services
        manager.translation_service = MagicMock()
        manager.translation_service.translate_text = AsyncMock()

        # Use real methods
        from srt_translator.translation.manager import TranslationManager

        manager._process_batch_structure_text = (
            TranslationManager._process_batch_structure_text.__get__(manager)
        )
        manager._process_batch_individual_fallback = (
            TranslationManager._process_batch_individual_fallback.__get__(manager)
        )
        manager._apply_translation = (
            TranslationManager._apply_translation.__get__(manager)
        )
        manager._post_process_translation = MagicMock(
            side_effect=lambda orig, trans: trans
        )
        manager._translate_single_subtitle = AsyncMock(return_value=True)
        manager._adjust_batch_size = MagicMock()

        return manager

    def _make_mock_subs(self, texts: list[str]) -> list:
        """Create mock subtitle objects."""
        subs = []
        for text in texts:
            sub = MagicMock()
            sub.text = text
            subs.append(sub)
        return subs

    @pytest.mark.asyncio
    async def test_successful_batch(self):
        """Test successful structure-text batch processing."""
        manager = self._make_mock_manager()
        subs = self._make_mock_subs(["Hello", "World", "Goodbye"])

        manager.translation_service.translate_text.return_value = "你好\n世界\n再見"

        success, failed, skipped = await manager._process_batch_structure_text(
            subs, [0, 1, 2]
        )

        assert success == 3
        assert failed == 0
        assert skipped == 0
        assert manager.stats.translated_count == 3
        assert len(manager.translated_indices) == 3

    @pytest.mark.asyncio
    async def test_skip_already_translated(self):
        """Test skipping already translated subtitles."""
        manager = self._make_mock_manager()
        subs = self._make_mock_subs(["Hello", "World", "Goodbye"])
        manager.translated_indices = {0, 2}  # Already translated

        manager.translation_service.translate_text.return_value = "世界"

        success, failed, skipped = await manager._process_batch_structure_text(
            subs, [0, 1, 2]
        )

        assert skipped == 2
        assert success == 1
        assert failed == 0

    @pytest.mark.asyncio
    async def test_all_already_translated(self):
        """Test when all subtitles are already translated."""
        manager = self._make_mock_manager()
        subs = self._make_mock_subs(["Hello", "World"])
        manager.translated_indices = {0, 1}

        success, failed, skipped = await manager._process_batch_structure_text(
            subs, [0, 1]
        )

        assert success == 0
        assert failed == 0
        assert skipped == 2
        manager.translation_service.translate_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_batch(self):
        """Test with empty batch indices."""
        manager = self._make_mock_manager()
        subs = self._make_mock_subs(["Hello"])

        success, failed, skipped = await manager._process_batch_structure_text(
            subs, []
        )

        assert success == 0
        assert failed == 0
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_fallback_to_individual(self):
        """Test fallback to individual translation on repeated failure."""
        manager = self._make_mock_manager()
        subs = self._make_mock_subs(["Hello", "World"])

        # Always return wrong line count
        manager.translation_service.translate_text.return_value = "只有一行"

        success, failed, skipped = await manager._process_batch_structure_text(
            subs, [0, 1]
        )

        # Should have fallen back to individual
        assert manager._translate_single_subtitle.call_count == 2
        assert success == 2  # individual fallback returns True
        assert failed == 0

    @pytest.mark.asyncio
    async def test_individual_fallback_partial_failure(self):
        """Test individual fallback with some failures."""
        manager = self._make_mock_manager()
        subs = self._make_mock_subs(["Hello", "World", "Goodbye"])

        # Batch mode fails
        manager.translation_service.translate_text.side_effect = RuntimeError("fail")
        # Individual mode: 2 succeed, 1 fails
        manager._translate_single_subtitle.side_effect = [True, False, True]

        success, failed, skipped = await manager._process_batch_structure_text(
            subs, [0, 1, 2]
        )

        assert success == 2
        assert failed == 1
        assert skipped == 0

    @pytest.mark.asyncio
    async def test_dispatch_flag(self):
        """Test that _process_subtitle_batch dispatches to structure-text mode."""
        from srt_translator.translation.manager import TranslationManager

        manager = self._make_mock_manager()
        subs = self._make_mock_subs(["Hello"])

        # Set the flag
        manager.use_structure_text_separation = True
        manager._process_subtitle_batch = (
            TranslationManager._process_subtitle_batch.__get__(manager)
        )

        manager.translation_service.translate_text.return_value = "你好"

        success, failed, skipped = await manager._process_subtitle_batch(
            subs, [0]
        )

        assert success == 1

    @pytest.mark.asyncio
    async def test_progress_callback_called(self):
        """Test that progress callback is called for each successful translation."""
        manager = self._make_mock_manager()
        manager.progress_callback = MagicMock()
        subs = self._make_mock_subs(["Hello", "World"])

        manager.translation_service.translate_text.return_value = "你好\n世界"

        await manager._process_batch_structure_text(subs, [0, 1])

        assert manager.progress_callback.call_count == 2
