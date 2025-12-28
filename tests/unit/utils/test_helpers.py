"""測試 helpers 模組"""

import time

from srt_translator.utils.helpers import (
    # 快取工具
    MemoryCache,
    # 進度追踪工具
    ProgressTracker,
    # 文本處理工具
    clean_text,
    compute_text_hash,
    detect_language,
    # 時間和格式工具
    format_elapsed_time,
    format_file_size,
    # 字幕處理工具
    format_srt_time,
    generate_unique_filename,
    get_language_name,
    is_valid_subtitle_file,
    parse_srt_time,
    split_sentences,
    standardize_language_code,
    truncate_text,
)

# ============================================================
# 文本處理工具測試
# ============================================================


class TestTextProcessing:
    """測試文本處理工具"""

    def test_clean_text_basic(self):
        """測試基本文本清理"""
        text = "  Hello   World  "
        assert clean_text(text) == "Hello World"

    def test_clean_text_control_chars(self):
        """測試移除控制字符"""
        text = "Hello\x00\x1fWorld"
        result = clean_text(text)
        assert "\x00" not in result
        assert "\x1f" not in result

    def test_clean_text_empty(self):
        """測試空文本"""
        assert clean_text("") == ""
        assert clean_text(None) == ""

    def test_detect_language_japanese(self):
        """測試日文檢測"""
        text = "こんにちは世界"
        assert detect_language(text) == "ja"

    def test_detect_language_english(self):
        """測試英文檢測"""
        text = "Hello World, this is a test."
        assert detect_language(text) == "en"

    def test_detect_language_empty(self):
        """測試空文本語言檢測"""
        assert detect_language("") == "unknown"

    def test_standardize_language_code(self):
        """測試語言代碼標準化"""
        assert standardize_language_code("繁體中文") == "zh-tw"
        assert standardize_language_code("zh-tw") == "zh-tw"
        assert standardize_language_code("japanese") == "ja"
        assert standardize_language_code("en") == "en"
        assert standardize_language_code("invalid") == "unknown"

    def test_get_language_name(self):
        """測試語言代碼轉名稱"""
        assert get_language_name("zh-tw") == "繁體中文"
        assert get_language_name("ja") == "日文"
        assert get_language_name("en") == "英文"
        assert get_language_name("unknown") == "未知語言"

    def test_compute_text_hash(self):
        """測試文本哈希計算"""
        text1 = "Hello, World!"
        text2 = "Hello, World!"
        text3 = "Different text"

        hash1 = compute_text_hash(text1)
        hash2 = compute_text_hash(text2)
        hash3 = compute_text_hash(text3)

        # 相同文本應產生相同哈希
        assert hash1 == hash2
        # 不同文本應產生不同哈希
        assert hash1 != hash3
        # 哈希應該是 64 字符的十六進制字串（SHA-256）
        assert len(hash1) == 64

    def test_compute_text_hash_empty(self):
        """測試空文本哈希"""
        assert compute_text_hash("") == ""
        assert compute_text_hash(None) == ""

    def test_truncate_text_basic(self):
        """測試文本截斷"""
        text = "This is a very long text that needs to be truncated"
        result = truncate_text(text, max_length=20)
        assert len(result) <= 20
        assert result.endswith("...")

    def test_truncate_text_no_ellipsis(self):
        """測試不加省略號的截斷"""
        text = "Long text here"
        result = truncate_text(text, max_length=9, with_ellipsis=False)
        assert result == "Long text"

    def test_truncate_text_short(self):
        """測試短文本不截斷"""
        text = "Short"
        result = truncate_text(text, max_length=100)
        assert result == "Short"

    def test_split_sentences_mixed(self):
        """測試句子分割（中英混合）"""
        text = "Hello world! 你好世界。How are you? 很好！"
        sentences = split_sentences(text)
        assert len(sentences) > 0
        assert all(len(s.strip()) > 0 for s in sentences)

    def test_split_sentences_empty(self):
        """測試空文本分割"""
        assert split_sentences("") == []


# ============================================================
# 字幕處理工具測試
# ============================================================


class TestSubtitleProcessing:
    """測試字幕處理工具"""

    def test_format_srt_time_basic(self):
        """測試基本 SRT 時間格式化"""
        # 1小時2分3秒456毫秒 = 3723456 毫秒
        result = format_srt_time(3723456)
        assert result == "01:02:03,456"

    def test_format_srt_time_zero(self):
        """測試零時間"""
        result = format_srt_time(0)
        assert result == "00:00:00,000"

    def test_format_srt_time_negative(self):
        """測試負數時間（應轉為零）"""
        result = format_srt_time(-1000)
        assert result == "00:00:00,000"

    def test_parse_srt_time_basic(self):
        """測試基本 SRT 時間解析"""
        result = parse_srt_time("01:02:03,456")
        assert result == 3723456

    def test_parse_srt_time_with_dot(self):
        """測試使用點號的時間格式"""
        result = parse_srt_time("01:02:03.456")
        assert result == 3723456

    def test_parse_srt_time_invalid(self):
        """測試無效時間格式"""
        result = parse_srt_time("invalid")
        assert result == 0

    def test_parse_srt_time_empty(self):
        """測試空字串"""
        result = parse_srt_time("")
        assert result == 0

    def test_srt_time_roundtrip(self):
        """測試時間格式化與解析的往返轉換"""
        original = 3723456
        formatted = format_srt_time(original)
        parsed = parse_srt_time(formatted)
        assert parsed == original

    def test_generate_unique_filename_no_conflict(self, temp_dir):
        """測試無衝突時的文件名生成"""
        base_path = temp_dir / "test.txt"
        result = generate_unique_filename(str(base_path))
        assert result == str(base_path)

    def test_generate_unique_filename_with_conflict(self, temp_dir):
        """測試有衝突時的文件名生成"""
        # 創建原始文件
        original = temp_dir / "test.txt"
        original.write_text("content")

        # 生成唯一文件名
        result = generate_unique_filename(str(original))
        assert result != str(original)
        assert "_1" in result

    def test_is_valid_subtitle_file_srt(self, temp_dir, sample_srt_file):
        """測試有效的 SRT 文件檢查"""
        assert is_valid_subtitle_file(str(sample_srt_file)) is True

    def test_is_valid_subtitle_file_invalid_extension(self, temp_dir):
        """測試無效擴展名"""
        invalid_file = temp_dir / "test.txt"
        invalid_file.write_text("test")
        assert is_valid_subtitle_file(str(invalid_file)) is False

    def test_is_valid_subtitle_file_nonexistent(self):
        """測試不存在的文件"""
        assert is_valid_subtitle_file("nonexistent.srt") is False


# ============================================================
# 時間和格式工具測試
# ============================================================


class TestTimeAndFormat:
    """測試時間和格式工具"""

    def test_format_elapsed_time_seconds(self):
        """測試秒級時間格式化"""
        assert "秒" in format_elapsed_time(30)

    def test_format_elapsed_time_minutes(self):
        """測試分鐘級時間格式化"""
        result = format_elapsed_time(125)  # 2分5秒
        assert "分" in result
        assert "秒" in result

    def test_format_elapsed_time_hours(self):
        """測試小時級時間格式化"""
        result = format_elapsed_time(3665)  # 1小時1分5秒
        assert "小時" in result
        assert "分" in result

    def test_format_file_size_bytes(self):
        """測試字節級文件大小"""
        assert format_file_size(512) == "512 B"

    def test_format_file_size_kb(self):
        """測試 KB 級文件大小"""
        result = format_file_size(2048)
        assert "KB" in result

    def test_format_file_size_mb(self):
        """測試 MB 級文件大小"""
        result = format_file_size(1024 * 1024 * 5)
        assert "MB" in result

    def test_format_file_size_gb(self):
        """測試 GB 級文件大小"""
        result = format_file_size(1024 * 1024 * 1024 * 2)
        assert "GB" in result


# ============================================================
# 快取工具測試
# ============================================================


class TestMemoryCache:
    """測試 MemoryCache 類"""

    def test_cache_set_and_get(self):
        """測試基本的設置和獲取"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

    def test_cache_get_default(self):
        """測試獲取不存在的鍵返回默認值"""
        cache = MemoryCache()
        assert cache.get("nonexistent", "default") == "default"

    def test_cache_delete(self):
        """測試刪除快取項目"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        assert cache.delete("key1") is True
        assert cache.get("key1") is None

    def test_cache_clear(self):
        """測試清空快取"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.clear()
        assert cache.get("key1") is None
        assert cache.get("key2") is None

    def test_cache_expiration(self):
        """測試快取過期"""
        cache = MemoryCache(ttl=1)  # 1秒過期
        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # 等待過期
        time.sleep(1.1)
        assert cache.get("key1") is None

    def test_cache_stats(self):
        """測試快取統計"""
        cache = MemoryCache()
        cache.set("key1", "value1")
        cache.set("key2", "value2")

        stats = cache.get_stats()
        assert stats["size"] >= 2
        assert stats["max_size"] == 1000


# ============================================================
# 進度追踪工具測試
# ============================================================


class TestProgressTracker:
    """測試 ProgressTracker 類"""

    def test_progress_tracker_basic(self):
        """測試基本進度追踪"""
        tracker = ProgressTracker(total=10, description="測試任務")
        tracker.start()

        assert tracker.current == 0
        assert tracker.total == 10

        tracker.update(current=5)
        assert tracker.current == 5

    def test_progress_tracker_increment(self):
        """測試進度增量"""
        tracker = ProgressTracker(total=10)
        tracker.start()

        tracker.increment()
        assert tracker.current == 1

        tracker.increment(amount=3)
        assert tracker.current == 4

    def test_progress_tracker_complete(self):
        """測試完成進度"""
        tracker = ProgressTracker(total=10)
        tracker.start()
        tracker.complete()

        assert tracker.current == tracker.total

    def test_progress_tracker_percentage(self):
        """測試進度百分比"""
        tracker = ProgressTracker(total=100)
        tracker.start()
        tracker.update(current=50)

        assert tracker.get_progress_percentage() == 50.0

    def test_progress_tracker_callback(self):
        """測試進度回調"""
        callback_data = {}

        def test_callback(current, total, description, elapsed, remaining):
            callback_data["current"] = current
            callback_data["total"] = total

        tracker = ProgressTracker(total=10, callback=test_callback)
        tracker.start()
        tracker.update(current=5)

        assert callback_data["current"] == 5
        assert callback_data["total"] == 10
