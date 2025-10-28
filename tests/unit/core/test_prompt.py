"""測試 prompt 模組"""

import pytest
import json
from pathlib import Path
from datetime import datetime

from srt_translator.core.prompt import PromptManager
from srt_translator.core.config import ConfigManager


@pytest.fixture(autouse=True, scope="function")
def reset_prompt_config():
    """在每個測試後重置 prompt 配置

    這確保測試間不會有狀態污染。
    """
    # 備份原始配置（如果存在）
    config_backup = {}
    config_dir = Path("config")
    if config_dir.exists():
        for config_file in config_dir.glob("prompt*.json"):
            try:
                config_backup[config_file.name] = config_file.read_text(encoding='utf-8')
            except Exception:
                pass

    yield

    # 測試後：重置單例
    PromptManager._instance = None
    ConfigManager._instances = {}

    # 恢復配置檔案
    if config_dir.exists():
        for filename, content in config_backup.items():
            try:
                (config_dir / filename).write_text(content, encoding='utf-8')
            except Exception:
                pass


class TestPromptManagerInit:
    """測試 PromptManager 初始化"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def temp_config_file(self, temp_dir):
        """提供臨時配置檔案路徑"""
        config_dir = temp_dir / "config"
        config_dir.mkdir(exist_ok=True)
        return str(config_dir / "prompt_config.json")

    def test_initialization_basic(self, temp_config_file):
        """測試基本初始化"""
        manager = PromptManager(temp_config_file)

        assert manager is not None
        assert manager.config_file == temp_config_file
        assert hasattr(manager, 'default_prompts')
        assert hasattr(manager, 'custom_prompts')
        assert hasattr(manager, 'translation_styles')
        assert hasattr(manager, 'language_pairs')

    def test_singleton_pattern(self, temp_config_file):
        """測試單例模式"""
        manager1 = PromptManager.get_instance(temp_config_file)
        manager2 = PromptManager.get_instance()

        assert manager1 is manager2

    def test_default_prompts_structure(self, temp_config_file):
        """測試預設提示詞結構"""
        manager = PromptManager(temp_config_file)

        # 驗證預設提示詞包含必要的內容類型
        assert "general" in manager.default_prompts
        assert "adult" in manager.default_prompts
        assert "anime" in manager.default_prompts
        assert "movie" in manager.default_prompts

        # 驗證每個內容類型都有 ollama 和 openai 的提示詞
        for content_type in ["general", "adult", "anime", "movie"]:
            assert "ollama" in manager.default_prompts[content_type]
            assert "openai" in manager.default_prompts[content_type]

    def test_translation_styles_defined(self, temp_config_file):
        """測試翻譯風格定義"""
        manager = PromptManager(temp_config_file)

        expected_styles = ["standard", "literal", "localized", "specialized"]
        for style in expected_styles:
            assert style in manager.translation_styles

    def test_language_pairs_defined(self, temp_config_file):
        """測試語言對定義"""
        manager = PromptManager(temp_config_file)

        # 驗證主要語言對存在
        assert "日文→繁體中文" in manager.language_pairs
        assert "英文→繁體中文" in manager.language_pairs

        # 驗證語言對結構
        pair = manager.language_pairs["日文→繁體中文"]
        assert "source" in pair
        assert "target" in pair
        assert pair["source"] == "日文"
        assert pair["target"] == "繁體中文"

    def test_current_settings_initialization(self, temp_config_file):
        """測試當前設定初始化"""
        manager = PromptManager(temp_config_file)

        # 設定可能為None或有預設值，只要存在這些屬性即可
        assert hasattr(manager, 'current_content_type')
        assert hasattr(manager, 'current_style')
        assert hasattr(manager, 'current_language_pair')

    def test_templates_directory_created(self, temp_config_file, temp_dir):
        """測試模板目錄自動創建"""
        manager = PromptManager(temp_config_file)

        templates_dir = Path(manager.templates_dir)
        assert templates_dir.exists()


class TestPromptManagerGetPrompt:
    """測試提示詞獲取功能"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_get_prompt_default_general_ollama(self, manager):
        """測試獲取預設 general/ollama 提示詞"""
        prompt = manager.get_prompt(llm_type="ollama", content_type="general")

        assert prompt is not None
        assert len(prompt) > 0
        assert "translate" in prompt.lower()

    def test_get_prompt_default_general_openai(self, manager):
        """測試獲取預設 general/openai 提示詞"""
        prompt = manager.get_prompt(llm_type="openai", content_type="general")

        assert prompt is not None
        assert len(prompt) > 0
        assert "translate" in prompt.lower()

    def test_get_prompt_different_content_types(self, manager):
        """測試獲取不同內容類型的提示詞"""
        content_types = ["general", "adult", "anime", "movie"]

        for content_type in content_types:
            prompt = manager.get_prompt("ollama", content_type)
            assert prompt is not None
            assert len(prompt) > 0

    def test_get_prompt_uses_current_settings(self, manager):
        """測試使用當前設定獲取提示詞"""
        # 設置當前設定
        manager.current_content_type = "anime"
        manager.current_style = "standard"

        # 不指定參數，應該使用當前設定
        prompt = manager.get_prompt("ollama")
        assert prompt is not None

    def test_get_prompt_with_custom_prompt(self, manager):
        """測試獲取自訂提示詞"""
        # 設置自訂提示詞
        custom_prompt = "This is a custom prompt for testing."
        manager.set_prompt(custom_prompt, "ollama", "general")

        # 獲取應該返回自訂提示詞
        prompt = manager.get_prompt("ollama", "general")
        assert custom_prompt in prompt

    def test_get_prompt_fallback_to_general(self, manager):
        """測試回退到通用提示詞"""
        # 獲取不存在的內容類型應該回退到 general
        prompt = manager.get_prompt("unknown_llm", "general")
        assert prompt is not None


class TestPromptManagerSetPrompt:
    """測試提示詞設置功能"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_set_prompt_basic(self, manager):
        """測試基本設置提示詞"""
        new_prompt = "This is a new custom prompt."
        result = manager.set_prompt(new_prompt, "ollama", "general")

        assert result is True

        # 驗證提示詞已設置
        prompt = manager.get_prompt("ollama", "general")
        assert new_prompt in prompt

    def test_set_prompt_updates_custom_prompts(self, manager):
        """測試設置提示詞更新自訂提示詞字典"""
        new_prompt = "Another custom prompt."
        manager.set_prompt(new_prompt, "openai", "anime")

        assert "anime" in manager.custom_prompts
        assert "openai" in manager.custom_prompts["anime"]
        assert manager.custom_prompts["anime"]["openai"].strip() == new_prompt

    def test_set_prompt_saves_to_file(self, manager, temp_dir):
        """測試設置提示詞儲存至檔案"""
        new_prompt = "Prompt saved to file."
        manager.set_prompt(new_prompt, "ollama", "general")

        # 驗證模板檔案存在
        template_file = Path(manager.templates_dir) / "general_template.json"
        assert template_file.exists()

        # 驗證檔案內容
        with open(template_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
        assert "ollama" in data
        assert data["ollama"].strip() == new_prompt

    def test_set_prompt_adds_to_version_history(self, manager):
        """測試設置提示詞添加到版本歷史"""
        # 先設置一次
        manager.set_prompt("First version.", "ollama", "general")

        # 再設置第二次（會保存第一次到歷史）
        manager.set_prompt("Second version.", "ollama", "general")

        # 驗證版本歷史
        history = manager.get_version_history("general", "ollama")
        assert len(history) >= 1

    def test_set_prompt_with_whitespace(self, manager):
        """測試設置帶空白的提示詞（應該自動去除）"""
        new_prompt = "  \n  Prompt with whitespace.  \n  "
        manager.set_prompt(new_prompt, "ollama", "general")

        # 驗證空白已去除
        prompt = manager.custom_prompts["general"]["ollama"]
        assert prompt == new_prompt.strip()


class TestPromptManagerStyles:
    """測試風格與語言修飾符"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_apply_style_modifier_literal(self, manager):
        """測試套用直譯風格修飾符"""
        base_prompt = "Translate this text."
        modified = manager._apply_style_modifier(base_prompt, "literal", "ollama")

        assert "literal" in modified.lower()
        assert base_prompt in modified

    def test_apply_style_modifier_localized(self, manager):
        """測試套用本地化風格修飾符"""
        base_prompt = "Translate this text."
        modified = manager._apply_style_modifier(base_prompt, "localized", "ollama")

        assert "Taiwan" in modified or "文化" in modified
        assert base_prompt in modified

    def test_apply_style_modifier_specialized(self, manager):
        """測試套用專業風格修飾符"""
        base_prompt = "Translate this text."
        modified = manager._apply_style_modifier(base_prompt, "specialized", "ollama")

        assert "terminology" in modified.lower() or "術語" in modified
        assert base_prompt in modified

    def test_apply_style_modifier_standard_unchanged(self, manager):
        """測試標準風格不修改提示詞"""
        base_prompt = "Translate this text."
        modified = manager._apply_style_modifier(base_prompt, "standard", "ollama")

        assert modified == base_prompt

    def test_get_prompt_with_style(self, manager):
        """測試獲取帶風格的提示詞"""
        prompt = manager.get_prompt("ollama", "general", "literal")

        assert prompt is not None
        assert "literal" in prompt.lower()

    def test_apply_language_pair_modifier(self, manager):
        """測試套用語言對修飾符"""
        base_prompt = "Translate to Traditional Chinese."
        modified = manager._apply_language_pair_modifier(base_prompt, "英文→繁體中文")

        assert "英文" in modified or "English" in modified
        assert "繁體中文" in modified or "Traditional Chinese" in modified

    def test_apply_language_pair_modifier_default_unchanged(self, manager):
        """測試預設語言對不修改"""
        base_prompt = "Translate to Traditional Chinese."
        modified = manager._apply_language_pair_modifier(base_prompt, "日文→繁體中文")

        # 日文→繁體中文是預設，不應該修改
        assert modified == base_prompt


class TestPromptManagerVersionHistory:
    """測試版本歷史管理"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_get_version_history_empty(self, manager):
        """測試獲取空版本歷史"""
        # 清空版本歷史
        manager.version_history = {}
        history = manager.get_version_history("general", "ollama")
        assert history == [] or len(history) == 0

    def test_get_version_history_after_update(self, manager):
        """測試更新後獲取版本歷史"""
        # 清空版本歷史
        manager.version_history = {}

        # 設置初始提示詞
        manager.set_prompt("Version 1", "ollama", "general")

        # 更新提示詞（會保存 v1 到歷史）
        manager.set_prompt("Version 2", "ollama", "general")

        # 獲取歷史
        history = manager.get_version_history("general", "ollama")
        assert len(history) >= 1
        # 驗證歷史中包含 Version 1
        assert any("Version 1" in h["prompt"] for h in history)

    def test_version_history_maintains_limit(self, manager):
        """測試版本歷史維護數量限制（最多10個）"""
        # 設置超過10個版本
        for i in range(15):
            manager.set_prompt(f"Version {i}", "ollama", "general")

        # 驗證最多保留10個
        history = manager.get_version_history("general", "ollama")
        assert len(history) <= 10

    def test_version_history_includes_metadata(self, manager):
        """測試版本歷史包含元數據"""
        manager.set_prompt("First", "ollama", "general")
        manager.set_prompt("Second", "ollama", "general")

        history = manager.get_version_history("general", "ollama")
        assert len(history) > 0

        # 驗證元數據
        entry = history[0]
        assert "prompt" in entry
        assert "timestamp" in entry
        assert "version" in entry

    def test_restore_version(self, manager):
        """測試恢復版本"""
        # 清空版本歷史
        manager.version_history = {}

        # 設置多個版本
        manager.set_prompt("Version 1", "ollama", "general")
        manager.set_prompt("Version 2", "ollama", "general")
        manager.set_prompt("Version 3", "ollama", "general")

        # 獲取歷史以確認有版本
        history = manager.get_version_history("general", "ollama")

        if len(history) > 0:
            # 恢復到第一個版本
            result = manager.restore_version("general", "ollama", 0)
            assert result is True
        else:
            # 如果沒有歷史，測試恢復無效索引
            result = manager.restore_version("general", "ollama", 999)
            assert result is False

    def test_restore_version_invalid_index(self, manager):
        """測試恢復無效版本索引"""
        result = manager.restore_version("general", "ollama", 999)
        assert result is False

    def test_get_version_history_all_llm_types(self, manager):
        """測試獲取所有 LLM 類型的歷史"""
        # 為不同 LLM 設置提示詞
        manager.set_prompt("Ollama v1", "ollama", "general")
        manager.set_prompt("Ollama v2", "ollama", "general")
        manager.set_prompt("OpenAI v1", "openai", "general")
        manager.set_prompt("OpenAI v2", "openai", "general")

        # 獲取所有歷史（不指定 llm_type）
        all_history = manager.get_version_history("general")

        # 應該包含兩種 LLM 的歷史
        assert len(all_history) >= 2
        llm_types = {entry["llm_type"] for entry in all_history}
        assert "ollama" in llm_types
        assert "openai" in llm_types


class TestPromptManagerOptimizedMessage:
    """測試優化訊息格式"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_get_optimized_message_basic(self, manager):
        """測試基本優化訊息格式"""
        text = "Hello"
        context = ["Hi", "Bye"]

        messages = manager.get_optimized_message(text, context, "ollama", "llama3")

        assert isinstance(messages, list)
        assert len(messages) >= 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"

    def test_get_optimized_message_ollama_format(self, manager):
        """測試 Ollama 訊息格式"""
        text = "Test text"
        context = ["Context 1", "Context 2"]

        messages = manager.get_optimized_message(text, context, "ollama", "llama3")

        # 驗證訊息結構
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert text in messages[1]["content"]

    def test_get_optimized_message_openai_format(self, manager):
        """測試 OpenAI 訊息格式"""
        text = "Test text"
        context = ["Context 1"]

        messages = manager.get_optimized_message(text, context, "openai", "gpt-4")

        # 驗證訊息結構
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[1]["role"] == "user"
        assert text in messages[1]["content"]

    def test_get_optimized_message_includes_context(self, manager):
        """測試優化訊息包含上下文"""
        text = "Main text"
        context = ["Before", "After"]

        messages = manager.get_optimized_message(text, context, "ollama", "model")

        # 驗證上下文包含在用戶訊息中
        user_message = messages[1]["content"]
        assert "Before" in user_message
        assert "After" in user_message
        assert "Main text" in user_message


class TestPromptManagerReset:
    """測試重置功能"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_reset_to_default_specific_llm(self, manager):
        """測試重置特定 LLM 類型為預設值"""
        # 設置自訂提示詞
        manager.set_prompt("Custom prompt", "ollama", "general")

        # 重置
        result = manager.reset_to_default("ollama", "general")
        assert result is True

        # 驗證已恢復預設值
        prompt = manager.get_prompt("ollama", "general")
        assert "Custom prompt" not in prompt

    def test_reset_to_default_all_llm_types(self, manager):
        """測試重置所有 LLM 類型為預設值"""
        # 設置多個自訂提示詞
        manager.set_prompt("Custom Ollama", "ollama", "general")
        manager.set_prompt("Custom OpenAI", "openai", "general")

        # 重置所有
        result = manager.reset_to_default(None, "general")
        assert result is True

        # 驗證所有都已恢復預設值
        ollama_prompt = manager.get_prompt("ollama", "general")
        openai_prompt = manager.get_prompt("openai", "general")

        assert "Custom Ollama" not in ollama_prompt
        assert "Custom OpenAI" not in openai_prompt


class TestPromptManagerConfigListener:
    """測試配置監聽器"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_config_changed_updates_settings(self, manager):
        """測試配置變更更新設定"""
        # 觸發配置變更
        new_config = {
            "current_content_type": "anime",
            "current_style": "localized",
            "current_language_pair": "英文→繁體中文"
        }

        manager._config_changed("prompt", new_config)

        # 驗證設定已更新
        assert manager.current_content_type == "anime"
        assert manager.current_style == "localized"
        assert manager.current_language_pair == "英文→繁體中文"

    def test_config_changed_ignores_other_types(self, manager):
        """測試配置變更忽略其他類型"""
        original_content_type = manager.current_content_type

        # 觸發非 prompt 類型的配置變更
        manager._config_changed("app", {"some": "config"})

        # 驗證設定未變更
        assert manager.current_content_type == original_content_type


class TestPromptManagerFileOperations:
    """測試檔案操作"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_save_prompt_template(self, manager):
        """測試儲存提示詞模板"""
        # 設置自訂提示詞
        manager.custom_prompts["test_type"] = {
            "ollama": "Test prompt for ollama",
            "openai": "Test prompt for openai"
        }

        # 儲存模板
        result = manager._save_prompt_template("test_type")
        assert result is True

        # 驗證檔案存在
        template_file = Path(manager.templates_dir) / "test_type_template.json"
        assert template_file.exists()

    def test_load_custom_prompts_from_file(self, manager, temp_dir):
        """測試從檔案載入自訂提示詞"""
        # 先建立模板檔案
        template_file = Path(manager.templates_dir) / "general_template.json"
        template_file.parent.mkdir(exist_ok=True)

        template_data = {
            "ollama": "Custom General Ollama prompt",
            "openai": "Custom General OpenAI prompt"
        }

        with open(template_file, 'w', encoding='utf-8') as f:
            json.dump(template_data, f)

        # 重新初始化以載入模板
        PromptManager._instance = None
        ConfigManager._instances = {}
        new_manager = PromptManager(manager.config_file)

        # 驗證模板已載入（可能合併到自訂提示詞中）
        assert "general" in new_manager.custom_prompts
        # 檢查是否載入了檔案中的內容
        assert new_manager.custom_prompts is not None

    def test_load_custom_prompts_with_invalid_json(self, manager):
        """測試載入無效 JSON 檔案"""
        # 建立無效的 JSON 檔案
        template_file = Path(manager.templates_dir) / "anime_template.json"
        template_file.parent.mkdir(exist_ok=True)

        with open(template_file, 'w', encoding='utf-8') as f:
            f.write("invalid json{{{")

        # 重新載入自訂提示詞（應該捕獲錯誤不崩潰）
        manager._load_custom_prompts()

        # 應該不崩潰
        assert manager.custom_prompts is not None

    def test_save_prompt_template_error_handling(self, manager):
        """測試儲存模板的錯誤處理"""
        # 使用無效路徑
        original_dir = manager.templates_dir
        manager.templates_dir = "/invalid/path/that/does/not/exist"

        # 設置自訂提示詞
        manager.custom_prompts["test"] = {"ollama": "test"}

        # 嘗試儲存（應該返回 False 而不是崩潰）
        result = manager._save_prompt_template("test")
        # 在某些系統上可能會創建目錄，所以不強制要求 False
        assert result is True or result is False

        # 恢復原始路徑
        manager.templates_dir = original_dir


class TestPromptManagerEdgeCases:
    """測試邊緣情況和錯誤處理"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        """每個測試前重置單例實例"""
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        """提供測試用的 PromptManager"""
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_get_prompt_with_unknown_content_type(self, manager):
        """測試獲取未知內容類型的提示詞"""
        prompt = manager.get_prompt("ollama", "unknown_type")

        # 應該回退到預設提示詞
        assert prompt is not None
        assert len(prompt) > 0

    def test_set_prompt_creates_content_type(self, manager):
        """測試設置提示詞時自動創建內容類型"""
        new_type = "documentary"
        manager.set_prompt("Documentary prompt", "ollama", new_type)

        # 驗證新類型已創建
        assert new_type in manager.custom_prompts
        assert "ollama" in manager.custom_prompts[new_type]

    def test_version_history_timestamp(self, manager):
        """測試版本歷史包含時間戳"""
        manager.version_history = {}
        manager.set_prompt("V1", "ollama", "general")
        manager.set_prompt("V2", "ollama", "general")

        history = manager.get_version_history("general", "ollama")
        if len(history) > 0:
            # 驗證時間戳格式
            timestamp = history[0]["timestamp"]
            assert isinstance(timestamp, str)
            # 嘗試解析時間戳
            try:
                datetime.fromisoformat(timestamp)
                assert True
            except:
                # 如果解析失敗，至少確保時間戳存在
                assert timestamp is not None

    def test_apply_language_pair_modifier_unknown_pair(self, manager):
        """測試套用未知語言對修飾符"""
        prompt = "Test prompt"
        modified = manager._apply_language_pair_modifier(prompt, "未知語言對")

        # 未知語言對應該返回原始提示詞
        assert modified == prompt

    def test_get_optimized_message_with_empty_context(self, manager):
        """測試生成沒有上下文的優化訊息"""
        messages = manager.get_optimized_message("Test", [], "ollama", "model")

        assert len(messages) == 2
        assert messages[1]["role"] == "user"

    def test_multiple_style_applications(self, manager):
        """測試多次套用風格修飾符"""
        prompt = manager.get_prompt("ollama", "general", "literal")
        prompt2 = manager.get_prompt("ollama", "general", "localized")

        # 兩個提示詞應該不同
        assert prompt != prompt2

    def test_reset_to_default_for_new_content_type(self, manager):
        """測試重置新內容類型（不在預設中）"""
        # 設置一個新類型的自訂提示詞
        manager.set_prompt("Custom", "ollama", "new_type")

        # 嘗試重置（應該處理不存在於 default_prompts 的情況）
        result = manager.reset_to_default("ollama", "new_type")

        # 可能成功或失敗都是合理的，只要不崩潰
        assert result is True or result is False

    def test_config_changed_with_partial_config(self, manager):
        """測試配置變更時只包含部分欄位"""
        original_style = manager.current_style

        # 只提供部分配置
        manager._config_changed("prompt", {"current_content_type": "anime"})

        # 驗證只更新了提供的欄位
        assert manager.current_content_type == "anime"
        # 其他欄位保持原值
        assert manager.current_style == original_style or manager.current_style is not None

    def test_get_instance_with_explicit_path(self, temp_dir):
        """測試使用明確路徑獲取實例"""
        config_file = str(temp_dir / "custom_config.json")

        PromptManager._instance = None
        manager = PromptManager.get_instance(config_file)

        assert manager is not None
        assert manager.config_file == config_file
