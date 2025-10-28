"""快取整合測試

測試 CacheManager 與其他模組的整合互動。
"""

import pytest
from pathlib import Path

from srt_translator.core.cache import CacheManager
from srt_translator.core.config import ConfigManager


class TestCacheConfigIntegration:
    """測試快取與配置管理器的整合"""

    def test_cache_respects_config_settings(self, integration_env):
        """測試快取管理器遵循配置設定"""
        cache_manager = integration_env["cache_manager"]

        # 驗證快取管理器使用了配置中的設定
        assert cache_manager.max_memory_cache > 0
        assert cache_manager.auto_cleanup_days > 0

    def test_cache_config_update_triggers_cleanup(self, integration_env):
        """測試配置更新觸發快取清理"""
        cache_manager = integration_env["cache_manager"]

        # 儲存一些測試資料
        for i in range(20):
            cache_manager.store_translation(
                f"source_{i}",
                f"target_{i}",
                [],
                "test-model"
            )

        # 驗證記憶體快取有資料
        initial_cache_size = len(cache_manager.memory_cache)
        assert initial_cache_size > 0

        # 更新配置（降低記憶體快取限制）
        cache_manager.max_memory_cache = 5
        cache_manager.update_config()

        # 驗證記憶體快取被清理
        assert len(cache_manager.memory_cache) <= 5

    def test_cache_persistence_across_instances(self, integration_env):
        """測試快取在不同實例間的持久性"""
        cache_path = integration_env["cache_path"]

        # 第一個實例：儲存資料
        cache1 = CacheManager(str(cache_path))
        cache1.store_translation("hello", "你好", [], "gpt-4")

        # 關閉連線
        if hasattr(cache1, 'conn') and cache1.conn:
            cache1.conn.close()

        # 重置單例
        CacheManager._instance = None

        # 第二個實例：讀取資料
        cache2 = CacheManager(str(cache_path))
        cached = cache2.get_cached_translation("hello", [], "gpt-4")

        assert cached == "你好"

        # 清理
        if hasattr(cache2, 'conn') and cache2.conn:
            cache2.conn.close()


class TestCacheTranslationWorkflow:
    """測試快取在翻譯工作流程中的作用"""

    def test_cache_hit_scenario(self, integration_env, mock_translation_api):
        """測試快取命中場景"""
        cache_manager = integration_env["cache_manager"]

        # 第一次翻譯：快取未命中
        text = "Hello, world!"
        model = "gpt-4"

        # 模擬翻譯並儲存到快取
        translated = "你好，世界！"
        cache_manager.store_translation(text, translated, [], model)

        # 第二次翻譯：應該從快取獲取
        cached_result = cache_manager.get_cached_translation(text, [], model)
        assert cached_result == translated

        # 驗證統計資料
        stats = cache_manager.get_cache_stats()
        assert stats["cache_hits"] >= 1

    def test_cache_miss_and_store_workflow(self, integration_env):
        """測試快取未命中並儲存的工作流程"""
        cache_manager = integration_env["cache_manager"]

        text = "New text to translate"
        model = "claude-3"

        # 檢查快取（應該未命中）
        cached = cache_manager.get_cached_translation(text, [], model)
        assert cached is None

        # 模擬翻譯
        translated = "新的翻譯文字"

        # 儲存到快取
        result = cache_manager.store_translation(text, translated, [], model)
        assert result is True

        # 再次檢查快取（應該命中）
        cached = cache_manager.get_cached_translation(text, [], model)
        assert cached == translated

    def test_cache_with_context(self, integration_env):
        """測試帶上下文的快取"""
        cache_manager = integration_env["cache_manager"]

        text = "test"
        context1 = ["previous line 1"]
        context2 = ["previous line 2"]
        model = "gpt-4"

        # 儲存相同文字但不同上下文的翻譯
        cache_manager.store_translation(text, "測試1", context1, model)
        cache_manager.store_translation(text, "測試2", context2, model)

        # 驗證能正確區分不同上下文
        cached1 = cache_manager.get_cached_translation(text, context1, model)
        cached2 = cache_manager.get_cached_translation(text, context2, model)

        assert cached1 == "測試1"
        assert cached2 == "測試2"
        assert cached1 != cached2

    def test_cache_batch_operations(self, integration_env):
        """測試批量操作的快取效果"""
        cache_manager = integration_env["cache_manager"]
        model = "gpt-4"

        # 批量儲存
        texts = [f"text_{i}" for i in range(10)]
        translations = [f"翻譯_{i}" for i in range(10)]

        for text, translation in zip(texts, translations):
            cache_manager.store_translation(text, translation, [], model)

        # 批量讀取
        cached_translations = []
        for text in texts:
            cached = cache_manager.get_cached_translation(text, [], model)
            cached_translations.append(cached)

        # 驗證所有翻譯都正確快取
        assert cached_translations == translations

        # 驗證統計資料
        stats = cache_manager.get_cache_stats()
        assert stats["total_records"] >= 10
        assert stats["cache_hits"] >= 10


class TestCacheMaintenanceIntegration:
    """測試快取維護功能的整合"""

    def test_cache_cleanup_with_model_filter(self, integration_env):
        """測試按模型清理快取"""
        cache_manager = integration_env["cache_manager"]

        # 儲存不同模型的翻譯
        cache_manager.store_translation("test1", "測試1", [], "gpt-4")
        cache_manager.store_translation("test2", "測試2", [], "gpt-4")
        cache_manager.store_translation("test3", "測試3", [], "claude-3")

        # 清理特定模型的快取
        deleted = cache_manager.clear_cache_by_model("gpt-4")
        assert deleted == 2

        # 驗證只有 claude-3 的快取還存在
        assert cache_manager.get_cached_translation("test1", [], "gpt-4") is None
        assert cache_manager.get_cached_translation("test2", [], "gpt-4") is None
        assert cache_manager.get_cached_translation("test3", [], "claude-3") == "測試3"

    def test_cache_export_import_workflow(self, integration_env, temp_dir):
        """測試快取匯出匯入工作流程"""
        cache_manager = integration_env["cache_manager"]

        # 準備測試資料
        test_data = [
            ("hello", "你好", "gpt-4"),
            ("world", "世界", "gpt-4"),
            ("test", "測試", "claude-3"),
        ]

        for source, target, model in test_data:
            cache_manager.store_translation(source, target, [], model)

        # 匯出快取
        export_path = temp_dir / "cache_export.json"
        result = cache_manager.export_cache(str(export_path))
        assert result is True
        assert export_path.exists()

        # 清空快取
        cache_manager.clear_all_cache()

        # 匯入快取
        success, count = cache_manager.import_cache(str(export_path))
        assert success is True
        assert count == len(test_data)

        # 驗證資料已恢復
        for source, target, model in test_data:
            cached = cache_manager.get_cached_translation(source, [], model)
            assert cached == target

    def test_cache_statistics_tracking(self, integration_env):
        """測試快取統計追蹤"""
        cache_manager = integration_env["cache_manager"]

        # 執行一些操作
        cache_manager.store_translation("test1", "測試1", [], "gpt-4")
        cache_manager.get_cached_translation("test1", [], "gpt-4")  # 命中
        cache_manager.get_cached_translation("not_exist", [], "gpt-4")  # 未命中

        # 獲取統計資料
        stats = cache_manager.get_cache_stats()

        # 驗證統計資料
        assert stats["total_queries"] >= 2
        assert stats["cache_hits"] >= 1
        assert "hit_rate" in stats
        assert stats["total_records"] >= 1
        assert "gpt-4" in stats.get("models", {})
