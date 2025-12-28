"""Pytest 共享配置與 Fixtures

此檔案定義了所有測試共享的配置、fixtures 和 hooks。
"""

import sys
import tempfile
from pathlib import Path
from typing import Generator

import pytest

# ============================================================
# 環境配置
# ============================================================

# 將 src 目錄加入 Python 路徑
ROOT_DIR = Path(__file__).parent.parent
SRC_DIR = ROOT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


# ============================================================
# 基礎 Fixtures
# ============================================================


@pytest.fixture
def temp_dir() -> Generator[Path, None, None]:
    """提供臨時目錄，測試結束後自動清理

    注意：在 Windows 上，若資料庫檔案仍被鎖定，清理可能失敗。
    使用 ignore_cleanup_errors=True 避免測試失敗。
    """
    # Python 3.10+ 支援 ignore_cleanup_errors 參數
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def sample_srt_content() -> str:
    """提供範例 SRT 字幕內容"""
    return """1
00:00:01,000 --> 00:00:03,000
Hello, world!

2
00:00:04,000 --> 00:00:06,000
This is a test subtitle.

3
00:00:07,000 --> 00:00:09,000
Testing SRT translation.
"""


@pytest.fixture
def sample_srt_file(temp_dir: Path, sample_srt_content: str) -> Path:
    """建立範例 SRT 檔案"""
    srt_file = temp_dir / "test.srt"
    srt_file.write_text(sample_srt_content, encoding="utf-8")
    return srt_file


# ============================================================
# 配置相關 Fixtures
# ============================================================


@pytest.fixture
def mock_config_data() -> dict:
    """提供模擬配置資料"""
    return {
        "ollama": {
            "api_base": "http://localhost:11434",
            "model": "llama2",
            "timeout": 300,
        },
        "openai": {
            "api_key": "test-api-key",
            "model": "gpt-3.5-turbo",
            "max_tokens": 150,
        },
        "anthropic": {
            "api_key": "test-api-key",
            "model": "claude-3-haiku-20240307",
            "max_tokens": 1024,
        },
        "translation": {
            "source_lang": "en",
            "target_lang": "zh-TW",
            "batch_size": 10,
            "max_retries": 3,
        },
    }


@pytest.fixture
def config_file(temp_dir: Path, mock_config_data: dict) -> Path:
    """建立配置檔案"""
    import json

    config_file = temp_dir / "config.json"
    config_file.write_text(json.dumps(mock_config_data, indent=2), encoding="utf-8")
    return config_file


# ============================================================
# Cache 相關 Fixtures
# ============================================================


@pytest.fixture
def mock_cache_data() -> dict:
    """提供模擬快取資料"""
    return {
        "Hello, world!": "你好，世界！",
        "This is a test subtitle.": "這是一個測試字幕。",
        "Testing SRT translation.": "測試 SRT 翻譯。",
    }


# ============================================================
# pytest 配置 Hooks
# ============================================================


def pytest_configure(config):
    """pytest 啟動時的配置"""
    # 註冊自定義標記
    config.addinivalue_line("markers", "unit: Unit tests")
    config.addinivalue_line("markers", "integration: Integration tests")
    config.addinivalue_line("markers", "slow: Slow running tests")
    config.addinivalue_line("markers", "gui: Tests requiring GUI")


def pytest_collection_modifyitems(config, items):
    """修改收集到的測試項目"""
    # 為單元測試自動加上 @pytest.mark.unit
    for item in items:
        if "unit" in str(item.fspath):
            item.add_marker(pytest.mark.unit)
        elif "integration" in str(item.fspath):
            item.add_marker(pytest.mark.integration)
