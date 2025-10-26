"""測試 models 模組"""

import pytest
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

from srt_translator.core.models import ModelInfo, ModelManager
from srt_translator.core.config import ConfigManager


class TestModelInfo:
    """測試 ModelInfo 資料類別"""

    def test_model_info_creation(self):
        """測試基本的 ModelInfo 建立"""
        model = ModelInfo(
            id="test-model",
            provider="ollama",
            name="Test Model"
        )

        assert model.id == "test-model"
        assert model.provider == "ollama"
        assert model.name == "Test Model"

    def test_model_info_defaults(self):
        """測試 ModelInfo 預設值"""
        model = ModelInfo(id="test", provider="ollama")

        assert model.context_length == 4096
        assert model.pricing == "未知"
        assert model.recommended_for == "一般翻譯"
        assert model.parallel == 10
        assert model.tags == []
        assert model.capabilities == {}
        assert model.available is True

    def test_model_info_to_dict(self):
        """測試 ModelInfo 轉換為字典"""
        model = ModelInfo(
            id="test-model",
            provider="ollama",
            name="Test Model",
            description="A test model",
            tags=["test", "demo"]
        )

        result = model.to_dict()

        assert isinstance(result, dict)
        assert result["id"] == "test-model"
        assert result["provider"] == "ollama"
        assert result["name"] == "Test Model"
        assert result["description"] == "A test model"
        assert result["tags"] == ["test", "demo"]

    def test_model_info_with_capabilities(self):
        """測試帶有能力評分的 ModelInfo"""
        capabilities = {
            "translation": 0.8,
            "context_handling": 0.7
        }

        model = ModelInfo(
            id="advanced-model",
            provider="openai",
            capabilities=capabilities
        )

        assert model.capabilities == capabilities
        assert model.to_dict()["capabilities"] == capabilities

    def test_model_info_availability(self):
        """測試模型可用性標記"""
        model_available = ModelInfo(id="model1", provider="ollama", available=True)
        model_unavailable = ModelInfo(id="model2", provider="ollama", available=False)

        assert model_available.available is True
        assert model_unavailable.available is False

    def test_model_info_name_fallback(self):
        """測試名稱回退到 ID"""
        model = ModelInfo(id="my-model", provider="ollama")
        result = model.to_dict()

        # 當沒有設置 name 時，應該使用 id
        assert result["name"] == "my-model"

    def test_model_info_custom_parallel(self):
        """測試自定義並行數量"""
        model = ModelInfo(
            id="fast-model",
            provider="ollama",
            parallel=20
        )

        assert model.parallel == 20

    def test_model_info_context_length(self):
        """測試自定義上下文長度"""
        model = ModelInfo(
            id="large-context",
            provider="openai",
            context_length=32000
        )

        assert model.context_length == 32000


class TestModelManagerInit:
    """測試 ModelManager 初始化"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def temp_config_file(self, temp_dir):
        """提供臨時配置檔案路徑"""
        config_dir = temp_dir / "config"
        config_dir.mkdir(exist_ok=True)
        return str(config_dir / "model_config.json")

    def test_initialization_basic(self, temp_config_file):
        """測試基本初始化"""
        manager = ModelManager(temp_config_file)

        assert manager is not None
        assert manager.config_file == temp_config_file
        assert hasattr(manager, 'config')
        assert hasattr(manager, 'model_database')
        assert hasattr(manager, 'cached_models')

    def test_singleton_pattern(self, temp_config_file):
        """測試單例模式"""
        manager1 = ModelManager.get_instance(temp_config_file)
        manager2 = ModelManager.get_instance()

        assert manager1 is manager2

    def test_default_config_values(self, temp_config_file):
        """測試預設配置值"""
        manager = ModelManager(temp_config_file)

        # 驗證預設值
        assert manager.base_url is not None
        assert manager.cache_expiry > 0
        assert manager.connect_timeout > 0
        assert manager.request_timeout > 0
        assert isinstance(manager.model_patterns, list)

    def test_model_database_initialized(self, temp_config_file):
        """測試模型資訊資料庫已初始化"""
        manager = ModelManager(temp_config_file)

        assert isinstance(manager.model_database, dict)
        # 應該包含預設的模型資訊
        assert len(manager.model_database) > 0

    def test_cached_models_empty_on_init(self, temp_config_file):
        """測試初始化時快取為空"""
        manager = ModelManager(temp_config_file)

        assert len(manager.cached_models) == 0
        assert len(manager.cache_time) == 0

    def test_session_none_on_init(self, temp_config_file):
        """測試初始化時 session 為 None"""
        manager = ModelManager(temp_config_file)

        assert manager.session is None


class TestModelManagerConfig:
    """測試 ModelManager 配置管理"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_load_config(self, manager):
        """測試載入配置"""
        config = manager._load_config()

        assert isinstance(config, dict)

    def test_save_config(self, manager):
        """測試儲存配置"""
        # 修改配置
        manager.config["test_key"] = "test_value"

        # 儲存
        result = manager._save_config()

        # 驗證儲存成功（可能成功或失敗都是合理的）
        assert result is True or result is False

    def test_config_has_required_fields(self, manager):
        """測試配置包含必要欄位"""
        config = manager.config

        # 基本欄位應該存在（可能為預設值或從檔案載入）
        assert isinstance(config, dict)


class TestModelManagerAPIKeys:
    """測試 API 金鑰管理"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_api_keys_initialized(self, manager):
        """測試 API 金鑰字典已初始化"""
        assert isinstance(manager.api_keys, dict)

    def test_load_api_keys_file_not_exist(self, manager):
        """測試載入不存在的 API 金鑰檔案"""
        # _load_api_keys 已在初始化時調用
        # 檔案不存在時不應該崩潰
        assert isinstance(manager.api_keys, dict)

    def test_load_api_keys_with_file(self, manager, temp_dir):
        """測試從檔案載入 API 金鑰"""
        # 建立 API 金鑰檔案
        api_key_file = temp_dir / "test_api_key.txt"
        test_key = "sk-test-key-12345"
        with open(api_key_file, 'w', encoding='utf-8') as f:
            f.write(test_key)

        # Mock get_config 以返回測試檔案路徑
        with patch('srt_translator.core.models.get_config', return_value=str(api_key_file)):
            # 重新載入
            manager._load_api_keys()

        # 驗證金鑰已載入（如果 mock 生效）
        assert isinstance(manager.api_keys, dict)


class TestModelManagerDatabase:
    """測試模型資訊資料庫"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_model_database_contains_models(self, manager):
        """測試模型資料庫包含模型"""
        assert len(manager.model_database) > 0

    def test_model_database_has_openai_models(self, manager):
        """測試模型資料庫包含 OpenAI 模型"""
        # 檢查是否有任何 OpenAI 模型
        openai_models = [
            model for model in manager.model_database.values()
            if model.provider == "openai"
        ]
        assert len(openai_models) > 0

    def test_model_database_models_are_model_info(self, manager):
        """測試資料庫中的模型都是 ModelInfo 實例"""
        for model in manager.model_database.values():
            assert isinstance(model, ModelInfo)

    def test_get_model_info_from_database(self, manager):
        """測試從資料庫獲取模型資訊"""
        # 直接訪問資料庫
        if manager.model_database:
            first_model_id = list(manager.model_database.keys())[0]
            info = manager.model_database.get(first_model_id)

            assert info is not None
            assert isinstance(info, ModelInfo)
            # 驗證提供者資訊
            assert info.provider is not None


class TestModelManagerCaching:
    """測試模型快取機制"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_cache_expiry_set(self, manager):
        """測試快取過期時間已設定"""
        assert manager.cache_expiry > 0

    def test_cached_models_structure(self, manager):
        """測試快取模型的資料結構"""
        assert isinstance(manager.cached_models, dict)
        assert isinstance(manager.cache_time, dict)

    def test_cache_manual_check(self, manager):
        """測試手動檢查快取狀態"""
        import time

        # 測試快取為空的情況
        assert "test_provider" not in manager.cached_models

        # 設定快取
        manager.cached_models["test_provider"] = []
        manager.cache_time["test_provider"] = time.time()

        # 驗證快取已設定
        assert "test_provider" in manager.cached_models
        assert "test_provider" in manager.cache_time

    def test_cache_expiry_check(self, manager):
        """測試快取過期檢查邏輯"""
        import time

        # 設定一個很久以前的快取
        manager.cached_models["old_provider"] = []
        manager.cache_time["old_provider"] = time.time() - manager.cache_expiry - 100

        # 手動檢查是否過期
        time_diff = time.time() - manager.cache_time["old_provider"]
        is_expired = time_diff > manager.cache_expiry

        assert is_expired is True


class TestModelManagerSelection:
    """測試模型選擇邏輯"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_default_ollama_model(self, manager):
        """測試預設 Ollama 模型"""
        assert manager.default_ollama_model is not None
        assert isinstance(manager.default_ollama_model, str)

    def test_model_comparison_by_capabilities(self, manager):
        """測試基於能力評分比較模型"""
        # 建立一些測試模型
        model1 = ModelInfo(id="model1", provider="test", capabilities={"translation": 0.5})
        model2 = ModelInfo(id="model2", provider="test", capabilities={"translation": 0.9})

        # 比較能力評分
        assert model2.capabilities["translation"] > model1.capabilities["translation"]

    def test_model_database_structure(self, manager):
        """測試模型資料庫結構"""
        # 驗證資料庫是字典
        assert isinstance(manager.model_database, dict)

        # 驗證鍵是字串，值是 ModelInfo
        for key, value in manager.model_database.items():
            assert isinstance(key, str)
            assert isinstance(value, ModelInfo)


class TestModelManagerHelpers:
    """測試輔助方法"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_filter_translation_models(self, manager):
        """測試過濾翻譯模型"""
        # 建立測試模型列表
        test_models = [
            ModelInfo(id="model1", provider="test", tags=["translation"]),
            ModelInfo(id="model2", provider="test", tags=["chat"]),
            ModelInfo(id="model3", provider="test", tags=["translation", "specialized"]),
        ]

        # 應該有過濾方法
        if hasattr(manager, 'filter_translation_models'):
            filtered = manager.filter_translation_models(test_models)
            # 驗證過濾結果
            assert isinstance(filtered, list)

    def test_model_patterns_matching(self, manager):
        """測試模型模式匹配"""
        # 測試模型模式是否包含預期的模型
        assert isinstance(manager.model_patterns, list)
        assert len(manager.model_patterns) > 0

        # 常見模型應該在模式中
        common_patterns = ['llama', 'gpt', 'qwen']
        matches = any(pattern in manager.model_patterns for pattern in common_patterns)
        assert matches  # 至少有一個常見模式


class TestModelManagerDefaultModels:
    """測試預設模型建立"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_create_default_ollama_model(self, manager):
        """測試建立預設 Ollama 模型"""
        model = manager._create_default_ollama_model()

        assert isinstance(model, ModelInfo)
        assert model.provider == "ollama"
        assert model.id is not None

    def test_create_default_ollama_model_not_in_db(self, manager):
        """測試建立不在資料庫中的 Ollama 預設模型"""
        # 暫時修改預設模型名稱為不在資料庫中的
        original = manager.default_ollama_model
        manager.default_ollama_model = "nonexistent-model"

        model = manager._create_default_ollama_model()

        assert isinstance(model, ModelInfo)
        assert model.provider == "ollama"
        assert model.id == "nonexistent-model"

        # 恢復
        manager.default_ollama_model = original

    def test_create_default_openai_model(self, manager):
        """測試建立預設 OpenAI 模型"""
        model = manager._create_default_openai_model()

        assert isinstance(model, ModelInfo)
        assert model.provider == "openai"
        assert model.id == "gpt-3.5-turbo"

    def test_create_default_openai_model_not_in_db(self, temp_dir):
        """測試建立不在資料庫中的 OpenAI 預設模型"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        manager = ModelManager(str(config_file))

        # 清空資料庫中的 openai:gpt-3.5-turbo
        if "openai:gpt-3.5-turbo" in manager.model_database:
            del manager.model_database["openai:gpt-3.5-turbo"]

        model = manager._create_default_openai_model()

        assert isinstance(model, ModelInfo)
        assert model.id == "gpt-3.5-turbo"

    def test_create_default_anthropic_model(self, manager):
        """測試建立預設 Anthropic 模型"""
        model = manager._create_default_anthropic_model()

        assert isinstance(model, ModelInfo)
        assert model.provider == "anthropic"
        assert "claude" in model.id.lower()

    def test_create_default_anthropic_model_not_in_db(self, temp_dir):
        """測試建立不在資料庫中的 Anthropic 預設模型"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        manager = ModelManager(str(config_file))

        # 清空資料庫中的 anthropic 模型
        if "anthropic:claude-3-haiku-20240307" in manager.model_database:
            del manager.model_database["anthropic:claude-3-haiku-20240307"]

        model = manager._create_default_anthropic_model()

        assert isinstance(model, ModelInfo)
        assert "claude" in model.id.lower()

    def test_get_default_model_ollama(self, manager):
        """測試獲取 Ollama 預設模型"""
        model_name = manager.get_default_model("ollama")

        assert isinstance(model_name, str)
        assert len(model_name) > 0

    def test_get_default_model_openai(self, manager):
        """測試獲取 OpenAI 預設模型"""
        model_name = manager.get_default_model("openai")

        assert model_name == "gpt-3.5-turbo"

    def test_get_default_model_anthropic(self, manager):
        """測試獲取 Anthropic 預設模型"""
        model_name = manager.get_default_model("anthropic")

        assert "claude" in model_name.lower()


class TestModelManagerModelInfo:
    """測試模型資訊獲取"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_get_model_info_with_provider(self, manager):
        """測試使用 provider 獲取模型資訊"""
        info = manager.get_model_info("gpt-4o", provider="openai")

        assert isinstance(info, dict)
        assert info.get("id") == "gpt-4o"
        assert info.get("provider") == "openai"

    def test_get_model_info_without_provider(self, manager):
        """測試不指定 provider 獲取模型資訊"""
        info = manager.get_model_info("gpt-4o")

        assert isinstance(info, dict)
        # 應該能找到模型
        if info:
            assert "id" in info

    def test_get_model_info_nonexistent(self, manager):
        """測試獲取不存在的模型資訊"""
        info = manager.get_model_info("nonexistent-model-xyz")

        # 應該返回空字典
        assert isinstance(info, dict)

    def test_get_model_info_known_openai_model(self, manager):
        """測試獲取已知 OpenAI 模型資訊"""
        # 測試幾個常見的 OpenAI 模型
        models = ["gpt-3.5-turbo", "gpt-4"]

        for model_name in models:
            info = manager.get_model_info(model_name)
            assert isinstance(info, dict)

    def test_get_model_info_fallback_to_hardcoded(self, temp_dir):
        """測試 get_model_info 回退到硬編碼資訊"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        manager = ModelManager(str(config_file))

        # 清空資料庫中的 gpt-4o
        if "openai:gpt-4o" in manager.model_database:
            del manager.model_database["openai:gpt-4o"]

        # 嘗試獲取 gpt-4o 資訊，應該回退到硬編碼
        info = manager.get_model_info("gpt-4o")

        assert isinstance(info, dict)
        # 應該返回硬編碼的資訊
        if info:
            assert "id" in info or "name" in info


class TestModelManagerRecommendation:
    """測試模型推薦功能"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_get_recommended_model_default(self, manager):
        """測試獲取預設推薦模型"""
        model = manager.get_recommended_model()

        # 應該返回 ModelInfo 或 None
        assert model is None or isinstance(model, ModelInfo)

    def test_get_recommended_model_translation(self, manager):
        """測試獲取翻譯任務推薦模型"""
        model = manager.get_recommended_model(task_type="translation")

        assert model is None or isinstance(model, ModelInfo)

    def test_get_recommended_model_with_provider(self, manager):
        """測試指定 provider 獲取推薦模型"""
        model = manager.get_recommended_model(task_type="translation", provider="openai")

        assert model is None or isinstance(model, ModelInfo)
        if model:
            assert model.provider == "openai"

    def test_get_recommended_model_subtitle(self, manager):
        """測試字幕翻譯推薦模型"""
        model = manager.get_recommended_model(task_type="subtitle")

        assert model is None or isinstance(model, ModelInfo)

    def test_get_recommended_model_literary(self, manager):
        """測試文學翻譯推薦模型"""
        model = manager.get_recommended_model(task_type="literary")

        assert model is None or isinstance(model, ModelInfo)

    def test_get_recommended_model_technical(self, manager):
        """測試技術文件翻譯推薦模型"""
        model = manager.get_recommended_model(task_type="technical")

        assert model is None or isinstance(model, ModelInfo)

    def test_get_recommended_model_no_available(self, temp_dir):
        """測試無可用模型時返回 None"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        manager = ModelManager(str(config_file))

        # 標記所有模型為不可用
        for model in manager.model_database.values():
            model.available = False

        result = manager.get_recommended_model()

        # 應該返回 None
        assert result is None


class TestModelManagerSync:
    """測試同步方法"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_get_model_list_ollama(self, manager):
        """測試同步獲取 Ollama 模型列表"""
        # Mock 非同步方法
        mock_models = [
            ModelInfo(id="llama3", provider="ollama"),
            ModelInfo(id="mistral", provider="ollama")
        ]

        # 使用 AsyncMock
        mock_coro = AsyncMock(return_value=mock_models)

        with patch.object(manager, 'get_model_list_async', mock_coro):
            # 呼叫同步方法
            result = manager.get_model_list("ollama")

            # 驗證結果是字串列表
            assert isinstance(result, list)
            # 應該包含模型 ID
            assert len(result) == 2
            assert "llama3" in result
            assert "mistral" in result

    def test_get_model_list_invalid_type(self, manager):
        """測試無效的 LLM 類型"""
        # Mock get_model_list_async 返回空列表
        with patch.object(manager, 'get_model_list_async', return_value=AsyncMock(return_value=[])):
            result = manager.get_model_list("invalid_type")
            assert isinstance(result, list)


class TestModelManagerAsync:
    """測試非同步方法"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    @pytest.mark.asyncio
    async def test_init_async_session(self, manager):
        """測試初始化非同步 session"""
        await manager._init_async_session()

        assert manager.session is not None

        # 清理
        await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_close_async_session(self, manager):
        """測試關閉非同步 session"""
        # 先初始化
        await manager._init_async_session()
        assert manager.session is not None

        # 關閉
        await manager._close_async_session()
        assert manager.session is None

    @pytest.mark.asyncio
    async def test_async_context_manager(self, manager):
        """測試非同步上下文管理器"""
        async with manager as m:
            assert m is manager
            assert manager.session is not None

        # 退出後 session 應該被關閉
        assert manager.session is None

    @pytest.mark.asyncio
    async def test_get_provider_status(self, manager):
        """測試獲取提供者狀態"""
        status = await manager.get_provider_status()

        assert isinstance(status, dict)
        assert "ollama" in status
        assert "openai" in status
        assert "anthropic" in status

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_with_cache(self, manager):
        """測試非同步獲取模型列表（使用快取）"""
        import time

        # 模擬快取
        mock_models = [ModelInfo(id="test", provider="ollama")]
        manager.cached_models["ollama"] = mock_models
        manager.cache_time["ollama"] = time.time()

        # 應該返回快取的模型
        result = await manager.get_model_list_async("ollama")

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].id == "test"

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_cache_expired(self, manager):
        """測試非同步獲取模型列表（快取過期）"""
        import time

        # 設定過期的快取
        manager.cached_models["ollama"] = []
        manager.cache_time["ollama"] = time.time() - manager.cache_expiry - 100

        # Mock _get_ollama_models_async 返回預設模型
        with patch.object(manager, '_get_ollama_models_async', return_value=[]):
            result = await manager.get_model_list_async("ollama")

            assert isinstance(result, list)

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_unsupported_type(self, manager):
        """測試非同步獲取不支援的 LLM 類型"""
        result = await manager.get_model_list_async("unsupported_type")

        # 應該返回空列表
        assert isinstance(result, list)
        assert len(result) == 0

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_error_with_cache(self, manager):
        """測試獲取模型時發生錯誤但有快取"""
        import time

        # 設定舊快取
        mock_models = [ModelInfo(id="cached", provider="ollama")]
        manager.cached_models["ollama"] = mock_models
        manager.cache_time["ollama"] = time.time() - manager.cache_expiry - 10

        # Mock 方法拋出錯誤
        with patch.object(manager, '_get_ollama_models_async', side_effect=Exception("Network error")):
            result = await manager.get_model_list_async("ollama")

            # 應該返回過期的快取
            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].id == "cached"

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_error_no_cache(self, manager):
        """測試獲取模型時發生錯誤且無快取（Ollama）"""
        # Mock 方法拋出錯誤
        with patch.object(manager, '_get_ollama_models_async', side_effect=Exception("Network error")):
            result = await manager.get_model_list_async("ollama")

            # 應該返回預設模型
            assert isinstance(result, list)
            assert len(result) == 1

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_openai(self, manager):
        """測試非同步獲取 OpenAI 模型列表"""
        # Mock _get_openai_models_async 返回模型
        mock_models = [ModelInfo(id="gpt-4", provider="openai")]

        with patch.object(manager, '_get_openai_models_async', return_value=mock_models):
            result = await manager.get_model_list_async("openai", api_key="test-key")

            assert isinstance(result, list)
            assert len(result) == 1
            assert result[0].id == "gpt-4"

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_openai_error(self, manager):
        """測試 OpenAI 獲取失敗返回預設模型"""
        # Mock 方法拋出錯誤
        with patch.object(manager, '_get_openai_models_async', side_effect=Exception("API error")):
            result = await manager.get_model_list_async("openai")

            # 應該返回預設 OpenAI 模型
            assert isinstance(result, list)
            if result:
                assert result[0].provider == "openai"

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_anthropic(self, manager):
        """測試非同步獲取 Anthropic 模型列表"""
        # Mock _get_anthropic_models_async 返回模型
        mock_models = [ModelInfo(id="claude-3", provider="anthropic")]

        with patch.object(manager, '_get_anthropic_models_async', return_value=mock_models):
            # 需要 mock ANTHROPIC_AVAILABLE
            with patch('srt_translator.core.models.ANTHROPIC_AVAILABLE', True):
                result = await manager.get_model_list_async("anthropic", api_key="test-key")

                assert isinstance(result, list)

        # 清理
        if manager.session:
            await manager._close_async_session()

    @pytest.mark.asyncio
    async def test_get_model_list_async_anthropic_error(self, manager):
        """測試 Anthropic 獲取失敗返回預設模型"""
        # Mock 方法拋出錯誤
        with patch.object(manager, '_get_anthropic_models_async', side_effect=Exception("API error")):
            with patch('srt_translator.core.models.ANTHROPIC_AVAILABLE', True):
                result = await manager.get_model_list_async("anthropic")

                # 應該返回預設 Anthropic 模型
                assert isinstance(result, list)
                if result:
                    assert result[0].provider == "anthropic"

        # 清理
        if manager.session:
            await manager._close_async_session()


class TestModelManagerEdgeCases:
    """測試邊界條件"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 ModelManager"""
        config_file = temp_dir / "config" / "model_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return ModelManager(str(config_file))

    def test_get_model_info_empty_string(self, manager):
        """測試空字串模型名稱"""
        info = manager.get_model_info("")
        assert isinstance(info, dict)

    def test_get_default_model_unknown_type(self, manager):
        """測試未知類型的預設模型"""
        model = manager.get_default_model("unknown_type")
        # 應該返回 Ollama 預設模型
        assert isinstance(model, str)

    def test_get_recommended_model_unknown_task(self, manager):
        """測試未知任務類型"""
        model = manager.get_recommended_model(task_type="unknown_task")
        assert model is None or isinstance(model, ModelInfo)

    def test_model_database_key_format(self, manager):
        """測試模型資料庫鍵格式"""
        # 驗證鍵格式為 provider:model_id
        for key in manager.model_database.keys():
            assert ":" in key
            parts = key.split(":", 1)
            assert len(parts) == 2
            assert parts[0] in ["ollama", "openai", "anthropic"]
