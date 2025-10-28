"""整合測試共用 fixtures

此檔案定義了整合測試專用的 fixtures，提供完整的測試環境設定。
"""

import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from srt_translator.core.cache import CacheManager
from srt_translator.core.config import ConfigManager
from srt_translator.core.prompt import PromptManager
from srt_translator.core.models import ModelManager


@pytest.fixture(scope="function")
def integration_env(temp_dir):
    """提供完整的整合測試環境

    此 fixture 設定一個隔離的測試環境，包括：
    - 臨時配置目錄
    - 臨時快取資料庫
    - 模擬的 API 客戶端
    - 所有核心管理器的實例

    使用後會自動清理。
    """
    # 1. 建立測試目錄結構
    config_dir = temp_dir / "config"
    data_dir = temp_dir / "data"
    config_dir.mkdir(exist_ok=True)
    data_dir.mkdir(exist_ok=True)

    # 2. 建立測試配置檔案
    test_config = {
        "app": {
            "version": "1.0.0",
            "debug_mode": True,
            "log_level": "INFO",
        },
        "model": {
            "default_provider": "ollama",
            "timeout": 30,
        },
        "translation": {
            "source_lang": "en",
            "target_lang": "zh-TW",
            "batch_size": 10,
        },
        "cache": {
            "enabled": True,
            "max_memory_cache": 100,
            "auto_cleanup_days": 7,
        },
        "ollama": {
            "api_base": "http://localhost:11434",
            "model": "llama2",
            "timeout": 300,
        },
        "openai": {
            "api_key": "test-openai-key",
            "model": "gpt-3.5-turbo",
            "max_tokens": 150,
        },
        "anthropic": {
            "api_key": "test-anthropic-key",
            "model": "claude-3-haiku-20240307",
            "max_tokens": 1024,
        },
    }

    app_config_path = config_dir / "app_config.json"
    app_config_path.write_text(json.dumps(test_config, indent=2), encoding="utf-8")

    # 3. 重置所有單例
    CacheManager._instance = None
    ConfigManager._instances = {}
    PromptManager._instance = None
    ModelManager._instance = None

    # 4. 建立管理器實例（使用臨時路徑）
    cache_path = data_dir / "test_cache.db"
    cache_manager = CacheManager(str(cache_path))

    # 配置管理器需要特殊處理（它會自動載入配置）
    # 我們先不直接實例化，讓測試自行決定如何使用

    # 5. 返回測試環境
    env = {
        "temp_dir": temp_dir,
        "config_dir": config_dir,
        "data_dir": data_dir,
        "config_path": app_config_path,
        "cache_path": cache_path,
        "cache_manager": cache_manager,
        "test_config": test_config,
    }

    yield env

    # 6. 清理（確保資料庫連線關閉）
    if cache_manager and hasattr(cache_manager, 'conn') and cache_manager.conn:
        cache_manager.conn.close()

    # 重置單例
    CacheManager._instance = None
    ConfigManager._instances = {}
    PromptManager._instance = None
    ModelManager._instance = None


@pytest.fixture
def mock_translation_api():
    """模擬翻譯 API 回應

    提供一個 mock 的非同步翻譯函數，用於測試翻譯流程
    而無需實際呼叫 API。
    """
    async def mock_translate(text, source_lang="en", target_lang="zh-TW", **kwargs):
        """模擬翻譯函數"""
        # 簡單的模擬：將英文轉換為固定的中文
        translations = {
            "Hello, world!": "你好，世界！",
            "This is a test.": "這是一個測試。",
            "Testing translation.": "測試翻譯。",
            "Good morning!": "早安！",
            "Thank you.": "謝謝。",
        }
        return translations.get(text, f"[已翻譯] {text}")

    return mock_translate


@pytest.fixture
def sample_srt_subtitles(temp_dir):
    """提供範例 SRT 字幕檔案

    建立一個包含多個字幕的 SRT 檔案，用於測試完整流程。
    """
    srt_content = """1
00:00:01,000 --> 00:00:03,000
Hello, world!

2
00:00:04,000 --> 00:00:06,000
This is a test.

3
00:00:07,000 --> 00:00:09,000
Testing translation.

4
00:00:10,000 --> 00:00:12,000
Good morning!

5
00:00:13,000 --> 00:00:15,000
Thank you.
"""

    srt_path = temp_dir / "test_subtitles.srt"
    srt_path.write_text(srt_content, encoding="utf-8")

    return {
        "path": srt_path,
        "content": srt_content,
        "subtitle_count": 5,
    }


@pytest.fixture
def mock_model_client():
    """模擬模型客戶端

    提供模擬的 API 客戶端，避免實際呼叫外部服務。
    """
    client = MagicMock()

    # 模擬 OpenAI 客戶端
    openai_response = MagicMock()
    openai_response.choices = [MagicMock(message=MagicMock(content="翻譯結果"))]
    client.chat.completions.create = AsyncMock(return_value=openai_response)

    # 模擬 Anthropic 客戶端
    anthropic_response = MagicMock()
    anthropic_response.content = [MagicMock(text="翻譯結果")]
    client.messages.create = AsyncMock(return_value=anthropic_response)

    return client


@pytest.fixture
def integration_cleanup():
    """整合測試清理 fixture

    確保每個整合測試結束後都正確清理所有資源。
    """
    yield

    # 清理所有單例
    CacheManager._instance = None
    ConfigManager._instances = {}
    PromptManager._instance = None
    ModelManager._instance = None

    # 強制垃圾回收
    import gc
    gc.collect()
