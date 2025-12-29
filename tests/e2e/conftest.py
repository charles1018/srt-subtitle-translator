"""E2E 測試共享 Fixtures

此檔案定義了 E2E 測試所需的 fixtures 和輔助工具。
"""

import shutil
import sys
import tempfile
from pathlib import Path
from typing import Dict, Generator, List
from unittest.mock import AsyncMock, Mock, patch

import pysrt
import pytest

# 將 src 目錄加入 Python 路徑
ROOT_DIR = Path(__file__).parent.parent.parent
SRC_DIR = ROOT_DIR / "src"
sys.path.insert(0, str(SRC_DIR))


# ============================================================
# E2E 測試目錄與檔案 Fixtures
# ============================================================


@pytest.fixture
def e2e_temp_dir() -> Generator[Path, None, None]:
    """提供 E2E 測試專用的臨時目錄

    此目錄會在測試結束後自動清理。
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def fixtures_dir() -> Path:
    """提供 E2E 測試 fixtures 目錄路徑"""
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_srt_path(fixtures_dir: Path) -> Path:
    """提供範例 SRT 檔案路徑"""
    return fixtures_dir / "sample.srt"


@pytest.fixture
def invalid_srt_path(fixtures_dir: Path) -> Path:
    """提供無效 SRT 檔案路徑"""
    return fixtures_dir / "invalid.srt"


@pytest.fixture
def expected_translated_srt_path(fixtures_dir: Path) -> Path:
    """提供預期的翻譯結果檔案路徑"""
    return fixtures_dir / "expected" / "sample_translated.srt"


@pytest.fixture
def sample_japanese_srt_path(fixtures_dir: Path) -> Path:
    """提供日文 SRT 檔案路徑"""
    return fixtures_dir / "sample_japanese.srt"


@pytest.fixture
def large_sample_srt_path(fixtures_dir: Path) -> Path:
    """提供大型測試 SRT 檔案路徑（10 個字幕）"""
    return fixtures_dir / "large_sample.srt"


@pytest.fixture
def copy_sample_srt(sample_srt_path: Path, e2e_temp_dir: Path) -> Path:
    """複製範例 SRT 檔案到臨時目錄

    這樣可以避免修改原始測試檔案。
    """
    dest = e2e_temp_dir / "test.srt"
    shutil.copy(sample_srt_path, dest)
    return dest


@pytest.fixture
def custom_config_path(fixtures_dir: Path) -> Path:
    """提供自訂配置檔案路徑"""
    return fixtures_dir / "config_custom.json"


@pytest.fixture
def invalid_config_path(fixtures_dir: Path) -> Path:
    """提供無效配置檔案路徑"""
    return fixtures_dir / "config_invalid.json"


@pytest.fixture
def empty_srt_path(fixtures_dir: Path) -> Path:
    """提供空 SRT 檔案路徑"""
    return fixtures_dir / "empty.srt"


@pytest.fixture
def batch_srt_files(fixtures_dir: Path) -> List[Path]:
    """提供批量測試用的多個 SRT 檔案路徑"""
    batch_dir = fixtures_dir / "batch"
    return [
        batch_dir / "file1.srt",
        batch_dir / "file2.srt",
        batch_dir / "file3.srt",
    ]


@pytest.fixture
def very_large_srt_path(fixtures_dir: Path) -> Path:
    """提供超大 SRT 檔案路徑（100+ 字幕）"""
    return fixtures_dir / "very_large.srt"


@pytest.fixture
def long_subtitle_srt_path(fixtures_dir: Path) -> Path:
    """提供超長字幕 SRT 檔案路徑"""
    return fixtures_dir / "long_subtitle.srt"


@pytest.fixture
def special_chars_srt_path(fixtures_dir: Path) -> Path:
    """提供包含特殊字符的 SRT 檔案路徑"""
    return fixtures_dir / "special_chars.srt"


# ============================================================
# Mock 服務 Fixtures
# ============================================================


@pytest.fixture
def mock_translation_responses() -> Dict[str, str]:
    """提供 Mock 翻譯回應

    支持多語言 -> 繁體中文翻譯
    """
    responses = {
        # 英文 -> 繁體中文
        "Hello, world!": "你好，世界！",
        "This is a test subtitle.": "這是一個測試字幕。",
        "Welcome to the translation system.": "歡迎使用翻譯系統。",
        "Testing SRT translation.": "測試 SRT 翻譯。",
        "Welcome to the subtitle translator.": "歡迎使用字幕翻譯器。",
        "This tool helps you translate subtitles.": "這個工具幫助您翻譯字幕。",
        "It supports multiple languages.": "它支持多種語言。",
        "You can translate from English to Chinese.": "您可以從英文翻譯成中文。",
        "The system uses AI for translation.": "系統使用人工智慧進行翻譯。",
        "Translation quality is high.": "翻譯質量很高。",
        "Cache mechanism improves performance.": "快取機制提升效能。",
        "Multiple files can be processed.": "可以處理多個檔案。",
        "Thank you for using our tool.": "感謝您使用我們的工具。",
        "Enjoy your translation experience!": "享受您的翻譯體驗！",
        # 日文 -> 繁體中文
        "こんにちは、世界！": "你好，世界！",
        "これはテスト字幕です。": "這是測試字幕。",
        "翻訳システムへようこそ。": "歡迎使用翻譯系統。",
        # 批量測試檔案 (file1.srt)
        "Welcome to batch translation test.": "歡迎使用批量翻譯測試。",
        "This is the first file.": "這是第一個檔案。",
        "It contains three subtitles.": "它包含三個字幕。",
        # 批量測試檔案 (file2.srt)
        "Batch processing is efficient.": "批量處理很高效。",
        "Multiple files can be translated simultaneously.": "多個檔案可以同時翻譯。",
        "This improves productivity.": "這提升了生產力。",
        # 批量測試檔案 (file3.srt)
        "Testing batch translation feature.": "測試批量翻譯功能。",
        "All files should be processed correctly.": "所有檔案都應正確處理。",
        "Quality should remain consistent.": "品質應保持一致。",
        # 長字幕測試
        "Normal subtitle after long one.": "長字幕後的普通字幕。",
        "Testing continues.": "測試繼續。",
        # 特殊字符測試
        "Special characters test: 你好世界! 🌍🚀": "特殊字符測試：你好世界！🌍🚀",
        "Emojis: 😀😎🎉 ❤️💯✨": "表情符號：😀😎🎉 ❤️💯✨",
        "Symbols: @#$%^&*()_+-=[]{}|;':\"<>,.?/": "符號：@#$%^&*()_+-=[]{}|;':\"<>,.?/",
        "Mixed: Hello世界 Test測試 123！": "混合：Hello 世界 Test 測試 123！",
        "Unicode: 你好 αβγ абв": "統一碼：你好 αβγ абв",
    }

    # 為 very_large.srt 動態生成翻譯（100+ 個字幕）
    for i in range(1, 101):
        text = f"This is subtitle number {i}. Testing large file processing."
        responses[text] = f"這是字幕編號 {i}。測試大型檔案處理。"

    return responses


@pytest.fixture
def mock_translation_client(mock_translation_responses: Dict[str, str]):
    """提供 Mock 的翻譯客戶端

    這個 Mock 客戶端會返回預設的翻譯結果，而不會真正呼叫 API。
    """
    client = AsyncMock()

    async def mock_translate(text: str, context: List[str], model_name: str) -> str:
        """Mock 翻譯函數"""
        # 返回預定義的翻譯或原文
        return mock_translation_responses.get(text, f"[Mock翻譯] {text}")

    async def mock_translate_batch(texts_with_context: List, model_name: str, concurrent_limit: int = 5) -> List[str]:
        """Mock 批量翻譯函數"""
        results = []
        for text, context in texts_with_context:
            translation = mock_translation_responses.get(text, f"[Mock翻譯] {text}")
            results.append(translation)
        return results

    client.translate_text = mock_translate
    client.translate_batch = mock_translate_batch
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    return client


@pytest.fixture
def mock_model_service(mock_translation_client):
    """提供 Mock 的模型服務

    這樣可以避免實際初始化模型客戶端。
    """
    with patch("srt_translator.services.factory.ModelService") as MockModelService:
        mock_service = Mock()
        mock_service.get_translation_client = AsyncMock(return_value=mock_translation_client)
        mock_service.get_available_models = AsyncMock(return_value=["test-model"])
        mock_service.api_keys = {"openai": "test-key", "ollama": ""}
        MockModelService.return_value = mock_service
        yield mock_service


@pytest.fixture
def mock_cache_service():
    """提供 Mock 的快取服務

    預設快取為空，可以用於測試快取行為。
    """
    with patch("srt_translator.services.factory.CacheService") as MockCacheService:
        mock_service = Mock()
        mock_service.get_translation = Mock(return_value=None)  # 預設無快取
        mock_service.store_translation = Mock(return_value=True)
        mock_service.get_cache_stats = Mock(return_value={"total_entries": 0, "cache_size_mb": 0, "hit_rate": 0})
        MockCacheService.return_value = mock_service
        yield mock_service


# ============================================================
# 測試輔助工具
# ============================================================


class SRTComparator:
    """SRT 檔案比對工具

    用於比對兩個 SRT 檔案是否相同（忽略時間軸，只比對文字內容）
    """

    @staticmethod
    def compare_content(file1: Path, file2: Path, compare_timing: bool = False) -> bool:
        """比對兩個 SRT 檔案的內容

        Args:
            file1: 第一個 SRT 檔案路徑
            file2: 第二個 SRT 檔案路徑
            compare_timing: 是否比對時間軸（預設為 False）

        Returns:
            是否相同
        """
        try:
            subs1 = pysrt.open(str(file1), encoding="utf-8")
            subs2 = pysrt.open(str(file2), encoding="utf-8")

            if len(subs1) != len(subs2):
                return False

            for sub1, sub2 in zip(subs1, subs2):
                # 比對文字內容
                if sub1.text.strip() != sub2.text.strip():
                    return False

                # 如果需要，比對時間軸
                if compare_timing:
                    if sub1.start != sub2.start or sub1.end != sub2.end:
                        return False

            return True
        except Exception as e:
            print(f"比對 SRT 檔案時發生錯誤: {e}")
            return False

    @staticmethod
    def get_subtitle_texts(file_path: Path) -> List[str]:
        """取得 SRT 檔案中的所有字幕文字

        Args:
            file_path: SRT 檔案路徑

        Returns:
            字幕文字列表
        """
        try:
            subs = pysrt.open(str(file_path), encoding="utf-8")
            return [sub.text.strip() for sub in subs]
        except Exception as e:
            print(f"讀取 SRT 檔案時發生錯誤: {e}")
            return []


@pytest.fixture
def srt_comparator() -> SRTComparator:
    """提供 SRT 檔案比對工具"""
    return SRTComparator()


@pytest.fixture
def assert_srt_valid():
    """提供 SRT 檔案驗證函數

    用於驗證 SRT 檔案格式是否正確。
    """

    def _assert_valid(file_path: Path) -> None:
        """驗證 SRT 檔案格式

        Args:
            file_path: SRT 檔案路徑

        Raises:
            AssertionError: 如果檔案格式無效
        """
        assert file_path.exists(), f"SRT 檔案不存在: {file_path}"

        try:
            subs = pysrt.open(str(file_path), encoding="utf-8")
            assert len(subs) > 0, "SRT 檔案不應該是空的"

            for i, sub in enumerate(subs):
                assert sub.text.strip(), f"字幕 {i + 1} 的文字不應該是空的"
                assert sub.start is not None, f"字幕 {i + 1} 缺少開始時間"
                assert sub.end is not None, f"字幕 {i + 1} 缺少結束時間"
                assert sub.start < sub.end, f"字幕 {i + 1} 的開始時間應該早於結束時間"
        except Exception as e:
            pytest.fail(f"SRT 檔案格式無效: {e}")

    return _assert_valid


# ============================================================
# 環境設定 Fixtures
# ============================================================


@pytest.fixture(autouse=True)
def setup_e2e_environment(e2e_temp_dir: Path, monkeypatch):
    """自動設定 E2E 測試環境

    此 fixture 會自動應用於所有 E2E 測試，設定測試所需的環境變數。
    """
    # 設定測試模式環境變數
    monkeypatch.setenv("TEST_MODE", "1")

    # 設定快取資料庫路徑為臨時目錄
    cache_db_path = e2e_temp_dir / "test_cache.db"
    monkeypatch.setenv("CACHE_DB_PATH", str(cache_db_path))

    # 設定輸出目錄為臨時目錄
    output_dir = e2e_temp_dir / "output"
    output_dir.mkdir(exist_ok=True)
    monkeypatch.setenv("OUTPUT_DIR", str(output_dir))

    yield

    # 測試結束後的清理工作（如果需要）


# ============================================================
# pytest 配置
# ============================================================


def pytest_configure(config):
    """pytest 啟動時的配置"""
    # 註冊 E2E 測試標記
    config.addinivalue_line("markers", "e2e: End-to-end tests")


def pytest_collection_modifyitems(config, items):
    """修改收集到的測試項目"""
    # 為 E2E 測試自動加上 @pytest.mark.e2e
    for item in items:
        if "e2e" in str(item.fspath):
            item.add_marker(pytest.mark.e2e)
