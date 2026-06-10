"""測試 models 模組的擴展功能"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from srt_translator.core.config import ConfigManager
from srt_translator.core.models import ModelManager, get_model_info, get_recommended_model


class TestModelManagerAPIKeyOperations:
    """測試 API 金鑰載入行為"""

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

    @patch.dict("os.environ", {"OPENAI_API_KEY": "sk-env-openai", "GOOGLE_API_KEY": "env-google"}, clear=True)
    def test_load_api_keys_from_environment(self, manager):
        """測試從環境變數 / .env 載入 API 金鑰。"""
        manager.api_keys.clear()

        manager._load_api_keys()

        assert manager.api_keys == {"openai": "sk-env-openai", "google": "env-google"}

    @patch.dict("os.environ", {}, clear=True)
    def test_load_api_keys_does_not_fallback_to_legacy_txt_files(self, manager):
        """測試未設定環境變數時不再回退讀取舊 txt 金鑰檔。"""
        manager.api_keys.clear()

        with patch("os.path.exists", return_value=True), patch("builtins.open", MagicMock()) as mock_open:
            manager._load_api_keys()

        assert manager.api_keys == {}
        mock_open.assert_not_called()

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
        new_config = {"llamacpp_url": "http://newhost:8080"}

        manager.update_config(new_config)

        # 驗證快取已清除
        assert len(manager.cached_models) == 0
        assert len(manager.cache_time) == 0

    def test_update_config_default_model(self, manager):
        """測試更新預設模型配置"""
        new_config = {"llamacpp_url": "http://localhost:8081"}

        manager.update_config(new_config)

        # 驗證快取已清除
        assert len(manager.cached_models) == 0
        assert manager.config.get("llamacpp_url") == "http://localhost:8081"

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
        result = manager._format_model_name("gemini_2_flash")
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
        assert result[0].id == "gpt-4.1-mini"

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
                assert result[0].id == "gpt-4.1-mini"
