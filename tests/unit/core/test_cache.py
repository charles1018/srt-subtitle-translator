"""測試 cache 模組"""

import pytest
import sqlite3
from pathlib import Path
import time

from srt_translator.core.cache import CacheManager


class TestCacheManager:
    """測試 CacheManager 類"""

    @pytest.fixture
    def cache_db_path(self, temp_dir):
        """提供臨時資料庫路徑"""
        return temp_dir / "test_cache.db"

    @pytest.fixture
    def cache_manager(self, cache_db_path):
        """提供測試用的快取管理器"""
        # 重置單例
        CacheManager._instance = None
        return CacheManager(str(cache_db_path))

    def test_cache_manager_initialization(self, cache_manager, cache_db_path):
        """測試快取管理器初始化"""
        assert cache_manager is not None
        assert Path(cache_db_path).exists()

    def test_singleton_pattern(self, cache_db_path):
        """測試單例模式"""
        CacheManager._instance = None
        manager1 = CacheManager.get_instance(str(cache_db_path))
        manager2 = CacheManager.get_instance()
        assert manager1 is manager2

    def test_database_initialization(self, cache_db_path):
        """測試資料庫初始化"""
        manager = CacheManager(str(cache_db_path))

        # 檢查資料庫文件存在
        assert Path(cache_db_path).exists()

        # 檢查表格存在
        with sqlite3.connect(str(cache_db_path)) as conn:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='translations'"
            )
            assert cursor.fetchone() is not None

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
    def cache_manager(self, temp_dir):
        """提供測試用的快取管理器"""
        CacheManager._instance = None
        cache_path = temp_dir / "test_cache.db"
        return CacheManager(str(cache_path))

    def test_cache_initialization_creates_data_dir(self, temp_dir):
        """測試初始化時自動創建資料目錄"""
        cache_path = temp_dir / "new_data" / "cache.db"
        manager = CacheManager(str(cache_path))

        assert cache_path.parent.exists()
        assert cache_path.exists()

    def test_default_db_path_handling(self):
        """測試預設資料庫路徑處理"""
        CacheManager._instance = None
        manager = CacheManager(db_path=None)

        # 應該使用預設路徑
        assert manager.db_path is not None
        assert manager.db_path != ""
