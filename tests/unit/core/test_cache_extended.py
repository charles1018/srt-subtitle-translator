"""擴展測試 CacheManager - 提升覆蓋率

此檔案包含 CacheManager 的擴展測試，專注於：
1. 資料庫初始化與復原的錯誤處理
2. 快取版本檢查與遷移
3. 備份與還原功能
4. 錯誤處理與邊界案例
5. 批量操作與優化
"""

import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from srt_translator.core.cache import CACHE_VERSION, CacheManager

# ============================================================
# 資料庫初始化與復原測試
# ============================================================


class TestCacheDatabase:
    """測試資料庫初始化與復原"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        CacheManager._instance = None

    def test_init_with_empty_db_path(self, temp_dir, ensure_cache_cleanup):
        """測試空的資料庫路徑（應使用預設值）"""
        manager = CacheManager("")
        assert manager.db_path == "data/translation_cache.db"
        CacheManager._instance = None

    def test_init_with_none_db_path(self, temp_dir, ensure_cache_cleanup):
        """測試 None 資料庫路徑（應使用預設值）"""
        manager = CacheManager(None)
        assert manager.db_path == "data/translation_cache.db"
        CacheManager._instance = None

    def test_recover_db_with_backup(self, temp_dir, ensure_cache_cleanup):
        """測試從備份復原資料庫"""
        cache_path = temp_dir / "test_cache.db"
        backup_path = temp_dir / "test_cache.db.bak"

        # 創建備份文件
        manager = CacheManager(str(cache_path))
        manager.store_translation("test", "測試", [], "model1")
        shutil.copy(cache_path, backup_path)

        # 損壞原資料庫
        with open(cache_path, "w") as f:
            f.write("corrupted data")

        # 嘗試復原
        manager._recover_db_if_needed()
        assert cache_path.exists()

        CacheManager._instance = None

    def test_recover_db_without_backup(self, temp_dir, ensure_cache_cleanup):
        """測試無備份時復原資料庫（重新創建）"""
        cache_path = temp_dir / "corrupt_cache.db"

        # 創建損壞的資料庫
        with open(cache_path, "w") as f:
            f.write("corrupted")

        manager = CacheManager(str(cache_path))
        manager._recover_db_if_needed()

        # 應該重新創建
        assert cache_path.exists()
        CacheManager._instance = None

    def test_cache_version_mismatch(self, temp_dir, ensure_cache_cleanup):
        """測試快取版本不匹配時清理舊數據"""
        cache_path = temp_dir / "version_cache.db"

        # 創建舊版本快取
        with sqlite3.connect(str(cache_path)) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS translations (
                    source_text TEXT,
                    target_text TEXT,
                    context_hash TEXT,
                    model_name TEXT,
                    created_at timestamp,
                    usage_count INTEGER,
                    last_used timestamp,
                    PRIMARY KEY (source_text, context_hash, model_name)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)
            conn.execute("INSERT INTO cache_metadata (key, value) VALUES (?, ?)", ("version", "0.9"))
            conn.execute(
                """
                INSERT INTO translations
                (source_text, target_text, context_hash, model_name, created_at, usage_count, last_used)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                ("old", "舊的", "hash", "model", datetime.now(), 1, datetime.now()),
            )

        # 創建管理器（應該清理舊數據）
        manager = CacheManager(str(cache_path))

        # 檢查資料已清理
        with sqlite3.connect(str(cache_path)) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM translations")
            assert cursor.fetchone()[0] == 0

        CacheManager._instance = None

    def test_create_backup_success(self, cache_manager):
        """測試成功創建備份"""
        result = cache_manager._create_backup()
        assert result is True
        backup_path = f"{cache_manager.db_path}.bak"
        assert Path(backup_path).exists()

    @patch("shutil.copy")
    def test_create_backup_failure(self, mock_copy, cache_manager):
        """測試備份失敗"""
        mock_copy.side_effect = Exception("Backup failed")
        result = cache_manager._create_backup()
        assert result is False


# ============================================================
# 快取操作擴展測試
# ============================================================


class TestCacheOperationsExtended:
    """測試快取操作的擴展功能"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        CacheManager._instance = None

    def test_store_empty_source_text(self, cache_manager):
        """測試儲存空的原文"""
        result = cache_manager.store_translation("", "翻譯", [], "model1")
        assert result is False

    def test_store_empty_target_text(self, cache_manager):
        """測試儲存空的譯文"""
        result = cache_manager.store_translation("源文本", "", [], "model1")
        assert result is False

    def test_get_empty_source_text(self, cache_manager):
        """測試獲取空的原文"""
        result = cache_manager.get_cached_translation("", [], "model1")
        assert result == ""

    def test_get_whitespace_only_source_text(self, cache_manager):
        """測試獲取只有空白字符的原文"""
        result = cache_manager.get_cached_translation("   ", [], "model1")
        assert result == ""

    def test_memory_cache_cleanup_trigger(self, cache_manager):
        """測試記憶體快取清理觸發

        清理策略：
        - 觸發閾值: max_memory_cache * CLEANUP_TRIGGER_RATIO (預設 120%)
        - 保留數量: max_memory_cache * CLEANUP_KEEP_RATIO (預設 70%)
        """
        # 設置較小的最大快取
        cache_manager.max_memory_cache = 5
        trigger_threshold = int(5 * CacheManager.CLEANUP_TRIGGER_RATIO)  # 6
        keep_count = int(5 * CacheManager.CLEANUP_KEEP_RATIO)  # 3

        # 填滿快取 (10 項會觸發多次清理)
        for i in range(10):
            cache_manager.store_translation(f"text{i}", f"譯文{i}", [], "model1")

        # 記憶體快取應該在清理後保持在合理範圍內
        # 清理後保留 keep_count 項，然後可能再加入幾項直到再次觸發
        # 最終大小應 <= trigger_threshold (因為超過才會觸發清理)
        assert len(cache_manager.memory_cache) <= trigger_threshold

    def test_memory_cache_cleanup_skip_when_small(self, cache_manager):
        """測試記憶體快取太小時跳過清理"""
        cache_manager.max_memory_cache = 100
        cache_manager.memory_cache = {"key1": {"target_text": "text", "last_accessed": 1}}

        # 呼叫清理（應該跳過）
        cache_manager._clean_memory_cache()
        assert len(cache_manager.memory_cache) == 1

    @patch("sqlite3.connect")
    def test_get_cached_translation_db_error(self, mock_connect, cache_manager):
        """測試獲取翻譯時資料庫錯誤"""
        mock_connect.side_effect = sqlite3.Error("Database error")

        result = cache_manager.get_cached_translation("test", [], "model1")
        assert result is None
        assert cache_manager.stats["db_errors"] > 0

    @patch("sqlite3.connect")
    def test_store_translation_db_error(self, mock_connect, cache_manager):
        """測試儲存翻譯時資料庫錯誤"""
        # 先成功一次初始化資料庫
        cache_manager.store_translation("test", "測試", [], "model1")

        # 然後模擬錯誤
        mock_connect.side_effect = sqlite3.Error("Database error")
        result = cache_manager.store_translation("new", "新的", [], "model1")
        assert result is False


# ============================================================
# 清理與維護測試
# ============================================================


class TestCacheCleanup:
    """測試快取清理與維護功能"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        CacheManager._instance = None

    def test_auto_cleanup_skip_recent(self, cache_manager):
        """測試自動清理跳過最近清理過的"""
        # 設置上次清理時間為現在
        with sqlite3.connect(cache_manager.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)",
                ("last_cleanup", datetime.now().isoformat()),
            )

        # 再次嘗試清理（應該跳過）
        with sqlite3.connect(cache_manager.db_path) as conn:
            cache_manager._auto_cleanup(conn)

    def test_auto_cleanup_invalid_date_format(self, cache_manager):
        """測試自動清理時處理無效日期格式"""
        # 設置無效的日期格式
        with sqlite3.connect(cache_manager.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO cache_metadata (key, value) VALUES (?, ?)", ("last_cleanup", "invalid_date")
            )

            # 執行清理（應該繼續執行）
            cache_manager._auto_cleanup(conn, days_threshold=1)

    def test_clear_old_cache_with_custom_threshold(self, cache_manager):
        """測試使用自定義閾值清理舊快取"""
        # 添加舊快取
        old_date = datetime.now() - timedelta(days=60)
        with sqlite3.connect(cache_manager.db_path) as conn:
            conn.execute(
                """
                INSERT INTO translations
                (source_text, target_text, context_hash, model_name, created_at, usage_count, last_used)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                ("old", "舊的", "hash", "model", old_date, 1, old_date),
            )

        # 清理超過 30 天的
        deleted = cache_manager.clear_old_cache(days_threshold=30)
        assert deleted >= 1

    @patch("sqlite3.connect")
    def test_clear_old_cache_db_error(self, mock_connect, cache_manager):
        """測試清理舊快取時資料庫錯誤"""
        mock_connect.side_effect = sqlite3.Error("Database error")
        deleted = cache_manager.clear_old_cache()
        assert deleted == 0

    def test_clear_cache_by_model_success(self, cache_manager):
        """測試按模型清理快取"""
        # 添加不同模型的快取
        cache_manager.store_translation("text1", "譯文1", [], "model_a")
        cache_manager.store_translation("text2", "譯文2", [], "model_b")

        # 清理 model_a
        deleted = cache_manager.clear_cache_by_model("model_a")
        assert deleted >= 1

        # 驗證 model_a 的快取已被清除
        result = cache_manager.get_cached_translation("text1", [], "model_a")
        assert result is None

        # model_b 的快取應該還在
        result = cache_manager.get_cached_translation("text2", [], "model_b")
        assert result == "譯文2"

    @patch("sqlite3.connect")
    def test_clear_cache_by_model_db_error(self, mock_connect, cache_manager):
        """測試按模型清理時資料庫錯誤"""
        mock_connect.side_effect = sqlite3.Error("Database error")
        deleted = cache_manager.clear_cache_by_model("model1")
        assert deleted == 0

    def test_optimize_database_success(self, cache_manager):
        """測試優化資料庫"""
        result = cache_manager.optimize_database()
        assert result is True

    @patch("sqlite3.connect")
    def test_optimize_database_error(self, mock_connect, cache_manager):
        """測試優化資料庫錯誤"""
        mock_connect.side_effect = sqlite3.Error("Optimization error")
        result = cache_manager.optimize_database()
        assert result is False

    def test_clear_all_cache_success(self, cache_manager):
        """測試清空所有快取"""
        # 添加一些快取
        cache_manager.store_translation("text1", "譯文1", [], "model1")
        cache_manager.store_translation("text2", "譯文2", [], "model2")

        # 清空
        result = cache_manager.clear_all_cache()
        assert result is True

        # 驗證已清空
        stats = cache_manager.get_cache_stats()
        assert stats.get("total_records", 0) == 0
        assert len(cache_manager.memory_cache) == 0

    @patch("sqlite3.connect")
    def test_clear_all_cache_error(self, mock_connect, cache_manager):
        """測試清空快取時錯誤"""
        # 先成功一次
        cache_manager.clear_all_cache()

        # 然後模擬錯誤
        mock_connect.side_effect = sqlite3.Error("Clear error")
        result = cache_manager.clear_all_cache()
        assert result is False


# ============================================================
# 匯入匯出測試
# ============================================================


class TestCacheImportExport:
    """測試快取匯入匯出功能"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        CacheManager._instance = None

    def test_export_cache_success(self, cache_manager, temp_dir):
        """測試匯出快取"""
        # 添加快取
        cache_manager.store_translation("hello", "你好", [], "model1")

        export_path = temp_dir / "export.json"
        result = cache_manager.export_cache(str(export_path))
        assert result is True
        assert export_path.exists()

        # 驗證內容
        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)
        assert "version" in data
        assert "entries" in data
        assert len(data["entries"]) >= 1

    @patch("builtins.open")
    def test_export_cache_error(self, mock_open, cache_manager, temp_dir):
        """測試匯出快取錯誤"""
        mock_open.side_effect = Exception("Export error")
        result = cache_manager.export_cache(str(temp_dir / "export.json"))
        assert result is False

    def test_import_cache_file_not_found(self, cache_manager):
        """測試匯入不存在的文件"""
        result, count = cache_manager.import_cache("nonexistent.json")
        assert result is False
        assert count == 0

    def test_import_cache_version_mismatch(self, cache_manager, temp_dir):
        """測試匯入版本不匹配的快取"""
        # 創建版本不匹配的匯出文件
        export_path = temp_dir / "old_version.json"
        data = {"version": "0.5", "entries": []}
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result, count = cache_manager.import_cache(str(export_path))
        assert result is False
        assert count == 0

    def test_import_cache_missing_fields(self, cache_manager, temp_dir):
        """測試匯入缺少必要欄位的條目"""
        export_path = temp_dir / "invalid_entries.json"
        data = {
            "version": CACHE_VERSION,
            "entries": [
                {"source_text": "test"},  # 缺少必要欄位
                {
                    "source_text": "hello",
                    "target_text": "你好",
                    "context_hash": "hash",
                    "model_name": "model1",
                },  # 有效條目
            ],
        }
        with open(export_path, "w", encoding="utf-8") as f:
            json.dump(data, f)

        result, count = cache_manager.import_cache(str(export_path))
        assert result is True
        assert count == 1  # 只匯入了1個有效條目

    @patch("builtins.open")
    def test_import_cache_error(self, mock_open, cache_manager):
        """測試匯入快取錯誤"""
        mock_open.side_effect = Exception("Import error")
        result, count = cache_manager.import_cache("test.json")
        assert result is False
        assert count == 0


# ============================================================
# 統計與搜尋測試
# ============================================================


class TestCacheStatsAndSearch:
    """測試快取統計與搜尋功能"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        CacheManager._instance = None

    def test_get_cache_stats_comprehensive(self, cache_manager):
        """測試獲取完整統計信息"""
        # 添加多個快取
        for i in range(5):
            cache_manager.store_translation(f"text{i}", f"譯文{i}", [], "model1")

        # 多次獲取以增加使用次數
        for _ in range(3):
            cache_manager.get_cached_translation("text0", [], "model1")

        stats = cache_manager.get_cache_stats()

        assert "total_records" in stats
        assert "db_size_mb" in stats
        assert "models" in stats
        assert "top_used" in stats
        assert "hit_rate" in stats
        assert "memory_cache_size" in stats
        assert stats["total_records"] >= 5

    @patch("sqlite3.connect")
    def test_get_cache_stats_db_error(self, mock_connect, cache_manager):
        """測試獲取統計時資料庫錯誤"""
        mock_connect.side_effect = sqlite3.Error("Stats error")
        stats = cache_manager.get_cache_stats()
        # 應該返回基本統計
        assert isinstance(stats, dict)

    def test_search_cache_keyword(self, cache_manager):
        """測試搜尋快取（關鍵字）"""
        # 添加測試數據
        cache_manager.store_translation("apple", "蘋果", [], "model1")
        cache_manager.store_translation("banana", "香蕉", [], "model1")
        cache_manager.store_translation("cherry", "櫻桃", [], "model1")

        # 搜尋
        results = cache_manager.search_cache("apple")
        assert len(results) >= 1
        assert any("apple" in r["source_text"] for r in results)

    def test_search_cache_with_model_filter(self, cache_manager):
        """測試搜尋快取（指定模型）"""
        # 添加不同模型的數據
        cache_manager.store_translation("test", "測試", [], "model_a")
        cache_manager.store_translation("test", "試験", [], "model_b")

        # 搜尋特定模型
        results = cache_manager.search_cache("test", model_name="model_a")
        assert len(results) >= 1
        assert all(r["model_name"] == "model_a" for r in results)

    @patch("sqlite3.connect")
    def test_search_cache_db_error(self, mock_connect, cache_manager):
        """測試搜尋時資料庫錯誤"""
        mock_connect.side_effect = sqlite3.Error("Search error")
        results = cache_manager.search_cache("test")
        assert results == []

    def test_update_config(self, cache_manager):
        """測試更新配置"""
        # 設置較大的記憶體快取
        cache_manager.max_memory_cache = 5

        # 填滿快取
        for i in range(10):
            cache_manager.store_translation(f"text{i}", f"譯文{i}", [], "model1")

        # 更新配置（會觸發清理）
        cache_manager.update_config()

        # 驗證配置已更新
        assert cache_manager.max_memory_cache > 0


# ============================================================
# 哈希與鍵值生成測試
# ============================================================


class TestCacheHashingAndKeys:
    """測試快取哈希與鍵值生成"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        CacheManager._instance = None

    def test_compute_context_hash_consistency(self, cache_manager):
        """測試上下文哈希的一致性"""
        context1 = ("前一句", "當前句", "後一句")
        context2 = ("前一句", "當前句", "後一句")

        hash1 = cache_manager._compute_context_hash(context1)
        hash2 = cache_manager._compute_context_hash(context2)

        assert hash1 == hash2

    def test_compute_context_hash_different(self, cache_manager):
        """測試不同上下文產生不同哈希"""
        context1 = ("前", "中", "後")
        context2 = ("前", "中", "不同")

        hash1 = cache_manager._compute_context_hash(context1)
        hash2 = cache_manager._compute_context_hash(context2)

        assert hash1 != hash2

    def test_generate_cache_key(self, cache_manager):
        """測試生成快取鍵值"""
        key = cache_manager._generate_cache_key("source", "hash123", "model1")
        assert "source" in key
        assert "hash123" in key
        assert "model1" in key
        assert "|" in key
