"""測試 cache 模組"""

import sqlite3
from pathlib import Path

import pytest

from srt_translator.core.cache import CacheManager


class TestCacheManager:
    """測試 CacheManager 類"""

    @pytest.fixture
    def cache_db_path(self, temp_dir):
        """提供臨時資料庫路徑"""
        return temp_dir / "test_cache.db"

    @pytest.fixture
    def cache_manager(self, cache_db_path, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        manager = CacheManager(str(cache_db_path))
        yield manager
        # 確保連線關閉
        if hasattr(manager, "conn") and manager.conn:
            manager.conn.close()

    def test_cache_manager_initialization(self, cache_manager, cache_db_path):
        """測試快取管理器初始化"""
        assert cache_manager is not None
        assert Path(cache_db_path).exists()

    def test_singleton_pattern(self, cache_db_path, ensure_cache_cleanup):
        """測試單例模式"""
        manager1 = CacheManager.get_instance(str(cache_db_path))
        manager2 = CacheManager.get_instance()

        try:
            assert manager1 is manager2
        finally:
            # 確保關閉連線
            if hasattr(manager1, "conn") and manager1.conn:
                manager1.conn.close()

    def test_database_initialization(self, cache_db_path, ensure_cache_cleanup):
        """測試資料庫初始化"""
        manager = CacheManager(str(cache_db_path))

        try:
            # 檢查資料庫文件存在
            assert Path(cache_db_path).exists()

            # 檢查表格存在
            with sqlite3.connect(str(cache_db_path)) as conn:
                cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='translations'")
                assert cursor.fetchone() is not None
        finally:
            # 確保關閉連線
            if hasattr(manager, "conn") and manager.conn:
                manager.conn.close()

    def test_cache_stats_initialization(self, cache_manager):
        """測試快取統計初始化"""
        assert "total_queries" in cache_manager.stats
        assert "cache_hits" in cache_manager.stats
        assert cache_manager.stats["total_queries"] == 0

    def test_memory_cache_initialization(self, cache_manager):
        """測試記憶體快取初始化"""
        assert cache_manager.memory_cache == {}
        assert cache_manager.max_memory_cache > 0


class TestCacheManagerOperations:
    """測試快取管理器操作（簡化版）"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        # 確保連線關閉
        if hasattr(manager, "conn") and manager.conn:
            manager.conn.close()

    def test_cache_initialization_creates_data_dir(self, temp_dir, ensure_cache_cleanup):
        """測試初始化時自動創建資料目錄"""
        cache_path = temp_dir / "new_data" / "cache.db"
        manager = CacheManager(str(cache_path))

        try:
            assert cache_path.parent.exists()
            assert cache_path.exists()
        finally:
            # 確保關閉連線
            if hasattr(manager, "conn") and manager.conn:
                manager.conn.close()

    def test_default_db_path_handling(self, ensure_cache_cleanup):
        """測試預設資料庫路徑處理"""
        manager = CacheManager(db_path=None)

        try:
            # 應該使用預設路徑
            assert manager.db_path is not None
            assert manager.db_path != ""
        finally:
            # 確保關閉連線
            if hasattr(manager, "conn") and manager.conn:
                manager.conn.close()


class TestCacheGetSet:
    """測試快取的 get/set 核心操作"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        # 確保連線關閉
        if hasattr(manager, "conn") and manager.conn:
            manager.conn.close()

    def test_store_and_get_translation_basic(self, cache_manager):
        """測試基本的儲存與獲取翻譯"""
        source = "Hello"
        target = "你好"
        context = ["greeting"]
        model = "gpt-4"

        # 儲存翻譯
        result = cache_manager.store_translation(source, target, context, model)
        assert result is True

        # 獲取翻譯
        cached = cache_manager.get_cached_translation(source, context, model)
        assert cached == target

    def test_get_translation_from_memory_cache(self, cache_manager):
        """測試從記憶體快取獲取翻譯"""
        source = "World"
        target = "世界"
        context = []
        model = "gpt-4"

        # 先儲存
        cache_manager.store_translation(source, target, context, model)

        # 第一次獲取（從資料庫載入到記憶體）
        cache_manager.get_cached_translation(source, context, model)

        # 第二次獲取（從記憶體快取）
        cached = cache_manager.get_cached_translation(source, context, model)
        assert cached == target
        assert cache_manager.stats["cache_hits"] == 2

    def test_get_translation_cache_miss(self, cache_manager):
        """測試快取未命中"""
        cached = cache_manager.get_cached_translation("Not exists", [], "gpt-4")
        assert cached is None
        assert cache_manager.stats["total_queries"] == 1
        assert cache_manager.stats["cache_hits"] == 0

    def test_store_empty_text_rejected(self, cache_manager):
        """測試拒絕儲存空文本"""
        result1 = cache_manager.store_translation("", "target", [], "gpt-4")
        result2 = cache_manager.store_translation("source", "", [], "gpt-4")
        result3 = cache_manager.store_translation("  ", "target", [], "gpt-4")

        assert result1 is False
        assert result2 is False
        assert result3 is False

    def test_get_empty_text_returns_empty(self, cache_manager):
        """測試獲取空文本返回空字串"""
        cached = cache_manager.get_cached_translation("", [], "gpt-4")
        assert cached == ""

    def test_context_affects_cache_key(self, cache_manager):
        """測試上下文影響快取鍵"""
        source = "test"
        target1 = "測試1"
        target2 = "測試2"
        context1 = ["context1"]
        context2 = ["context2"]
        model = "gpt-4"

        # 儲存相同源文本但不同上下文的翻譯
        cache_manager.store_translation(source, target1, context1, model)
        cache_manager.store_translation(source, target2, context2, model)

        # 驗證獲取到不同的翻譯
        assert cache_manager.get_cached_translation(source, context1, model) == target1
        assert cache_manager.get_cached_translation(source, context2, model) == target2

    def test_model_affects_cache_key(self, cache_manager):
        """測試模型名稱影響快取鍵"""
        source = "test"
        target1 = "測試GPT4"
        target2 = "測試Claude"
        context = []
        model1 = "gpt-4"
        model2 = "claude-3"

        # 儲存相同源文本但不同模型的翻譯
        cache_manager.store_translation(source, target1, context, model1)
        cache_manager.store_translation(source, target2, context, model2)

        # 驗證獲取到不同的翻譯
        assert cache_manager.get_cached_translation(source, context, model1) == target1
        assert cache_manager.get_cached_translation(source, context, model2) == target2


class TestCacheMemoryManagement:
    """測試記憶體快取管理"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器，設定小的記憶體快取限制"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        manager.max_memory_cache = 10  # 設定小的限制以便測試
        yield manager
        # 確保連線關閉
        if hasattr(manager, "conn") and manager.conn:
            manager.conn.close()

    def test_memory_cache_auto_cleanup(self, cache_manager):
        """測試記憶體快取自動清理"""
        # 儲存超過限制的項目
        for i in range(15):
            cache_manager.store_translation(f"source{i}", f"target{i}", [], "gpt-4")

        # 記憶體快取應該被清理
        assert len(cache_manager.memory_cache) <= cache_manager.max_memory_cache

    def test_memory_cache_lru_cleanup(self, cache_manager):
        """測試記憶體快取 LRU 清理策略"""
        # 儲存 10 個項目
        for i in range(10):
            cache_manager.store_translation(f"source{i}", f"target{i}", [], "gpt-4")

        # 存取前 5 個項目（更新它們的 last_accessed）
        for i in range(5):
            cache_manager.get_cached_translation(f"source{i}", [], "gpt-4")

        # 儲存更多項目觸發清理
        for i in range(10, 15):
            cache_manager.store_translation(f"source{i}", f"target{i}", [], "gpt-4")

        # 最近使用的項目應該還在記憶體中（可從資料庫載入）
        for i in range(5):
            cached = cache_manager.get_cached_translation(f"source{i}", [], "gpt-4")
            assert cached == f"target{i}"


class TestCacheDatabaseMaintenance:
    """測試資料庫維護功能"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        # 確保連線關閉
        if hasattr(manager, "conn") and manager.conn:
            manager.conn.close()

    def test_create_backup(self, cache_manager, temp_dir):
        """測試建立資料庫備份"""
        # 先儲存一些數據
        cache_manager.store_translation("test", "測試", [], "gpt-4")

        # 建立備份
        result = cache_manager._create_backup()
        assert result is True

        # 驗證備份檔案存在
        backup_path = Path(cache_manager.db_path + ".bak")
        assert backup_path.exists()

    def test_clear_old_cache(self, cache_manager):
        """測試清理過期快取"""
        # 儲存一些翻譯
        for i in range(5):
            cache_manager.store_translation(f"old{i}", f"舊{i}", [], "gpt-4")

        # 清理過期快取（設定閾值為 0 天，應該全部清理）
        deleted = cache_manager.clear_old_cache(days_threshold=0)
        assert deleted == 5

    def test_clear_cache_by_model(self, cache_manager):
        """測試按模型清理快取"""
        # 儲存不同模型的翻譯
        cache_manager.store_translation("test1", "測試1", [], "gpt-4")
        cache_manager.store_translation("test2", "測試2", [], "gpt-4")
        cache_manager.store_translation("test3", "測試3", [], "claude-3")

        # 清理 gpt-4 的快取
        deleted = cache_manager.clear_cache_by_model("gpt-4")
        assert deleted == 2

        # 驗證 gpt-4 的快取已清除
        assert cache_manager.get_cached_translation("test1", [], "gpt-4") is None
        assert cache_manager.get_cached_translation("test2", [], "gpt-4") is None

        # 驗證 claude-3 的快取仍存在
        assert cache_manager.get_cached_translation("test3", [], "claude-3") == "測試3"

    def test_clear_all_cache(self, cache_manager):
        """測試清空所有快取"""
        # 儲存一些翻譯
        cache_manager.store_translation("test1", "測試1", [], "gpt-4")
        cache_manager.store_translation("test2", "測試2", [], "claude-3")

        # 清空所有快取
        result = cache_manager.clear_all_cache()
        assert result is True

        # 驗證快取已清空
        assert cache_manager.get_cached_translation("test1", [], "gpt-4") is None
        assert cache_manager.get_cached_translation("test2", [], "claude-3") is None
        assert len(cache_manager.memory_cache) == 0

    def test_optimize_database(self, cache_manager):
        """測試資料庫最佳化"""
        # 儲存一些數據
        for i in range(10):
            cache_manager.store_translation(f"test{i}", f"測試{i}", [], "gpt-4")

        # 執行最佳化
        result = cache_manager.optimize_database()
        assert result is True


class TestCacheStatistics:
    """測試快取統計與查詢功能"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        # 確保連線關閉
        if hasattr(manager, "conn") and manager.conn:
            manager.conn.close()

    def test_get_cache_stats_basic(self, cache_manager):
        """測試獲取基本統計資訊"""
        # 儲存一些翻譯
        cache_manager.store_translation("test1", "測試1", [], "gpt-4")
        cache_manager.store_translation("test2", "測試2", [], "gpt-4")

        # 獲取統計
        stats = cache_manager.get_cache_stats()

        assert "total_records" in stats
        assert stats["total_records"] == 2
        assert "db_size_mb" in stats
        assert "models" in stats
        assert "gpt-4" in stats["models"]

    def test_get_cache_stats_hit_rate(self, cache_manager):
        """測試快取命中率統計"""
        # 儲存翻譯
        cache_manager.store_translation("test", "測試", [], "gpt-4")

        # 執行查詢（1 次命中，1 次未命中）
        cache_manager.get_cached_translation("test", [], "gpt-4")  # 命中
        cache_manager.get_cached_translation("not_exists", [], "gpt-4")  # 未命中

        stats = cache_manager.get_cache_stats()
        assert stats["total_queries"] == 2
        assert stats["cache_hits"] == 1
        assert stats["hit_rate"] == 50.0

    def test_search_cache_basic(self, cache_manager):
        """測試基本的快取搜尋"""
        # 儲存一些翻譯
        cache_manager.store_translation("Hello world", "你好世界", [], "gpt-4")
        cache_manager.store_translation("Hello there", "你好那裡", [], "gpt-4")
        cache_manager.store_translation("Goodbye", "再見", [], "gpt-4")

        # 搜尋包含 "Hello" 的快取
        results = cache_manager.search_cache("Hello")
        assert len(results) == 2

        # 驗證結果內容
        assert any("Hello world" in r["source_text"] for r in results)
        assert any("Hello there" in r["source_text"] for r in results)

    def test_search_cache_with_model_filter(self, cache_manager):
        """測試帶模型過濾的快取搜尋"""
        # 儲存不同模型的翻譯
        cache_manager.store_translation("test", "測試1", [], "gpt-4")
        cache_manager.store_translation("test", "測試2", [], "claude-3")

        # 搜尋特定模型
        results = cache_manager.search_cache("test", model_name="gpt-4")
        assert len(results) == 1
        assert results[0]["model_name"] == "gpt-4"


class TestCacheImportExport:
    """測試快取匯入匯出功能"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        # 確保連線關閉
        if hasattr(manager, "conn") and manager.conn:
            manager.conn.close()

    def test_export_cache(self, cache_manager, temp_dir):
        """測試匯出快取"""
        # 儲存一些翻譯
        cache_manager.store_translation("test1", "測試1", [], "gpt-4")
        cache_manager.store_translation("test2", "測試2", ["context"], "claude-3")

        # 匯出快取
        export_path = temp_dir / "exported_cache.json"
        result = cache_manager.export_cache(str(export_path))
        assert result is True

        # 驗證匯出檔案存在且內容正確
        assert export_path.exists()

        import json

        with open(export_path, encoding="utf-8") as f:
            data = json.load(f)

        assert "version" in data
        assert "entries" in data
        assert len(data["entries"]) == 2

    def test_import_cache(self, cache_manager, temp_dir):
        """測試匯入快取"""
        # 先匯出一些數據
        cache_manager.store_translation("test1", "測試1", [], "gpt-4")
        export_path = temp_dir / "test_export.json"
        cache_manager.export_cache(str(export_path))

        # 清空快取
        cache_manager.clear_all_cache()

        # 匯入快取
        success, count = cache_manager.import_cache(str(export_path))
        assert success is True
        assert count == 1

        # 驗證數據已匯入
        cached = cache_manager.get_cached_translation("test1", [], "gpt-4")
        assert cached == "測試1"

    def test_import_cache_file_not_found(self, cache_manager):
        """測試匯入不存在的檔案"""
        success, count = cache_manager.import_cache("not_exists.json")
        assert success is False
        assert count == 0


class TestCacheConfigAndMaintenance:
    """測試快取配置與維護功能"""

    @pytest.fixture
    def cache_manager(self, temp_dir, ensure_cache_cleanup):
        """提供測試用的快取管理器"""
        cache_path = temp_dir / "test_cache.db"
        manager = CacheManager(str(cache_path))
        yield manager
        # 確保連線關閉
        if hasattr(manager, "conn") and manager.conn:
            manager.conn.close()

    def test_update_config(self, cache_manager):
        """測試更新配置"""
        # 修改配置
        from srt_translator.core.config import ConfigManager

        config = ConfigManager.get_instance("cache")
        config.set_value("max_memory_cache", 50)
        config.set_value("auto_cleanup_days", 15)

        # 更新快取管理器配置
        cache_manager.update_config()

        assert cache_manager.max_memory_cache == 50
        assert cache_manager.auto_cleanup_days == 15

    def test_update_config_triggers_memory_cleanup(self, cache_manager):
        """測試更新配置時觸發記憶體清理"""
        # 先儲存一些數據
        for i in range(20):
            cache_manager.store_translation(f"test{i}", f"測試{i}", [], "gpt-4")

        # 降低記憶體快取限制
        from srt_translator.core.config import ConfigManager

        config = ConfigManager.get_instance("cache")
        config.set_value("max_memory_cache", 5)

        # 更新配置應該觸發清理
        cache_manager.update_config()
        assert len(cache_manager.memory_cache) <= 5

    def test_database_error_handling_on_get(self, cache_manager, temp_dir):
        """測試獲取快取時的資料庫錯誤處理"""
        # 儲存一個翻譯
        cache_manager.store_translation("test", "測試", [], "gpt-4")

        # 關閉並刪除資料庫以模擬錯誤
        db_path = cache_manager.db_path
        # 先清空記憶體快取
        cache_manager.memory_cache.clear()

        # 破壞資料庫路徑（讓查詢失敗）
        original_path = cache_manager.db_path
        cache_manager.db_path = str(temp_dir / "nonexistent" / "cache.db")

        # 嘗試獲取應該返回 None 並記錄錯誤
        result = cache_manager.get_cached_translation("test", [], "gpt-4")
        assert result is None
        assert cache_manager.stats["db_errors"] > 0

        # 恢復路徑
        cache_manager.db_path = original_path

    def test_database_error_handling_on_store(self, cache_manager, temp_dir):
        """測試儲存快取時的資料庫錯誤處理"""
        # 破壞資料庫路徑
        cache_manager.db_path = str(temp_dir / "nonexistent" / "cache.db")

        # 嘗試儲存應該返回 False 並記錄錯誤
        result = cache_manager.store_translation("test", "測試", [], "gpt-4")
        assert result is False

    def test_cache_version_check_new_database(self, cache_manager):
        """測試新資料庫的版本檢查"""
        # 新建的資料庫應該設定版本
        import sqlite3

        with sqlite3.connect(cache_manager.db_path) as conn:
            cursor = conn.execute("SELECT value FROM cache_metadata WHERE key = 'version'")
            result = cursor.fetchone()
            assert result is not None
            # 版本應該是當前版本
            from srt_translator.core.cache import CACHE_VERSION

            assert result[0] == CACHE_VERSION

    def test_compute_context_hash(self, cache_manager):
        """測試上下文雜湊計算"""
        context1 = ["Hello", "World"]
        context2 = ["Hello", "World"]
        context3 = ["Different", "Context"]

        hash1 = cache_manager._compute_context_hash(tuple(context1))
        hash2 = cache_manager._compute_context_hash(tuple(context2))
        hash3 = cache_manager._compute_context_hash(tuple(context3))

        # 相同上下文應該產生相同雜湊
        assert hash1 == hash2
        # 不同上下文應該產生不同雜湊
        assert hash1 != hash3

    def test_generate_cache_key(self, cache_manager):
        """測試快取鍵生成"""
        source = "test"
        context_hash = "abc123"
        model = "gpt-4"

        key = cache_manager._generate_cache_key(source, context_hash, model)
        assert source in key
        assert context_hash in key
        assert model in key
        assert key == f"{source}|{context_hash}|{model}"
