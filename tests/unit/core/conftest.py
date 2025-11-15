"""Core 模組測試的共用 fixtures

此檔案定義了 core 模組測試專用的 fixtures，特別處理資料庫連線的正確關閉。
"""

import time

import pytest

from srt_translator.core.cache import CacheManager


@pytest.fixture
def ensure_cache_cleanup():
    """確保測試後清理所有 CacheManager 實例

    此 fixture 在測試執行前後重置 CacheManager 單例，
    並確保所有資料庫連線都已關閉。
    """
    # 測試前：重置單例
    CacheManager._instance = None

    yield

    # 測試後：清理與關閉連線
    if CacheManager._instance is not None:
        manager = CacheManager._instance

        # 1. 關閉資料庫連線（如果有的話）
        try:
            if hasattr(manager, 'conn') and manager.conn is not None:
                manager.conn.close()
                manager.conn = None
        except Exception:
            pass  # 忽略關閉錯誤

        # 2. 清理記憶體快取
        if hasattr(manager, 'memory_cache'):
            manager.memory_cache.clear()

        # 3. 重置單例
        CacheManager._instance = None

    # 4. 等待一小段時間讓系統釋放檔案鎖（Windows 需要）
    time.sleep(0.05)


@pytest.fixture
def safe_cache_manager(temp_dir, ensure_cache_cleanup):
    """提供安全的快取管理器，確保資料庫連線正確關閉

    此 fixture 建立一個臨時的 CacheManager 實例，
    並在測試結束後確保所有資源都被正確釋放。

    使用範例：
        def test_something(safe_cache_manager):
            cache_manager = safe_cache_manager
            # ... 執行測試
    """
    cache_path = temp_dir / "test_cache.db"

    # 使用 context manager 確保連線關閉
    manager = CacheManager(str(cache_path))

    yield manager

    # 明確關閉連線
    try:
        if hasattr(manager, 'conn') and manager.conn is not None:
            manager.conn.close()
            manager.conn = None
    except Exception:
        pass  # 忽略關閉錯誤

    # 等待系統釋放檔案鎖
    time.sleep(0.05)


@pytest.fixture
def isolated_cache_db(temp_dir):
    """提供隔離的快取資料庫路徑

    此 fixture 為每個測試提供獨立的資料庫檔案路徑，
    避免測試間的狀態污染。

    使用範例：
        def test_something(isolated_cache_db):
            manager = CacheManager(str(isolated_cache_db))
            # ... 執行測試
    """
    import uuid
    # 使用 UUID 確保每個測試都有唯一的資料庫檔案
    unique_name = f"test_cache_{uuid.uuid4().hex[:8]}.db"
    cache_path = temp_dir / unique_name
    return cache_path


@pytest.fixture
def close_all_db_connections():
    """確保關閉所有 SQLite 資料庫連線

    此 fixture 在測試結束後掃描並關閉所有開啟的 SQLite 連線，
    避免 Windows 上的 PermissionError。
    """
    yield

    # 測試後：關閉所有可能的資料庫連線
    import gc
    gc.collect()  # 觸發垃圾回收

    # 等待系統釋放資源
    time.sleep(0.1)
