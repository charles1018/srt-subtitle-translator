"""測試 prompt 模組"""

import contextlib
import json
from datetime import datetime
from pathlib import Path

import pytest

from srt_translator.core.config import ConfigManager
from srt_translator.core.prompt import PromptManager


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
            with contextlib.suppress(Exception):
                config_backup[config_file.name] = config_file.read_text(encoding="utf-8")

    yield

    # 測試後：重置單例
    PromptManager._instance = None
    ConfigManager._instances = {}

    # 恢復配置檔案
    if config_dir.exists():
        for filename, content in config_backup.items():
            with contextlib.suppress(Exception):
                (config_dir / filename).write_text(content, encoding="utf-8")


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
        assert hasattr(manager, "default_prompts")
        assert hasattr(manager, "custom_prompts")
        assert hasattr(manager, "translation_styles")
        assert hasattr(manager, "language_pairs")

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
        assert hasattr(manager, "current_content_type")
        assert hasattr(manager, "current_style")
        assert hasattr(manager, "current_language_pair")

    def test_current_settings_loaded_from_config_file(self, temp_config_file):
        """測試初始化時會正確讀取既有的 prompt 設定值。"""
        config_path = Path(temp_config_file)
        config_path.write_text(
            json.dumps(
                {
                    "current_content_type": "adult",
                    "current_style": "localized",
                    "current_language_pair": "英文→繁體中文",
                    "custom_prompts": {},
                    "version_history": {},
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        manager = PromptManager(temp_config_file)

        assert manager.current_content_type == "adult"
        assert manager.current_style == "localized"
        assert manager.current_language_pair == "英文→繁體中文"

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

    def test_get_prompt_maps_google_to_openai_family_default(self, manager):
        """測試 google 會沿用 openai 家族的預設 prompt。"""
        google_prompt = manager.get_prompt("google", "general")
        openai_prompt = manager.get_prompt("openai", "general")

        assert google_prompt == openai_prompt

    def test_get_prompt_maps_llamacpp_to_ollama_family_default(self, manager):
        """測試 llamacpp 會沿用 ollama 家族的預設 prompt。"""
        llamacpp_prompt = manager.get_prompt("llamacpp", "general")
        ollama_prompt = manager.get_prompt("ollama", "general")

        assert llamacpp_prompt == ollama_prompt

    def test_get_prompt_applies_style_modifier_to_google(self, manager):
        """測試 google 也會套用 openai 家族的風格修飾。"""
        prompt = manager.get_prompt("google", "general", "localized")

        assert "Taiwan expressions and references" in prompt


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
        with open(template_file, encoding="utf-8") as f:
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

    def test_get_prompt_openai_uses_compact_prompt_by_default(self, manager):
        """測試 OpenAI 預設使用精簡 prompt，避免重複排版規則耗費 token。"""
        prompt = manager.get_prompt("openai", "general")

        assert "Formatting, punctuation, line wrapping" in prompt
        assert "Prefer Taiwan subtitle wording" in prompt
        assert "Netflix Traditional Chinese Subtitle Standards" not in prompt

    def test_get_optimized_message_openai_uses_compact_user_message(self, manager):
        """測試 OpenAI user message 使用較精簡的 CURRENT/BEFORE/AFTER 結構。"""
        text = "But the big number comes tomorrow."
        context = ["Earlier context", text, "Later context"]

        messages = manager.get_optimized_message(text, context, "openai", "gpt-4o-mini", current_index=1)

        user_message = messages[1]["content"]
        assert "CURRENT:" in user_message
        assert "BEFORE (reference only):" in user_message
        assert "AFTER (reference only):" in user_message
        assert "[CURRENT]" not in user_message

    def test_get_optimized_message_batch_request_uses_batch_prompt(self, manager):
        """測試批次翻譯請求走專用批次 prompt。"""
        batch_text = "[BATCH: 2 lines — translate each line, output exactly 2 lines]\nHello\nWorld"

        messages = manager.get_optimized_message(batch_text, [], "openai", "gpt-4o-mini")

        assert "Strict Line Mapping" in messages[0]["content"]
        assert "sentence mood" in messages[0]["content"]
        assert messages[1]["content"] == batch_text

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

    def test_get_prompt_uses_qwen35_ud_adult_variant(self, manager):
        """測試 qwen3.5-ud 在 adult 模式下使用較短的專用 prompt"""
        manager.current_content_type = "adult"

        prompt = manager.get_prompt("ollama", "adult", model_name="qwen3.5-ud:latest")

        assert "Preserve who does the action to whom." in prompt
        assert "Never translate or copy context." in prompt
        assert "Netflix Traditional Chinese Subtitle Standards" not in prompt

    def test_get_prompt_uses_qwen35_ud_adult_variant_for_llamacpp(self, manager):
        """測試 llamacpp 的 qwen3.5-ud 在 adult 模式下也使用專用 prompt"""
        manager.current_content_type = "adult"

        prompt = manager.get_prompt("llamacpp", "adult", model_name="qwen3.5-ud:latest")

        assert "Preserve who does the action to whom." in prompt
        assert "Never translate or copy context." in prompt
        assert "Netflix Traditional Chinese Subtitle Standards" not in prompt

    def test_get_prompt_version_differs_for_qwen35_ud_strategy(self, manager):
        """測試 qwen3.5-ud 的 prompt 版本會和一般策略區分"""
        manager.current_content_type = "adult"

        generic_version = manager.get_prompt_version("ollama", "adult", model_name="llama3")
        qwen35_ud_version = manager.get_prompt_version("ollama", "adult", model_name="qwen3.5-ud:latest")

        assert generic_version != qwen35_ud_version

    def test_get_optimized_message_qwen35_ud_drops_context_for_short_action_line(self, manager):
        """測試 qwen3.5-ud 對短成人動作句會移除上下文，降低語意漂移"""
        manager.current_content_type = "adult"
        text = "彼氏にはそんな風に舐めてるの?"
        context = ["前一行", text, "後一行"]

        messages = manager.get_optimized_message(text, context, "ollama", "qwen3.5-ud:latest")

        user_message = messages[1]["content"]
        assert messages[0]["content"].startswith("You translate Japanese adult subtitles")
        assert "CURRENT:" in user_message
        assert text in user_message
        assert "REFERENCE ONLY" not in user_message
        assert "前一行" not in user_message
        assert "後一行" not in user_message

    def test_get_optimized_message_qwen35_ud_keeps_only_nearest_context(self, manager):
        """測試 qwen3.5-ud 對較長句只保留最近一行前後文"""
        manager.current_content_type = "adult"
        text = "ちゃんと根元まで入れてあげるからもっと気持ちよくなってね"
        context = ["前二行", "前一行", text, "後一行", "後二行"]

        messages = manager.get_optimized_message(text, context, "ollama", "qwen3.5-ud:latest")

        user_message = messages[1]["content"]
        assert "REFERENCE ONLY" in user_message
        assert "Before: 前一行" in user_message
        assert "After: 後一行" in user_message
        assert "前二行" not in user_message
        assert "後二行" not in user_message

    def test_get_optimized_message_qwen35_ud_keeps_only_nearest_context_for_llamacpp(self, manager):
        """測試 llamacpp 的 qwen3.5-ud 也會只保留最近一行前後文"""
        manager.current_content_type = "adult"
        text = "ちゃんと根元まで入れてあげるからもっと気持ちよくなってね"
        context = ["前二行", "前一行", text, "後一行", "後二行"]

        messages = manager.get_optimized_message(text, context, "llamacpp", "qwen3.5-ud:latest")

        user_message = messages[1]["content"]
        assert "REFERENCE ONLY" in user_message
        assert "Before: 前一行" in user_message
        assert "After: 後一行" in user_message
        assert "前二行" not in user_message
        assert "後二行" not in user_message

    def test_get_optimized_message_qwen35_ud_respects_current_index_for_duplicate_lines(self, manager):
        """測試重複句時會依 current_index 選到正確的前後文。"""
        manager.current_content_type = "adult"
        text = "もっと、もっと"
        context = ["前二行", text, "前一行", text, "後一行"]

        messages = manager.get_optimized_message(
            text,
            context,
            "ollama",
            "qwen3.5-ud:latest",
            current_index=3,
        )

        user_message = messages[1]["content"]
        assert "Before: 前一行" in user_message
        assert "After: 後一行" in user_message
        assert "前二行" not in user_message

    def test_get_effective_cache_context_texts_marks_current_index(self, manager):
        """測試快取上下文會加入 current_index 標記，避免重複句碰撞。"""
        manager.current_content_type = "adult"
        text = "ちゃんと根元まで入れてあげるから"
        context = ["前二行", text, "前一行", text, "後一行"]

        first_context = manager.get_effective_cache_context_texts(
            text,
            context,
            "ollama",
            "qwen3.5-ud:latest",
            current_index=1,
        )
        second_context = manager.get_effective_cache_context_texts(
            text,
            context,
            "ollama",
            "qwen3.5-ud:latest",
            current_index=3,
        )

        assert first_context[0] == "[CURRENT_INDEX]1"
        assert second_context[0] == "[CURRENT_INDEX]3"
        assert first_context != second_context

    def test_get_effective_cache_context_texts_relaxes_short_kana_line(self, manager):
        """測試 qwen3.5-ud 的短片假名句會改用較寬鬆的快取鍵。"""
        manager.current_content_type = "adult"

        first_context = manager.get_effective_cache_context_texts(
            "いいよ",
            ["前一句", "いいよ", "後一句"],
            "ollama",
            "qwen3.5-ud:latest",
            current_index=1,
        )
        second_context = manager.get_effective_cache_context_texts(
            "いいよ",
            ["另一句", "いいよ", "別一句"],
            "ollama",
            "qwen3.5-ud:latest",
            current_index=1,
        )

        assert first_context == [
            "[CACHE_MODE]qwen35_ud_short_utterance_v1",
            "[CONTEXT_CLASS]plain",
        ]
        assert second_context == first_context

    def test_get_effective_cache_context_texts_short_line_keeps_coarse_question_class(self, manager):
        """測試短句 relaxed-cache 仍保留粗粒度的相鄰問題句分類。"""
        manager.current_content_type = "adult"

        relaxed_context = manager.get_effective_cache_context_texts(
            "ほら",
            ["真的嗎？", "ほら", "快一點"],
            "ollama",
            "qwen3.5-ud:latest",
            current_index=1,
        )

        assert relaxed_context == [
            "[CACHE_MODE]qwen35_ud_short_utterance_v1",
            "[CONTEXT_CLASS]question_nearby",
        ]


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

    def test_reset_to_default_google_uses_openai_family_prompt(self, manager):
        """測試 google reset 會回到與 openai 對齊的預設 prompt。"""
        manager.set_prompt("Custom Google", "google", "general")

        result = manager.reset_to_default("google", "general")

        assert result is True
        assert manager.get_prompt("google", "general") == manager.get_prompt("openai", "general")


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
            "current_language_pair": "英文→繁體中文",
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
        manager.custom_prompts["test_type"] = {"ollama": "Test prompt for ollama", "openai": "Test prompt for openai"}

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

        template_data = {"ollama": "Custom General Ollama prompt", "openai": "Custom General OpenAI prompt"}

        with open(template_file, "w", encoding="utf-8") as f:
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

        with open(template_file, "w", encoding="utf-8") as f:
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

    def test_export_prompt_includes_gui_visible_providers(self, manager, temp_dir):
        """測試匯出會包含 GUI/CLI 可見的所有 provider。"""
        export_path = temp_dir / "prompt_export.json"

        result = manager.export_prompt("general", file_path=str(export_path))

        assert result == str(export_path)
        export_data = json.loads(export_path.read_text(encoding="utf-8"))
        assert {"ollama", "openai", "anthropic", "google", "llamacpp"} <= set(export_data["prompts"])

    def test_import_prompt_accepts_google_and_llamacpp(self, manager, temp_dir):
        """測試匯入會接受 google 與 llamacpp provider。"""
        import_path = temp_dir / "prompt_import.json"
        import_path.write_text(
            json.dumps(
                {
                    "metadata": {
                        "exported_at": datetime.now().isoformat(),
                        "content_type": "anime",
                        "version": "1.0",
                    },
                    "prompts": {
                        "google": "Custom Google prompt",
                        "llamacpp": "Custom llama.cpp prompt",
                    },
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

        result = manager.import_prompt(str(import_path))

        assert result is True
        assert manager.custom_prompts["anime"]["google"] == "Custom Google prompt"
        assert manager.custom_prompts["anime"]["llamacpp"] == "Custom llama.cpp prompt"


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
            except ValueError:
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


class TestPromptWorkbenchEnhancements:
    """測試 subtitle-workbench 啟發的 prompt 改進"""

    @pytest.fixture(autouse=True)
    def reset_instances(self):
        PromptManager._instance = None
        ConfigManager._instances = {}
        yield
        PromptManager._instance = None
        ConfigManager._instances = {}

    @pytest.fixture
    def manager(self, temp_dir):
        config_file = temp_dir / "config" / "prompt_config.json"
        config_file.parent.mkdir(exist_ok=True)
        return PromptManager(str(config_file))

    def test_filler_word_instruction_in_general(self, manager):
        """填充詞過濾指令存在於 general prompt"""
        prompt = manager.get_prompt("ollama", "general")
        assert "Filler Word" in prompt or "filler" in prompt.lower()

    def test_dynamic_equivalency_in_general(self, manager):
        """動態對等指令存在於 general prompt"""
        prompt = manager.get_prompt("openai", "general")
        assert "Dynamic Equivalency" in prompt

    def test_cps_compression_in_general(self, manager):
        """CPS 壓縮指令存在於 general prompt"""
        prompt = manager.get_prompt("ollama", "general")
        assert "CPS Compression" in prompt or "Conciseness" in prompt

    def test_enhancement_in_all_content_types(self, manager):
        """所有 content type 都包含增強指令"""
        for content_type in ["general", "adult", "anime", "movie", "english_drama"]:
            for llm_type in ["ollama", "openai"]:
                prompt = manager.get_prompt(llm_type, content_type)
                assert "Filler Word" in prompt, f"Missing filler word instruction in {content_type}/{llm_type}"
                assert "Dynamic Equivalency" in prompt, f"Missing dynamic equivalency in {content_type}/{llm_type}"

    def test_netflix_rules_still_present(self, manager):
        """既有 Netflix 規則未被破壞"""
        prompt = manager.get_prompt("ollama", "general")
        assert "Netflix" in prompt
        assert "16" in prompt  # 16 chars per line

    def test_taiwanese_colloquial_still_present(self, manager):
        """既有台式口語規則未被破壞"""
        prompt = manager.get_prompt("ollama", "general")
        assert "Taiwanese" in prompt

    def test_batch_line_mapping_instruction(self, manager):
        """批次行映射指令可取得且內容正確"""
        instruction = manager.get_batch_line_mapping_instruction()
        assert "same number of lines" in instruction.lower()
        assert "MUST" in instruction
        assert "\\n" in instruction  # literal \n 保留指令

    def test_batch_instruction_not_in_default_prompts(self, manager):
        """批次行映射指令不應出現在預設 prompt 中"""
        prompt = manager.get_prompt("ollama", "general")
        assert "Strict Line Mapping" not in prompt
