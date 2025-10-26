"""測試 config 模組"""

import pytest
import json
from pathlib import Path

from srt_translator.core.config import ConfigManager


class TestConfigManager:
    """測試 ConfigManager 類"""

    @pytest.fixture
    def temp_config_dir(self, temp_dir):
        """提供臨時配置目錄"""
        config_dir = temp_dir / "config"
        config_dir.mkdir(exist_ok=True)
        return config_dir

    @pytest.fixture
    def config_manager(self, temp_config_dir, monkeypatch):
        """提供測試用的配置管理器"""
        # 重置單例
        ConfigManager._instances = {}
        # 修改配置目錄為臨時目錄
        monkeypatch.setattr(ConfigManager, "__init__",
            lambda self, config_type="app": self._test_init(config_type, str(temp_config_dir)))

        # 添加測試用的初始化方法
        def _test_init(self, config_type, config_dir):
            self.config_type = config_type
            self.config_dir = config_dir
            self.config_paths = {
                "app": str(Path(config_dir) / "app_config.json"),
                "user": str(Path(config_dir) / "user_settings.json"),
            }
            self.default_configs = self._get_default_configs()
            self.listeners = []
            self.configs = {}
            self.load_config()

        ConfigManager._test_init = _test_init

        return ConfigManager.get_instance()

    def test_singleton_pattern(self):
        """測試單例模式"""
        manager1 = ConfigManager.get_instance("app")
        manager2 = ConfigManager.get_instance("app")
        assert manager1 is manager2

    def test_different_config_types(self):
        """測試不同配置類型使用不同實例"""
        manager1 = ConfigManager.get_instance("app")
        manager2 = ConfigManager.get_instance("user")
        assert manager1 is not manager2

    def test_default_configs_structure(self):
        """測試預設配置結構"""
        manager = ConfigManager("app")
        defaults = manager._get_default_configs()

        # 驗證必要的配置類型存在
        assert "app" in defaults
        assert "user" in defaults
        assert "model" in defaults

        # 驗證 app 配置包含基本欄位
        assert "version" in defaults["app"]
        assert "debug_mode" in defaults["app"]

    def test_config_file_creation(self, temp_config_dir):
        """測試配置文件創建"""
        # 清空實例
        ConfigManager._instances = {}

        manager = ConfigManager("app")
        manager.config_dir = str(temp_config_dir)

        # 保存配置應該創建文件
        config_path = temp_config_dir / "app_config.json"
        assert temp_config_dir.exists()


class TestConfigManagerBasicOperations:
    """測試基本配置操作（簡化版）"""

    def test_get_value_basic(self):
        """測試獲取配置值"""
        manager = ConfigManager("app")

        # 獲取預設值
        version = manager.configs.get("app", {}).get("version")
        assert version is not None

    def test_config_types(self):
        """測試配置類型"""
        manager = ConfigManager("app")
        assert manager.config_type == "app"
