"""Tests for translation/manager.py module."""

import asyncio
import hashlib
import json
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from srt_translator.services.factory import TranslationTaskManager
from srt_translator.translation.manager import (
    TranslationManager,
    TranslationStats,
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

    @patch("srt_translator.translation.manager.get_config")
    @patch("srt_translator.translation.manager.ServiceFactory.get_progress_service")
    @patch("srt_translator.translation.manager.ServiceFactory.get_cache_service")
    @patch("srt_translator.translation.manager.ServiceFactory.get_file_service")
    @patch("srt_translator.translation.manager.ServiceFactory.get_translation_service")
    def test_initialization(
        self,
        mock_get_translation_service,
        mock_get_file_service,
        mock_get_cache_service,
        mock_get_progress_service,
        mock_get_config,
        tmp_path,
    ):
        """Test TranslationManager initialization with service factory mocks."""
        checkpoints_dir = tmp_path / "checkpoints"
        mock_get_translation_service.return_value = MagicMock()
        mock_get_file_service.return_value = MagicMock()
        mock_get_cache_service.return_value = MagicMock()
        mock_get_progress_service.return_value = MagicMock()
        mock_get_config.side_effect = lambda section, key, default=None: {
            ("app", "checkpoints_dir"): str(checkpoints_dir),
            ("model", "context_window"): 5,
            ("model", "max_retries"): 4,
            ("model", "retry_delay"): 2.5,
        }.get((section, key), default)

        manager = TranslationManager(
            file_path="movie.srt",
            source_lang="英文",
            target_lang="繁體中文",
            model_name="gpt-4.1-mini",
            parallel_requests=3,
            progress_callback=None,
            complete_callback=None,
            display_mode="標準模式",
            llm_type="openai",
        )

        expected_hash = hashlib.md5("movie.srt_繁體中文_gpt-4.1-mini".encode()).hexdigest()[:10]
        assert manager.file_path == "movie.srt"
        assert manager.translation_service is mock_get_translation_service.return_value
        assert manager.file_service is mock_get_file_service.return_value
        assert manager.cache_service is mock_get_cache_service.return_value
        assert manager.progress_service is mock_get_progress_service.return_value
        assert manager.context_window == 5
        assert manager.max_retries == 4
        assert manager.retry_delay == 2.5
        assert manager.pause_event.is_set() is True
        assert manager.running is True
        assert manager.checkpoint_path == str(checkpoints_dir / f"checkpoint_{expected_hash}.json")
        assert manager._key_terms_dict == {}

    @patch("srt_translator.translation.manager.get_config", side_effect=lambda _s, _k, default=None: default)
    @patch("srt_translator.translation.manager.ServiceFactory.get_progress_service", return_value=MagicMock())
    @patch("srt_translator.translation.manager.ServiceFactory.get_cache_service", return_value=MagicMock())
    @patch("srt_translator.translation.manager.ServiceFactory.get_file_service", return_value=MagicMock())
    @patch("srt_translator.translation.manager.ServiceFactory.get_translation_service", return_value=MagicMock())
    def test_initialization_with_api_key(
        self,
        _mock_get_translation_service,
        _mock_get_file_service,
        _mock_get_cache_service,
        _mock_get_progress_service,
        _mock_get_config,
    ):
        """Test TranslationManager initialization with API key."""
        manager = TranslationManager(
            file_path="movie.srt",
            source_lang="英文",
            target_lang="繁體中文",
            model_name="gemini-1.5-flash",
            parallel_requests=2,
            progress_callback=None,
            complete_callback=None,
            display_mode="標準模式",
            llm_type="google",
            api_key="test-api-key",
        )

        assert manager.api_key == "test-api-key"
        assert manager.llm_type == "google"


class TestTranslationManagerPostProcess:
    """Tests for TranslationManager post-processing."""

    @patch("srt_translator.translation.manager.get_config")
    def test_post_process_simple(self, mock_get_config):
        """Test punctuation-stripping post-processing."""
        mock_get_config.side_effect = (
            lambda section, key, default=None: False if (section, key) == ("user", "preserve_punctuation") else default
        )
        manager = TranslationManager.__new__(TranslationManager)

        result = manager._post_process_translation("Hello, world!", " 哈囉，世界！ ")

        assert result == "哈囉 世界"

    @patch("srt_translator.translation.manager.get_config")
    def test_post_process_with_preserved_punctuation(self, mock_get_config):
        """Test punctuation-preserving post-processing."""
        mock_get_config.side_effect = (
            lambda section, key, default=None: True if (section, key) == ("user", "preserve_punctuation") else default
        )
        manager = TranslationManager.__new__(TranslationManager)

        result = manager._post_process_translation("Hello, world!", " 哈囉，世界！ ")

        assert result == "哈囉，世界！"


class TestTranslationManagerCheckpoint:
    """Tests for TranslationManager checkpoint functionality."""

    @patch("srt_translator.translation.manager.get_config")
    def test_get_checkpoint_path(self, mock_get_config, tmp_path):
        """Test checkpoint path generation."""
        checkpoints_dir = tmp_path / "checkpoints"
        mock_get_config.side_effect = (
            lambda section, key, default=None: str(checkpoints_dir)
            if (section, key) == ("app", "checkpoints_dir")
            else default
        )
        manager = TranslationManager.__new__(TranslationManager)
        manager.file_path = "movie.srt"
        manager.target_lang = "繁體中文"
        manager.model_name = "gpt-4.1-mini"

        checkpoint_path = manager._get_checkpoint_path()

        expected_hash = hashlib.md5("movie.srt_繁體中文_gpt-4.1-mini".encode()).hexdigest()[:10]
        assert checkpoint_path == str(checkpoints_dir / f"checkpoint_{expected_hash}.json")

    def test_save_checkpoint(self, tmp_path):
        """Test saving checkpoint with atomic write and backup."""
        checkpoint_path = tmp_path / "checkpoints" / "checkpoint.json"
        checkpoint_path.parent.mkdir(parents=True)
        checkpoint_path.write_text('{"old": true}', encoding="utf-8")

        manager = TranslationManager.__new__(TranslationManager)
        manager.checkpoint_path = str(checkpoint_path)
        manager.file_path = "movie.srt"
        manager.target_lang = "繁體中文"
        manager.model_name = "gpt-4.1-mini"
        manager.translated_indices = {1, 3}
        manager.stats = TranslationStats(total_subtitles=5, translated_count=2, errors=["err"])
        manager._key_terms_dict = {"Fed": "聯準會"}

        manager._save_checkpoint()

        checkpoint_data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        backup_data = json.loads(Path(f"{checkpoint_path}.bak").read_text(encoding="utf-8"))

        assert checkpoint_data["file_path"] == "movie.srt"
        assert checkpoint_data["target_lang"] == "繁體中文"
        assert checkpoint_data["model_name"] == "gpt-4.1-mini"
        assert set(checkpoint_data["translated_indices"]) == {1, 3}
        assert checkpoint_data["stats"]["translated_count"] == 2
        assert checkpoint_data["key_terms_dict"] == {"Fed": "聯準會"}
        assert backup_data == {"old": True}
        assert not Path(f"{checkpoint_path}.tmp").exists()

    def test_load_checkpoint_not_exists(self, tmp_path):
        """Test loading checkpoint when file doesn't exist."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.checkpoint_path = str(tmp_path / "missing.json")

        assert manager._load_checkpoint() is False


class TestTranslationManagerControl:
    """Tests for TranslationManager control methods."""

    def test_pause(self):
        """Test pausing translation."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.pause_event = asyncio.Event()
        manager.pause_event.set()
        manager._save_checkpoint = MagicMock()

        manager.pause()

        assert manager.pause_event.is_set() is False
        manager._save_checkpoint.assert_called_once()

    def test_resume(self):
        """Test resuming translation."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.pause_event = asyncio.Event()
        manager.pause_event.clear()

        manager.resume()

        assert manager.pause_event.is_set() is True

    def test_stop(self):
        """Test stopping translation."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.running = True
        manager.pause_event = asyncio.Event()
        manager.pause_event.clear()

        manager.stop()

        assert manager.running is False
        assert manager.pause_event.is_set() is True


class TestTranslationManagerEncoding:
    """Tests for TranslationManager encoding methods."""

    def test_get_subtitle_encoding_default(self):
        """Test falling back to UTF-8 when file info lookup fails."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.file_path = "movie.srt"
        manager.file_service = MagicMock()
        manager.file_service.get_subtitle_info.side_effect = RuntimeError("boom")

        assert manager._get_subtitle_encoding() == "utf-8"

    def test_get_subtitle_encoding_from_info(self):
        """Test getting encoding from subtitle info."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.file_path = "movie.srt"
        manager.file_service = MagicMock()
        manager.file_service.get_subtitle_info.return_value = {"編碼": "big5"}

        assert manager._get_subtitle_encoding() == "big5"


class TestTranslationManagerContextSnapshot:
    """Tests for immutable source-context snapshot behavior."""

    @pytest.mark.asyncio
    async def test_get_context_for_subtitle_uses_original_snapshot(self):
        """Context should come from the original snapshot, not mutated subtitle text."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.context_window = 1
        manager._source_text_snapshot = ["原文 A", "原文 B", "原文 C"]

        subs = [
            SimpleNamespace(text="譯文 A"),
            SimpleNamespace(text="譯文 B"),
            SimpleNamespace(text="原文 C"),
        ]

        context, current_index = await manager._get_context_for_subtitle(subs, 1)

        assert context == ["原文 A", "原文 B", "原文 C"]
        assert current_index == 1

    @pytest.mark.asyncio
    async def test_get_context_for_subtitle_falls_back_without_snapshot(self):
        """Without snapshot, context should fall back to current subtitle text."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.context_window = 1
        manager._source_text_snapshot = []

        subs = [
            SimpleNamespace(text="目前 A"),
            SimpleNamespace(text="目前 B"),
            SimpleNamespace(text="目前 C"),
        ]

        context, current_index = await manager._get_context_for_subtitle(subs, 1)

        assert context == ["目前 A", "目前 B", "目前 C"]
        assert current_index == 1


# ============================================================
# TranslationManager Lifecycle Tests
# ============================================================


class TestTranslationManagerLifecycle:
    """Tests for TranslationManager lifecycle helpers."""

    @pytest.mark.asyncio
    async def test_initialize_loads_checkpoint(self):
        """Test initialize delegates to checkpoint loading."""
        manager = TranslationManager.__new__(TranslationManager)
        manager.llm_type = "openai"
        manager.model_name = "gpt-4.1-mini"
        manager._load_checkpoint = MagicMock(return_value=True)

        await manager.initialize()

        manager._load_checkpoint.assert_called_once()

    @pytest.mark.asyncio
    async def test_cleanup_is_noop(self):
        """Test cleanup completes without touching managed services."""
        manager = TranslationManager.__new__(TranslationManager)

        await manager.cleanup()

    def test_capture_source_text_snapshot_and_get_source_text(self):
        """Test source snapshot capture prevents later subtitle mutation from leaking in."""
        manager = TranslationManager.__new__(TranslationManager)
        subs = [SimpleNamespace(text="原文 A"), SimpleNamespace(text="原文 B")]

        manager._capture_source_text_snapshot(subs)
        subs[0].text = "譯文 A"

        assert manager._source_text_snapshot == ["原文 A", "原文 B"]
        assert manager._get_source_text(subs, 0) == "原文 A"


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
