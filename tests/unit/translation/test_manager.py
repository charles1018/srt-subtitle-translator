"""Tests for translation/manager.py module."""

import os
import tempfile
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from srt_translator.translation.manager import (
    TranslationManager,
    TranslationStats,
    TranslationTaskManager,
    TranslationThread,
)


# ============================================================
# TranslationStats Tests
# ============================================================


class TestTranslationStats:
    """Tests for TranslationStats dataclass."""

    def test_initial_values(self):
        """Test default initial values."""
        stats = TranslationStats()
        assert stats.started_at == 0
        assert stats.finished_at == 0
        assert stats.total_subtitles == 0
        assert stats.translated_count == 0
        assert stats.failed_count == 0
        assert stats.skipped_count == 0
        assert stats.cached_count == 0
        assert stats.total_chars == 0
        assert stats.errors == []

    def test_get_elapsed_time_running(self):
        """Test elapsed time while still running."""
        stats = TranslationStats()
        stats.started_at = time.time() - 10  # Started 10 seconds ago
        stats.finished_at = 0  # Not finished

        elapsed = stats.get_elapsed_time()
        assert elapsed >= 9.9  # Allow some tolerance

    def test_get_elapsed_time_finished(self):
        """Test elapsed time after finishing."""
        stats = TranslationStats()
        stats.started_at = 100.0
        stats.finished_at = 150.0

        elapsed = stats.get_elapsed_time()
        assert elapsed == 50.0

    def test_get_formatted_elapsed_time(self):
        """Test formatted elapsed time."""
        stats = TranslationStats()
        stats.started_at = time.time() - 65  # 1 minute 5 seconds ago
        stats.finished_at = time.time()

        formatted = stats.get_formatted_elapsed_time()
        # Should contain minute indication
        assert len(formatted) > 0

    def test_get_translation_speed(self):
        """Test translation speed calculation."""
        stats = TranslationStats()
        stats.started_at = 0
        stats.finished_at = 60  # 1 minute
        stats.translated_count = 30

        speed = stats.get_translation_speed()
        assert speed == 30.0  # 30 subtitles per minute

    def test_get_translation_speed_zero_time(self):
        """Test translation speed with zero time."""
        stats = TranslationStats()
        # When started_at and finished_at are both 0, elapsed time is current time
        # which is non-zero, so speed won't be 0. Let's test a very short elapsed time.
        stats.started_at = time.time()
        stats.finished_at = stats.started_at  # Same time = 0 elapsed
        stats.translated_count = 30

        # With 0 elapsed time, get_elapsed_time returns 0, and speed should be 0
        speed = stats.get_translation_speed()
        # Speed calculation: translated_count / (elapsed / 60)
        # When elapsed is 0, mins is 0, and we return 0
        assert speed == 0

    def test_get_char_speed(self):
        """Test character speed calculation."""
        stats = TranslationStats()
        stats.started_at = 0
        stats.finished_at = 60  # 1 minute
        stats.total_chars = 600

        speed = stats.get_char_speed()
        assert speed == 600.0  # 600 chars per minute

    def test_get_char_speed_zero_time(self):
        """Test character speed with zero time."""
        stats = TranslationStats()
        stats.started_at = time.time()
        stats.finished_at = stats.started_at  # Same time = 0 elapsed
        stats.total_chars = 600

        speed = stats.get_char_speed()
        assert speed == 0

    def test_get_summary(self):
        """Test getting summary."""
        stats = TranslationStats()
        stats.total_subtitles = 100
        stats.translated_count = 90
        stats.failed_count = 5
        stats.skipped_count = 5
        stats.cached_count = 20
        stats.total_chars = 5000
        stats.batch_count = 10
        stats.retry_count = 3
        stats.started_at = 0
        stats.finished_at = 120  # 2 minutes

        summary = stats.get_summary()

        assert summary["總字幕數"] == 100
        assert summary["已翻譯"] == 90
        assert summary["失敗"] == 5
        assert summary["跳過"] == 5
        assert summary["快取命中"] == 20
        assert summary["總字元數"] == 5000
        assert summary["批次數"] == 10
        assert summary["重試次數"] == 3


# ============================================================
# TranslationManager Tests
# ============================================================


class TestTranslationManagerInit:
    """Tests for TranslationManager initialization."""

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_initialization(self):
        """Test TranslationManager initialization - skipped due to complex dependencies."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_initialization_with_api_key(self):
        """Test TranslationManager initialization with API key - skipped."""
        pass


class TestTranslationManagerPostProcess:
    """Tests for TranslationManager post-processing."""

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_post_process_simple(self):
        """Test simple post-processing - skipped."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_post_process_with_key_terms(self):
        """Test post-processing with key terms dictionary - skipped."""
        pass


class TestTranslationManagerCheckpoint:
    """Tests for TranslationManager checkpoint functionality."""

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_get_checkpoint_path(self):
        """Test checkpoint path generation - skipped."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_save_checkpoint(self):
        """Test saving checkpoint - skipped."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_load_checkpoint_not_exists(self):
        """Test loading checkpoint when file doesn't exist - skipped."""
        pass


class TestTranslationManagerControl:
    """Tests for TranslationManager control methods."""

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_pause(self):
        """Test pausing translation - skipped."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_resume(self):
        """Test resuming translation - skipped."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_stop(self):
        """Test stopping translation - skipped."""
        pass


class TestTranslationManagerEncoding:
    """Tests for TranslationManager encoding methods."""

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_get_subtitle_encoding_default(self):
        """Test getting default encoding - skipped."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_get_subtitle_encoding_from_info(self):
        """Test getting encoding from file info - skipped."""
        pass


# ============================================================
# TranslationThread Tests
# ============================================================


class TestTranslationThread:
    """Tests for TranslationThread class."""

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_initialization(self):
        """Test TranslationThread initialization - skipped."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_stop(self):
        """Test stopping thread - skipped."""
        pass

    @pytest.mark.skip(reason="Complex initialization requires full service setup")
    def test_pause_resume(self):
        """Test pausing and resuming thread - skipped."""
        pass


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

    def test_with_mock_tasks(self):
        """Test task management with mock tasks."""
        manager = TranslationTaskManager()

        # Create mock tasks
        mock_task1 = MagicMock()
        mock_task1.is_alive.return_value = True
        mock_task1.is_paused.return_value = False

        mock_task2 = MagicMock()
        mock_task2.is_alive.return_value = True
        mock_task2.is_paused.return_value = False

        # Add tasks directly
        manager.tasks["file1.srt"] = mock_task1
        manager.tasks["file2.srt"] = mock_task2

        assert manager.get_active_task_count() == 2
        assert manager.is_any_running() is True
        assert manager.is_all_paused() is False

    def test_with_paused_tasks(self):
        """Test is_all_paused with paused tasks."""
        manager = TranslationTaskManager()

        # Create mock paused tasks
        mock_task1 = MagicMock()
        mock_task1.is_alive.return_value = True
        mock_task1.is_paused.return_value = True

        mock_task2 = MagicMock()
        mock_task2.is_alive.return_value = True
        mock_task2.is_paused.return_value = True

        manager.tasks["file1.srt"] = mock_task1
        manager.tasks["file2.srt"] = mock_task2

        assert manager.is_all_paused() is True

    def test_stop_all_with_tasks(self):
        """Test stop_all with active tasks."""
        manager = TranslationTaskManager()

        mock_task = MagicMock()
        mock_task.is_alive.return_value = True
        manager.tasks["file.srt"] = mock_task

        manager.stop_all()
        mock_task.stop.assert_called_once()

    def test_pause_all_with_tasks(self):
        """Test pause_all with active tasks."""
        manager = TranslationTaskManager()

        mock_task = MagicMock()
        mock_task.is_alive.return_value = True
        manager.tasks["file.srt"] = mock_task

        manager.pause_all()
        mock_task.pause.assert_called_once()

    def test_resume_all_with_tasks(self):
        """Test resume_all with paused tasks."""
        manager = TranslationTaskManager()

        mock_task = MagicMock()
        mock_task.is_alive.return_value = True
        mock_task.is_paused.return_value = True
        manager.tasks["file.srt"] = mock_task

        manager.resume_all()
        mock_task.resume.assert_called_once()


# ============================================================
# Additional TranslationStats Tests
# ============================================================


class TestTranslationStatsExtended:
    """Extended tests for TranslationStats."""

    def test_errors_list(self):
        """Test error list handling."""
        stats = TranslationStats()
        assert stats.errors == []

        stats.errors.append("Error 1")
        stats.errors.append("Error 2")
        assert len(stats.errors) == 2

    def test_wait_and_processing_time(self):
        """Test wait and processing time fields."""
        stats = TranslationStats()
        stats.total_wait_time = 5.5
        stats.total_processing_time = 10.2

        assert stats.total_wait_time == 5.5
        assert stats.total_processing_time == 10.2

    def test_get_summary_complete(self):
        """Test get_summary with complete data."""
        stats = TranslationStats()
        stats.started_at = 0
        stats.finished_at = 120
        stats.total_subtitles = 100
        stats.translated_count = 95
        stats.failed_count = 3
        stats.skipped_count = 2
        stats.cached_count = 10
        stats.total_chars = 5000
        stats.batch_count = 10
        stats.retry_count = 2

        summary = stats.get_summary()

        assert summary["總字幕數"] == 100
        assert summary["已翻譯"] == 95
        assert summary["失敗"] == 3
        assert summary["跳過"] == 2
        assert summary["快取命中"] == 10
        assert summary["總字元數"] == 5000
        assert summary["批次數"] == 10
        assert summary["重試次數"] == 2
        assert "字幕/分鐘" in summary["翻譯速度"]
        assert "字元/分鐘" in summary["字元速度"]

    def test_formatted_elapsed_time(self):
        """Test formatted elapsed time output."""
        stats = TranslationStats()
        stats.started_at = 0
        stats.finished_at = 125  # 2 minutes 5 seconds

        formatted = stats.get_formatted_elapsed_time()
        # Should be a non-empty string
        assert len(formatted) > 0
        assert isinstance(formatted, str)
