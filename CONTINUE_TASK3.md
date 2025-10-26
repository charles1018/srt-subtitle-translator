# 🚀 階段一任務 3：建立單元測試框架 - 開場白

> **建立日期**：2025-10-26
> **當前分支**：feature/modularity
> **前置任務**：✅ 任務 1-2 已完成（100%）

---

## 📋 新對話開場白（複製使用）

```
我要開始階段一任務 3：建立單元測試框架。

## 當前狀態

### ✅ 已完成工作
- ✅ 任務 1：pyproject.toml 配置完成（100%）
- ✅ 任務 2：套件結構重組完成（100%）
  - 建立 src/srt_translator/ 套件結構
  - 修正所有模組導入語句
  - 清理根目錄舊檔案
  - 測試驗證通過

### 📊 專案資訊
- **專案路徑**：D:\dev\project\coding_assistant\charles1018\claude\srt-subtitle-translator
- **當前分支**：feature/modularity
- **最新提交**：7835727 (chore: 清理根目錄舊檔案)
- **套件結構**：src/srt_translator/ (20 個檔案)
- **Python 版本**：>=3.8
- **測試框架**：pytest (已在 pyproject.toml 配置)

## 任務 3 目標

建立完整的單元測試框架，確保代碼品質和穩定性。

### 主要工作項目

1. **建立測試目錄結構**
   - 創建 tests/ 目錄
   - 建立對應套件的測試子目錄
   - 創建 conftest.py 共享配置

2. **編寫基礎測試用例**
   - utils 模組測試（errors, helpers, logging_config）
   - core 模組測試（config, cache, models, prompt）
   - 基本功能驗證測試

3. **配置測試工具**
   - 驗證 pytest 配置（pyproject.toml）
   - 設定代碼覆蓋率報告
   - 配置測試標記（unit, integration, slow）

4. **建立測試文檔**
   - 測試執行指南
   - 測試撰寫規範
   - CI/CD 整合準備

### 預期產出

- tests/ 目錄結構完整
- 至少 10-15 個基礎測試用例
- 代碼覆蓋率 > 50%（初始目標）
- 測試執行文檔

### 參考文檔

請參考以下已有配置：
1. pyproject.toml - pytest 配置（行 186-223）
2. src/srt_translator/ - 待測試的套件結構
3. CLAUDE.md - 開發指南

## 開始工作

請確認您已閱讀以上資訊，然後我們開始建立測試框架。

預估時間：2-3 小時
```

---

## 📂 建議的測試目錄結構

```
tests/
├── __init__.py
├── conftest.py                    # pytest 共享配置
│
├── unit/                          # 單元測試
│   ├── __init__.py
│   ├── test_utils_errors.py       # 測試 utils.errors
│   ├── test_utils_helpers.py      # 測試 utils.helpers
│   ├── test_utils_logging.py      # 測試 utils.logging_config
│   ├── test_core_config.py        # 測試 core.config
│   ├── test_core_cache.py         # 測試 core.cache
│   └── test_core_models.py        # 測試 core.models
│
├── integration/                   # 整合測試
│   ├── __init__.py
│   └── test_translation_flow.py   # 測試翻譯流程
│
└── fixtures/                      # 測試數據
    ├── __init__.py
    ├── sample_config.json
    └── sample.srt
```

---

## 🎯 測試優先級

### 優先級 1：基礎工具測試（必做）
- ✅ utils.errors - 錯誤類別測試
- ✅ utils.helpers - 工具函數測試
- ✅ core.config - 配置管理測試

### 優先級 2：核心功能測試（重要）
- ⏳ core.cache - 快取功能測試
- ⏳ core.models - 模型管理測試
- ⏳ core.prompt - 提示詞管理測試

### 優先級 3：整合測試（後續）
- ⏳ translation.client - 翻譯客戶端測試
- ⏳ file_handling.handler - 檔案處理測試

---

## 📝 測試撰寫範例

### 範例 1：測試錯誤類別

```python
# tests/unit/test_utils_errors.py

import pytest
from srt_translator.utils.errors import (
    AppError, ConfigError, ModelError,
    TranslationError, FileError, NetworkError
)

class TestAppError:
    """測試 AppError 基礎類別"""

    def test_app_error_basic(self):
        """測試基本錯誤創建"""
        error = AppError("Test error", error_code=1000)
        assert error.message == "Test error"
        assert error.error_code == 1000

    def test_app_error_with_details(self):
        """測試帶詳細資訊的錯誤"""
        details = {"file": "test.py", "line": 42}
        error = AppError("Test error", details=details)
        assert error.details == details

    def test_app_error_to_dict(self):
        """測試錯誤轉換為字典"""
        error = AppError("Test error", error_code=1000)
        error_dict = error.to_dict()

        assert error_dict["error_code"] == 1000
        assert error_dict["message"] == "Test error"
        assert "timestamp" in error_dict

class TestConfigError:
    """測試 ConfigError"""

    def test_config_error_code(self):
        """測試 ConfigError 錯誤代碼"""
        error = ConfigError("Config failed")
        assert error.error_code == 1100
```

### 範例 2：測試工具函數

```python
# tests/unit/test_utils_helpers.py

import pytest
from srt_translator.utils.helpers import (
    clean_text, detect_language,
    format_elapsed_time, ProgressTracker
)

class TestTextProcessing:
    """測試文本處理工具"""

    def test_clean_text_removes_extra_spaces(self):
        """測試清理多餘空格"""
        text = "  Hello   World  "
        result = clean_text(text)
        assert result == "Hello World"

    def test_clean_text_removes_control_chars(self):
        """測試移除控制字符"""
        text = "Hello\x00World\x1F"
        result = clean_text(text)
        assert "\x00" not in result
        assert "\x1F" not in result

class TestLanguageDetection:
    """測試語言檢測"""

    @pytest.mark.parametrize("text,expected", [
        ("こんにちは", "ja"),
        ("Hello World", "en"),
        ("你好世界", "zh-cn"),
    ])
    def test_detect_language(self, text, expected):
        """測試語言檢測準確性"""
        result = detect_language(text)
        assert result == expected

class TestProgressTracker:
    """測試進度追蹤器"""

    def test_progress_tracker_initialization(self):
        """測試初始化"""
        tracker = ProgressTracker(total=100, description="Test")
        assert tracker.total == 100
        assert tracker.description == "Test"
        assert tracker.current == 0

    def test_progress_tracker_increment(self):
        """測試進度增加"""
        tracker = ProgressTracker(total=100)
        tracker.start()
        tracker.increment(10)
        assert tracker.current == 10
        assert tracker.get_progress_percentage() == 10.0
```

---

## 🔧 測試執行命令

```bash
# 執行所有測試
uv run pytest

# 執行特定測試檔案
uv run pytest tests/unit/test_utils_errors.py

# 執行特定測試類別
uv run pytest tests/unit/test_utils_errors.py::TestAppError

# 執行特定測試函數
uv run pytest tests/unit/test_utils_errors.py::TestAppError::test_app_error_basic

# 查看覆蓋率報告
uv run pytest --cov=src/srt_translator --cov-report=html
# 然後開啟 htmlcov/index.html

# 只執行單元測試
uv run pytest -m unit

# 跳過慢速測試
uv run pytest -m "not slow"

# 詳細輸出
uv run pytest -v

# 顯示 print 輸出
uv run pytest -s
```

---

## 📊 成功標準

任務 3 完成的標準：

1. ✅ 測試目錄結構完整（tests/ 包含 unit/, integration/, fixtures/）
2. ✅ 至少 10 個基礎測試用例通過
3. ✅ 代碼覆蓋率 >= 50%
4. ✅ pytest 配置驗證通過
5. ✅ 測試執行文檔完成
6. ✅ 所有測試在 CI 環境可執行

---

## 🎓 測試撰寫最佳實踐

### 1. 測試命名規範
- 測試檔案：`test_*.py`
- 測試類別：`Test*`
- 測試函數：`test_*`
- 描述性命名，清楚說明測試目的

### 2. AAA 模式
```python
def test_example():
    # Arrange（準備）
    data = "test data"

    # Act（執行）
    result = process(data)

    # Assert（斷言）
    assert result == expected
```

### 3. 使用 Fixtures
```python
@pytest.fixture
def sample_config():
    """提供測試用配置"""
    return {
        "api_key": "test_key",
        "model": "test_model"
    }

def test_with_fixture(sample_config):
    """使用 fixture 的測試"""
    assert sample_config["api_key"] == "test_key"
```

### 4. 參數化測試
```python
@pytest.mark.parametrize("input,expected", [
    (1, 2),
    (2, 4),
    (3, 6),
])
def test_multiply_by_two(input, expected):
    assert input * 2 == expected
```

---

## 🔗 相關資源

- **pytest 官方文檔**：https://docs.pytest.org/
- **pytest-cov 文檔**：https://pytest-cov.readthedocs.io/
- **測試金字塔**：單元測試 > 整合測試 > E2E 測試

---

**預估時間**：2-3 小時
**難度等級**：⭐⭐⭐ (中等)
**依賴項目**：pyproject.toml (pytest 配置已完成)

**準備好了嗎？讓我們開始建立測試框架！** 🚀
