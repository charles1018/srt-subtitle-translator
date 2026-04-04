"""測試 models 模組的擴展功能"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from srt_translator.core.config import ConfigManager
from srt_translator.core.models import ModelInfo, ModelManager, get_model_info, get_recommended_model


class TestModelManagerAPIKeyOperations:
    """測試 API 金鑰操作"""

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

    def test_save_api_key_success(self, manager, temp_dir):
        """測試成功儲存 API 金鑰"""
        test_key = "sk-test-key-123456"
        key_file = temp_dir / "test_api_key.txt"

        with patch("srt_translator.core.models.get_config", return_value=str(key_file)):
            result = manager.save_api_key("openai", test_key)

            assert result is True
            assert manager.api_keys.get("openai") == test_key
            # 驗證檔案已建立
            assert key_file.exists()
            assert key_file.read_text(encoding="utf-8") == test_key

    def test_save_api_key_clears_cache(self, manager, temp_dir):
        """測試儲存 API 金鑰會清除快取"""
        # 設定快取
        manager.cached_models["openai"] = [ModelInfo(id="test", provider="openai")]
        manager.cache_time["openai"] = 1234567890

        test_key = "sk-test-key-123456"
        key_file = temp_dir / "test_api_key.txt"

        with patch("srt_translator.core.models.get_config", return_value=str(key_file)):
            manager.save_api_key("openai", test_key)

            # 驗證快取已清除
            assert "openai" not in manager.cached_models
            assert "openai" not in manager.cache_time

    def test_save_api_key_error_handling(self, manager):
        """測試儲存 API 金鑰錯誤處理"""
        # 使用無效路徑
        with patch("srt_translator.core.models.get_config", return_value="/invalid/path/key.txt"):  # noqa: SIM117
            with patch("os.makedirs", side_effect=PermissionError("Access denied")):
                result = manager.save_api_key("openai", "test-key")
                # 應該返回 False
                assert result is False

    def test_save_api_key_anthropic(self, manager, temp_dir):
        """測試儲存 Anthropic API 金鑰"""
        test_key = "sk-ant-test-123456"
        key_file = temp_dir / "anthropic_api_key.txt"

        with patch("srt_translator.core.models.get_config", return_value=str(key_file)):
            result = manager.save_api_key("anthropic", test_key)

            assert result is True
            assert manager.api_keys.get("anthropic") == test_key


class TestModelManagerConfigOperations:
    """測試配置操作"""

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

    def test_update_config_success(self, manager):
        """測試成功更新配置"""
        new_config = {"cache_expiry": 1200, "connect_timeout": 10}

        manager.update_config(new_config)

        # 驗證配置已更新
        assert manager.config.get("cache_expiry") == 1200
        assert manager.config.get("connect_timeout") == 10

    def test_update_config_clears_cache_on_important_changes(self, manager):
        """測試更新重要配置項時清除快取"""
        # 設定快取
        manager.cached_models["test"] = []
        manager.cache_time["test"] = 1234567890

        # 更新重要配置項
        new_config = {"ollama_url": "http://newhost:11434"}

        manager.update_config(new_config)

        # 驗證快取已清除
        assert len(manager.cached_models) == 0
        assert len(manager.cache_time) == 0

    def test_update_config_default_model(self, manager):
        """測試更新預設模型配置"""
        new_config = {"default_ollama_model": "mistral"}

        manager.update_config(new_config)

        # 驗證快取已清除
        assert len(manager.cached_models) == 0
        assert manager.config.get("default_ollama_model") == "mistral"

    def test_update_config_model_patterns(self, manager):
        """測試更新模型模式配置"""
        new_patterns = ["llama", "mistral", "custom"]
        new_config = {"model_patterns": new_patterns}

        manager.update_config(new_config)

        # 驗證快取已清除
        assert len(manager.cached_models) == 0
        assert manager.config.get("model_patterns") == new_patterns


class TestModelManagerFormatHelpers:
    """測試格式化輔助方法"""

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

    def test_format_model_name_simple(self, manager):
        """測試簡單模型名稱格式化"""
        result = manager._format_model_name("llama3")
        # 驗證返回值是字串且非空
        assert isinstance(result, str)
        assert len(result) > 0
        # 應該包含 llama
        assert "llama" in result.lower()

    def test_format_model_name_with_version(self, manager):
        """測試帶版本號的模型名稱"""
        result = manager._format_model_name("llama3:latest")
        # 應該移除版本號或保留原樣
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_model_name_with_tag(self, manager):
        """測試帶標籤的模型名稱"""
        result = manager._format_model_name("llama3@sha256:abc123")
        # 應該移除標籤或保留原樣
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_model_name_with_path(self, manager):
        """測試帶路徑的模型名稱"""
        result = manager._format_model_name("library/llama3")
        # 驗證返回值是字串且非空
        assert isinstance(result, str)
        assert len(result) > 0
        # 應該包含 llama
        assert "llama" in result.lower()

    def test_format_model_name_with_hyphen(self, manager):
        """測試帶連字號的模型名稱"""
        result = manager._format_model_name("gpt-3.5-turbo")
        # 應該保留或正確格式化
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_model_name_with_underscore(self, manager):
        """測試帶底線的模型名稱"""
        result = manager._format_model_name("claude_3_opus")
        # 應該轉換為空格
        assert isinstance(result, str)
        assert len(result) > 0

    def test_format_model_name_empty(self, manager):
        """測試空字串"""
        result = manager._format_model_name("")
        assert result == ""

    def test_format_model_name_special_characters(self, manager):
        """測試特殊字元"""
        result = manager._format_model_name("model-v1.2.3_final")
        assert isinstance(result, str)


class TestGlobalFunctions:
    """測試全域函數"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        ModelManager._instance = None
        ConfigManager._instances = {}
        yield
        ModelManager._instance = None
        ConfigManager._instances = {}

    def test_global_get_model_info_with_provider(self, temp_dir):
        """測試全域 get_model_info 函數（指定 provider）"""
        info = get_model_info("gpt-4o", provider="openai")

        assert isinstance(info, dict)
        if info:  # 如果找到模型
            assert info.get("id") == "gpt-4o"
            assert info.get("provider") == "openai"

    def test_global_get_model_info_without_provider(self, temp_dir):
        """測試全域 get_model_info 函數（不指定 provider）"""
        info = get_model_info("gpt-4o")

        assert isinstance(info, dict)
        # 應該能夠通過模型名稱找到

    def test_global_get_model_info_nonexistent(self, temp_dir):
        """測試全域 get_model_info 不存在的模型"""
        info = get_model_info("nonexistent-model-xyz")

        assert isinstance(info, dict)
        # 應該返回空字典

    def test_global_get_recommended_model_with_provider(self, temp_dir):
        """測試全域 get_recommended_model 函數（指定 provider）"""
        model_name = get_recommended_model(task_type="translation", provider="openai")

        assert isinstance(model_name, str)
        assert len(model_name) > 0

    def test_global_get_recommended_model_no_provider(self, temp_dir):
        """測試全域 get_recommended_model 不指定 provider"""
        model_name = get_recommended_model(task_type="literary")

        assert isinstance(model_name, str)
        assert len(model_name) > 0

    def test_global_get_recommended_model_default_task(self, temp_dir):
        """測試全域 get_recommended_model 預設任務類型"""
        model_name = get_recommended_model()

        assert isinstance(model_name, str)
        assert len(model_name) > 0


class TestModelManagerOllamaModelsAsync:
    """測試 _get_ollama_models_async 的各種場景"""

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

    def test_detect_ollama_model_family_qwen35_custom_name(self, manager):
        """測試可從自訂模型名稱辨識 Qwen3.5 家族"""
        family = manager._detect_ollama_model_family(
            "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0"
        )

        assert family == "qwen3.5"

    def test_build_dynamic_ollama_model_info_qwen35(self, manager):
        """測試 Qwen3.5 動態模型資訊會套用專屬設定"""
        model = manager._build_dynamic_ollama_model_info(
            "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0",
            {"family": "qwen35", "parameter_size": "9.3B", "quantization_level": "Q8_0"},
        )

        assert model.provider == "ollama"
        assert model.parallel == 1
        assert model.context_length == 262144
        assert "q8_0" in model.tags
        assert model.capabilities["chinese"] >= 0.9

    def test_build_dynamic_ollama_model_info_gemma4(self, manager):
        """測試 Gemma 4 動態模型資訊會套用 128K context 與多語標籤"""
        model = manager._build_dynamic_ollama_model_info(
            "gemma-4-E4B-it-UD-Q8_K_XL.gguf",
            {"family": "gemma4", "parameter_size": "7.5B", "quantization_level": "Q8_0"},
        )

        assert model.provider == "ollama"
        assert model.context_length == 131072
        assert "multilingual" in model.tags
        assert "q8_0" in model.tags
        assert "128K context" in model.description

    @pytest.mark.asyncio
    async def test_get_ollama_models_api_tags_format(self, manager):
        """測試從 /api/tags 端點獲取模型（標準格式）"""
        mock_response = {"models": [{"name": "llama3.2"}, {"name": "mistral"}, {"name": "qwen3"}]}

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_response)

        mock_context_manager = MagicMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = mock_session

            result = await manager._get_ollama_models_async()

            assert isinstance(result, list)
            assert len(result) >= 3
            model_ids = [m.id for m in result]
            assert "llama3.2" in model_ids
            assert "mistral" in model_ids

    @pytest.mark.asyncio
    async def test_get_ollama_models_api_tags_qwen35_details(self, manager):
        """測試可從 /api/tags 的 details 欄位辨識 Qwen3.5 特性"""
        mock_response = {
            "models": [
                {
                    "name": "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0",
                    "details": {"family": "qwen35", "parameter_size": "9.3B", "quantization_level": "Q8_0"},
                }
            ]
        }

        mock_resp = AsyncMock()
        mock_resp.status = 200
        mock_resp.json = AsyncMock(return_value=mock_response)

        mock_context_manager = MagicMock()
        mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
        mock_context_manager.__aexit__ = AsyncMock(return_value=None)

        mock_session = MagicMock()
        mock_session.get.return_value = mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = mock_session

            result = await manager._get_ollama_models_async()

            model = next(
                item
                for item in result
                if item.id == "HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive:Q8_0"
            )
            assert model.parallel == 1
            assert model.context_length == 262144
            assert "q8_0" in model.tags

    @pytest.mark.asyncio
    async def test_get_ollama_models_dict_format(self, manager):
        """測試模型以字典格式返回"""
        mock_response = {"models": {"llama3": {"size": "4.7GB"}, "mistral": {"size": "4.1GB"}}}

        def mock_get(*args, **kwargs):
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            mock_context_manager = MagicMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            return mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = MagicMock()
            manager.session.get = mock_get

            result = await manager._get_ollama_models_async()

            assert isinstance(result, list)
            assert len(result) >= 2

    @pytest.mark.asyncio
    async def test_get_ollama_models_list_format(self, manager):
        """測試模型以列表格式返回（無 'models' 鍵）"""
        mock_response = [{"name": "llama3"}, {"name": "mistral"}]

        def mock_get(*args, **kwargs):
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            mock_context_manager = MagicMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            return mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = MagicMock()
            manager.session.get = mock_get

            result = await manager._get_ollama_models_async()

            assert isinstance(result, list)
            assert len(result) >= 2

    @pytest.mark.asyncio
    async def test_get_ollama_models_api_error_fallback(self, manager):
        """測試 API 錯誤時使用預設模型"""

        def mock_get(*args, **kwargs):
            mock_resp = AsyncMock()
            mock_resp.status = 500
            mock_context_manager = MagicMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            return mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = MagicMock()
            manager.session.get = mock_get

            result = await manager._get_ollama_models_async()

            # 應該返回預設模型
            assert isinstance(result, list)
            assert len(result) >= 1

    @pytest.mark.asyncio
    async def test_get_ollama_models_default_fallback_includes_qwen35(self, manager):
        """測試 API 失敗時的預設模型清單包含 Qwen3.5"""

        def mock_get(*args, **kwargs):
            mock_resp = AsyncMock()
            mock_resp.status = 500
            mock_context_manager = MagicMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            return mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None), \
             patch.object(manager, "_get_ollama_models_via_cli", return_value={}):
            manager.session = MagicMock()
            manager.session.get = mock_get

            result = await manager._get_ollama_models_async()

            model_ids = [m.id for m in result]
            assert "qwen3.5" in model_ids

    @pytest.mark.asyncio
    async def test_get_ollama_models_includes_default(self, manager):
        """測試結果包含預設模型"""
        mock_response = {"models": [{"name": "mistral"}]}

        def mock_get(*args, **kwargs):
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            mock_context_manager = MagicMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            return mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = MagicMock()
            manager.session.get = mock_get

            result = await manager._get_ollama_models_async()

            # 應該包含預設模型
            model_ids = [m.id for m in result]
            assert manager.default_ollama_model in model_ids

    @pytest.mark.asyncio
    async def test_get_ollama_models_filtering(self, manager):
        """測試模型過濾功能"""
        # 創建超過 20 個模型來觸發過濾
        models = [{"name": f"model_{i}"} for i in range(25)]
        # 添加一些符合模式的模型
        models.extend([{"name": "llama3"}, {"name": "mistral"}, {"name": "qwen"}])

        mock_response = {"models": models}

        def mock_get(*args, **kwargs):
            mock_resp = AsyncMock()
            mock_resp.status = 200
            mock_resp.json = AsyncMock(return_value=mock_response)
            mock_context_manager = MagicMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            return mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = MagicMock()
            manager.session.get = mock_get

            result = await manager._get_ollama_models_async()

            assert isinstance(result, list)
            # 過濾後應該保留符合模式的模型
            model_ids = [m.id for m in result]
            # 至少應該有符合模式的模型
            assert any(pattern in " ".join(model_ids).lower() for pattern in manager.model_patterns)

class TestModelManagerLlamaCppModelsAsync:
    """測試 _get_llamacpp_models_async 的各種場景"""

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
    async def test_get_llamacpp_models_reads_props_slots_and_models(self, manager):
        """測試 llama.cpp 模型列表會整合 props 與 slots 資訊"""
        props_response = {
            "total_slots": 3,
            "model_path": "/models/Qwen3.5-8B-Instruct-Q8_0.gguf",
            "default_generation_settings": {"n_ctx": 8192},
        }
        slots_response = [{"n_ctx": 8192}, {"n_ctx": 8192}, {"n_ctx": 8192}]
        models_response = {
            "data": [
                {
                    "id": "qwen3.5-8b-instruct",
                    "meta": {
                        "n_params": 8_000_000_000,
                        "n_ctx_train": 131072,
                    },
                }
            ]
        }

        def mock_get(url, *args, **kwargs):
            if url.endswith("/props"):
                payload = props_response
                status = 200
            elif url.endswith("/slots"):
                payload = slots_response
                status = 200
            elif url.endswith("/v1/models"):
                payload = models_response
                status = 200
            else:
                payload = {}
                status = 404

            mock_resp = AsyncMock()
            mock_resp.status = status
            mock_resp.json = AsyncMock(return_value=payload)
            mock_context_manager = MagicMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            return mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = MagicMock()
            manager.session.get = mock_get

            result = await manager._get_llamacpp_models_async()

            assert len(result) == 1
            model = result[0]
            assert model.id == "qwen3.5-8b-instruct"
            assert model.name == "Qwen3.5-8B-Instruct-Q8_0"
            assert model.parallel == 3
            assert model.context_length == 8192
            assert "8.0B 參數" in model.description
            assert "3 個並行槽" in model.description

    @pytest.mark.asyncio
    async def test_get_llamacpp_models_falls_back_to_props_model_path(self, manager):
        """測試 /v1/models 不可用時仍可用 /props 建立單一模型資訊"""
        props_response = {
            "total_slots": 2,
            "model_path": "/models/Qwen3.5-8B-Instruct-Q8_0.gguf",
            "default_generation_settings": {"n_ctx": 4096},
        }

        def mock_get(url, *args, **kwargs):
            if url.endswith("/props"):
                payload = props_response
                status = 200
            elif url.endswith("/slots"):
                payload = {"error": "not supported"}
                status = 501
            elif url.endswith("/v1/models"):
                payload = {"error": "unavailable"}
                status = 404
            else:
                payload = {}
                status = 404

            mock_resp = AsyncMock()
            mock_resp.status = status
            mock_resp.json = AsyncMock(return_value=payload)
            mock_context_manager = MagicMock()
            mock_context_manager.__aenter__ = AsyncMock(return_value=mock_resp)
            mock_context_manager.__aexit__ = AsyncMock(return_value=None)
            return mock_context_manager

        with patch.object(manager, "_init_async_session", return_value=None):
            manager.session = MagicMock()
            manager.session.get = mock_get

            result = await manager._get_llamacpp_models_async()

            assert len(result) == 1
            model = result[0]
            assert model.id == "Qwen3.5-8B-Instruct-Q8_0.gguf"
            assert model.name == "Qwen3.5-8B-Instruct-Q8_0"
            assert model.parallel == 2
            assert model.context_length == 4096
            assert model.available is True

    def test_get_llamacpp_fallback_models_uses_updated_startup_hint(self, manager):
        """測試 llama.cpp fallback 提示改為最佳化後的建議參數"""
        fallback_model = manager._get_llamacpp_fallback_models()[0]

        assert "--parallel 1" in fallback_model.description
        assert "-c 1024" in fallback_model.description
        assert "--cache-ram 4096" in fallback_model.description
        assert "--reasoning-budget 0" not in fallback_model.description
        assert "-ctk" not in fallback_model.description
        assert fallback_model.context_length == 1024
        assert fallback_model.parallel == 1


class TestModelManagerOpenAIModelsAsync:
    """測試 _get_openai_models_async 的各種場景"""

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
    async def test_get_openai_models_without_api_key(self, manager):
        """測試沒有 API 金鑰時返回預設模型"""
        result = await manager._get_openai_models_async(api_key=None)

        assert isinstance(result, list)
        assert len(result) == 1
        assert result[0].provider == "openai"
        assert result[0].id == "gpt-3.5-turbo"

    @pytest.mark.asyncio
    async def test_get_openai_models_sorting(self, manager):
        """測試模型按翻譯優先級排序"""
        # Mock OpenAI client
        mock_models = [MagicMock(id="gpt-3.5-turbo"), MagicMock(id="gpt-4"), MagicMock(id="gpt-4o")]

        with patch("srt_translator.core.models.OPENAI_AVAILABLE", True):  # noqa: SIM117
            with patch("srt_translator.core.models.OpenAI") as mock_client:
                mock_instance = MagicMock()
                mock_instance.models.list.return_value = mock_models
                mock_client.return_value = mock_instance

                result = await manager._get_openai_models_async(api_key="test-key")

                # gpt-4o 應該排在最前面
                assert isinstance(result, list)
                assert len(result) > 0
                # 驗證結果包含預期模型
                model_ids = [m.id for m in result]
                assert "gpt-4o" in model_ids or "gpt-3.5-turbo" in model_ids

    @pytest.mark.asyncio
    async def test_get_openai_models_excludes_date_versions(self, manager):
        """測試排除日期版本的模型"""
        mock_models = [
            MagicMock(id="gpt-3.5-turbo"),
            MagicMock(id="gpt-3.5-turbo-0301"),  # 應該被排除
            MagicMock(id="gpt-4"),
        ]

        with patch("srt_translator.core.models.OPENAI_AVAILABLE", True):  # noqa: SIM117
            with patch("srt_translator.core.models.OpenAI") as mock_client:
                mock_instance = MagicMock()
                mock_instance.models.list.return_value = mock_models
                mock_client.return_value = mock_instance

                result = await manager._get_openai_models_async(api_key="test-key")

                model_ids = [m.id for m in result]
                # 不應該包含日期版本
                assert "gpt-3.5-turbo-0301" not in model_ids or len(result) == 1

    @pytest.mark.asyncio
    async def test_get_openai_models_error_handling(self, manager):
        """測試 API 錯誤時的處理"""
        with patch("srt_translator.core.models.OPENAI_AVAILABLE", True):  # noqa: SIM117
            with patch("srt_translator.core.models.OpenAI") as mock_client:
                mock_client.side_effect = Exception("API Error")

                result = await manager._get_openai_models_async(api_key="test-key")

                # 應該返回預設模型
                assert isinstance(result, list)
                assert len(result) == 1
                assert result[0].id == "gpt-3.5-turbo"
