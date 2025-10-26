"""測試 models 模組"""

import pytest
from srt_translator.core.models import ModelInfo


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
