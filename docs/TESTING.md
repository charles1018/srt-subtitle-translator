# 測試文檔 - SRT Subtitle Translator

## 📋 目錄

- [概覽](#概覽)
- [測試結構](#測試結構)
- [執行測試](#執行測試)
- [覆蓋率報告](#覆蓋率報告)
- [撰寫測試](#撰寫測試)
- [CI/CD 整合](#cicd-整合)

---

## 概覽

本專案使用 **pytest** 作為測試框架，配合 **pytest-cov** 生成覆蓋率報告。測試分為單元測試和整合測試兩大類。

### 測試統計

- **總測試數量**: 84 個
- **測試通過率**: 100% (84/84 passed)
- **代碼覆蓋率**:
  - errors.py: 100%
  - helpers.py: 63%
  - logging_config.py: 70%
  - 總體覆蓋率: 13% (初始基礎)

---

## 測試結構

```
tests/
├── __init__.py              # 測試套件初始化
├── conftest.py              # pytest 共享配置與 fixtures
│
├── unit/                    # 單元測試
│   ├── core/                # core 模組測試
│   │   ├── __init__.py
│   │   ├── test_cache.py    # 快取管理器測試
│   │   ├── test_config.py   # 配置管理器測試
│   │   └── test_models.py   # 模型資訊測試
│   │
│   └── utils/               # utils 模組測試
│       ├── __init__.py
│       ├── test_errors.py         # 錯誤類別測試
│       ├── test_helpers.py        # 輔助函數測試
│       └── test_logging_config.py # 日誌配置測試
│
├── integration/             # 整合測試（待開發）
└── fixtures/                # 測試夾具與資料
```

---

## 執行測試

### 基本命令

```bash
# 執行所有測試
uv run pytest

# 執行特定測試檔案
uv run pytest tests/unit/utils/test_errors.py

# 執行特定測試類別
uv run pytest tests/unit/utils/test_errors.py::TestAppError

# 執行特定測試函數
uv run pytest tests/unit/utils/test_errors.py::TestAppError::test_app_error_basic
```

### 常用選項

```bash
# 顯示詳細輸出
uv run pytest -v

# 只執行單元測試
uv run pytest -m unit

# 跳過慢速測試
uv run pytest -m "not slow"

# 顯示測試覆蓋率
uv run pytest --cov=src/srt_translator

# 生成 HTML 覆蓋率報告
uv run pytest --cov=src/srt_translator --cov-report=html

# 只執行失敗的測試
uv run pytest --lf

# 並行執行測試（需要 pytest-xdist）
uv run pytest -n auto
```

### 使用測試標記

專案定義了以下測試標記：

- `@pytest.mark.unit` - 單元測試
- `@pytest.mark.integration` - 整合測試
- `@pytest.mark.slow` - 慢速測試
- `@pytest.mark.gui` - 需要 GUI 的測試

```bash
# 只執行單元測試
uv run pytest -m unit

# 只執行整合測試
uv run pytest -m integration

# 執行非 GUI 測試
uv run pytest -m "not gui"
```

---

## 覆蓋率報告

### 生成報告

```bash
# 終端機顯示覆蓋率
uv run pytest --cov=src/srt_translator --cov-report=term-missing

# 生成 HTML 報告
uv run pytest --cov=src/srt_translator --cov-report=html

# 同時生成多種格式
uv run pytest --cov=src/srt_translator \
  --cov-report=term-missing \
  --cov-report=html \
  --cov-report=xml
```

### 查看 HTML 報告

```bash
# Windows
start htmlcov/index.html

# macOS
open htmlcov/index.html

# Linux
xdg-open htmlcov/index.html
```

### 覆蓋率目標

- **短期目標**: 核心模組覆蓋率 > 60%
- **中期目標**: 總體覆蓋率 > 70%
- **長期目標**: 總體覆蓋率 > 85%

---

## 撰寫測試

### 基本原則

1. **一個測試一個斷言** - 保持測試簡潔明確
2. **使用描述性名稱** - 測試名稱應清楚說明測試目的
3. **遵循 AAA 模式** - Arrange (準備), Act (執行), Assert (斷言)
4. **避免測試間依賴** - 每個測試應該獨立執行
5. **使用 fixtures** - 共用設置邏輯應放在 fixtures 中

### 測試命名規範

```python
def test_<function>_<scenario>_<expected_result>():
    """測試 <功能> 在 <情境> 下應該 <預期結果>"""
    pass

# 範例
def test_clean_text_with_multiple_spaces_returns_single_space():
    """測試清理文本時多個空格應該被替換為單個空格"""
    pass
```

### 使用 Fixtures

```python
import pytest

@pytest.fixture
def sample_config():
    """提供範例配置資料"""
    return {
        "model": "llama2",
        "timeout": 300,
    }

def test_config_loading(sample_config):
    """測試配置載入"""
    assert sample_config["model"] == "llama2"
```

### 測試例外

```python
import pytest
from srt_translator.utils.errors import ConfigError

def test_invalid_config_raises_error():
    """測試無效配置應拋出錯誤"""
    with pytest.raises(ConfigError) as exc_info:
        load_invalid_config()

    assert "Configuration failed" in str(exc_info.value)
```

### 測試非同步代碼

```python
import pytest

@pytest.mark.asyncio
async def test_async_translation():
    """測試非同步翻譯功能"""
    result = await translate_async("Hello")
    assert result is not None
```

---

## 模擬與測試替身

### 使用 pytest-mock

```python
def test_api_call_with_mock(mocker):
    """測試 API 呼叫（使用 mock）"""
    # 模擬 HTTP 請求
    mock_get = mocker.patch('requests.get')
    mock_get.return_value.json.return_value = {"result": "success"}

    result = call_api()
    assert result["result"] == "success"
```

### 使用 monkeypatch

```python
def test_environment_variable(monkeypatch):
    """測試環境變數"""
    monkeypatch.setenv("API_KEY", "test-key")
    assert os.getenv("API_KEY") == "test-key"
```

---

## CI/CD 整合

### GitHub Actions 範例

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
    - uses: actions/checkout@v3

    - name: Install uv
      run: curl -LsSf https://astral.sh/uv/install.sh | sh

    - name: Install dependencies
      run: uv sync --all-extras --dev

    - name: Run tests
      run: uv run pytest --cov=src/srt_translator

    - name: Upload coverage
      uses: codecov/codecov-action@v3
```

---

## 故障排除

### Windows 文件清理問題

在 Windows 上執行測試時，可能會遇到 `PermissionError`，這是因為日誌檔案在測試結束後仍被佔用。

**解決方案**:
1. 在測試中明確關閉日誌處理程序
2. 使用 `@pytest.fixture(scope="function")` 確保每個測試後清理
3. 忽略這些錯誤（不影響測試邏輯）

```python
@pytest.fixture
def logger_cleanup():
    yield
    # 清理日誌處理程序
    logging.shutdown()
```

### 測試資料庫鎖定

SQLite 資料庫可能在測試間被鎖定。

**解決方案**:
```python
@pytest.fixture
def db_connection():
    conn = sqlite3.connect(":memory:")  # 使用記憶體資料庫
    yield conn
    conn.close()
```

---

## 最佳實踐

### ✅ 建議

- 定期執行測試（每次提交前）
- 維持高覆蓋率（> 70%）
- 為新功能編寫測試
- 使用 fixtures 共享設置
- 保持測試快速（單元測試 < 1秒）
- 使用測試標記組織測試
- 定期更新測試文檔

### ❌ 避免

- 測試間的相依性
- 過度使用 mock（優先使用真實物件）
- 測試實作細節（測試行為而非實作）
- 忽略失敗的測試
- 跳過編寫測試

---

## 資源

- [pytest 官方文檔](https://docs.pytest.org/)
- [pytest-cov 文檔](https://pytest-cov.readthedocs.io/)
- [pytest-asyncio 文檔](https://pytest-asyncio.readthedocs.io/)
- [pytest-mock 文檔](https://pytest-mock.readthedocs.io/)

---

**最後更新**: 2025-10-26
**版本**: 1.0.0
**維護者**: charles1018
