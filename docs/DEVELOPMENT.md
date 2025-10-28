# 開發者文檔

> SRT Subtitle Translator 開發環境設定與開發指南

## 目錄

- [環境需求](#環境需求)
- [開發環境設定](#開發環境設定)
- [專案結構](#專案結構)
- [開發工作流](#開發工作流)
- [測試](#測試)
- [程式碼品質](#程式碼品質)
- [建構與發布](#建構與發布)
- [除錯技巧](#除錯技巧)
- [常見問題](#常見問題)

---

## 環境需求

### 必要條件

- **Python**: 3.8 或更高版本
- **uv**: 推薦的套件管理器
- **Git**: 版本控制
- **Make**: 任務自動化（可選）

### 推薦工具

- **IDE**: VS Code 或 PyCharm
- **VS Code 擴充套件**:
  - Python (Microsoft)
  - Pylance
  - Python Test Explorer
  - Ruff
  - GitLens

---

## 開發環境設定

### 快速開始

```bash
# 1. 克隆儲存庫
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator

# 2. 安裝 uv（如果尚未安裝）
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. 建立虛擬環境並安裝依賴
uv sync --all-extras --dev

# 4. 驗證安裝
uv run pytest --version
uv run ruff --version

# 5. 執行測試確認環境正常
uv run pytest -v
```

### 替代方案：使用 pip

```bash
# 建立虛擬環境
python -m venv .venv

# 啟動虛擬環境
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

# 安裝依賴
pip install -e ".[dev]"

# 執行測試
pytest -v
```

### 設定 API 金鑰（測試用）

```bash
# OpenAI（如需測試 OpenAI 整合）
echo "sk-test-key" > openapi_api_key.txt

# Anthropic（如需測試 Anthropic 整合）
echo "sk-ant-test-key" > anthropic_api_key.txt
```

### VS Code 設定

建立 `.vscode/settings.json`：

```json
{
  "python.defaultInterpreterPath": "${workspaceFolder}/.venv/bin/python",
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": [
    "tests"
  ],
  "python.linting.enabled": false,
  "ruff.enable": true,
  "ruff.organizeImports": true,
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.organizeImports": true,
    "source.fixAll": true
  },
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.formatOnSave": true,
    "editor.codeActionsOnSave": {
      "source.fixAll": true,
      "source.organizeImports": true
    }
  }
}
```

---

## 專案結構

```
srt-subtitle-translator/
├── src/srt_translator/        # 主要原始碼
│   ├── core/                  # 核心模組
│   │   ├── config.py          # ConfigManager
│   │   ├── cache.py           # CacheManager
│   │   ├── models.py          # ModelManager
│   │   └── prompt.py          # PromptManager
│   ├── translation/           # 翻譯模組
│   │   ├── client.py          # TranslationClient
│   │   └── manager.py         # TranslationManager
│   ├── file_handling/         # 檔案處理
│   │   └── handler.py         # FileHandler
│   ├── gui/                   # GUI 組件
│   │   └── components.py      # GUIComponents
│   ├── services/              # 服務工廠
│   │   └── factory.py         # ServiceFactory
│   ├── utils/                 # 工具模組
│   │   ├── errors.py          # 錯誤定義
│   │   ├── helpers.py         # 輔助函數
│   │   └── logging_config.py # 日誌配置
│   └── __main__.py            # 主程式入口
├── tests/                     # 測試
│   ├── unit/                  # 單元測試
│   ├── integration/           # 整合測試
│   └── e2e/                   # E2E 測試
├── docs/                      # 文檔
│   ├── USER_GUIDE.md          # 使用者指南
│   ├── API.md                 # API 文檔
│   └── DEVELOPMENT.md         # 本文檔
├── config/                    # 配置檔案（執行時生成）
├── data/                      # 資料目錄（執行時生成）
├── logs/                      # 日誌目錄（執行時生成）
├── pyproject.toml             # 專案配置
├── README.md                  # 專案說明
├── CHANGELOG.md               # 變更日誌
├── CONTRIBUTING.md            # 貢獻指南
└── LICENSE                    # 授權條款
```

### 核心模組說明

| 模組 | 職責 | 主要類別 |
|------|------|---------|
| **core/config.py** | 配置管理 | ConfigManager |
| **core/cache.py** | 翻譯快取 | CacheManager |
| **core/models.py** | 模型管理 | ModelManager |
| **core/prompt.py** | 提示詞管理 | PromptManager |
| **translation/client.py** | API 客戶端 | TranslationClient |
| **translation/manager.py** | 翻譯流程 | TranslationManager |
| **file_handling/handler.py** | 檔案處理 | FileHandler |
| **services/factory.py** | 服務工廠 | ServiceFactory |

---

## 開發工作流

### 1. 建立功能分支

```bash
# 確保 master 是最新的
git checkout master
git pull origin master

# 建立新分支
git checkout -b feature/your-feature-name
```

### 2. 開發循環

```bash
# 編寫程式碼
# ...

# 執行測試
uv run pytest -v

# 檢查程式碼品質
uv run ruff check

# 自動修復問題
uv run ruff check --fix

# 提交變更
git add .
git commit -m "feat: your feature description"
```

### 3. 提交前檢查

```bash
# 執行完整測試套件
uv run pytest -v

# 檢查覆蓋率
uv run pytest --cov=src/srt_translator --cov-report=html

# 檢查型別（可選）
uv run mypy src/srt_translator

# 檢查程式碼風格
uv run ruff check
```

### 4. 推送與 PR

```bash
# 推送到遠端
git push origin feature/your-feature-name

# 在 GitHub 上建立 Pull Request
```

---

## 測試

### 測試架構

專案包含三種層級的測試：

1. **單元測試** (`tests/unit/`)：測試單一函數或類別
2. **整合測試** (`tests/integration/`)：測試模組間的整合
3. **E2E 測試** (`tests/e2e/`)：測試完整使用者流程

### 執行測試

```bash
# 執行所有測試
uv run pytest -v

# 執行特定測試類型
uv run pytest tests/unit -v           # 只執行單元測試
uv run pytest tests/integration -v    # 只執行整合測試
uv run pytest tests/e2e -v            # 只執行 E2E 測試

# 執行特定檔案
uv run pytest tests/unit/core/test_config.py -v

# 執行特定測試
uv run pytest tests/unit/core/test_config.py::test_get_config -v

# 平行執行（需要 pytest-xdist）
uv run pytest -n auto

# 詳細輸出
uv run pytest -vv

# 顯示 print 輸出
uv run pytest -s
```

### 測試覆蓋率

```bash
# 生成覆蓋率報告
uv run pytest --cov=src/srt_translator --cov-report=term-missing

# 生成 HTML 報告
uv run pytest --cov=src/srt_translator --cov-report=html

# 開啟 HTML 報告
# Windows
start htmlcov/index.html
# macOS
open htmlcov/index.html
# Linux
xdg-open htmlcov/index.html
```

### 撰寫測試

#### 單元測試範例

```python
import pytest
from srt_translator.core.config import ConfigManager

def test_config_manager_singleton():
    """測試 ConfigManager 單例模式"""
    config1 = ConfigManager.get_instance("app")
    config2 = ConfigManager.get_instance("app")

    assert config1 is config2

def test_get_config_value():
    """測試獲取配置值"""
    config = ConfigManager.get_instance("app")

    value = config.get_value("version", "1.0.0")

    assert value is not None
    assert isinstance(value, str)
```

#### 非同步測試範例

```python
import pytest
from srt_translator.translation.client import TranslationClient

@pytest.mark.asyncio
async def test_translate_text(mock_openai_client):
    """測試文本翻譯"""
    client = TranslationClient("openai", "gpt-3.5-turbo", "test-key")

    result = await client.translate(
        "Hello",
        "English",
        "Chinese"
    )

    assert result is not None
    assert isinstance(result, str)
```

#### 使用 Fixtures

```python
import pytest
from srt_translator.core.cache import CacheManager

@pytest.fixture
def cache_manager(tmp_path):
    """快取管理器 fixture"""
    db_path = tmp_path / "test_cache.db"
    manager = CacheManager(str(db_path))
    yield manager
    # 清理
    db_path.unlink(missing_ok=True)

def test_cache_save_and_get(cache_manager):
    """測試快取儲存與讀取"""
    # 儲存
    cache_manager.save_translation(
        "Hello",
        "你好",
        [],
        "test-model"
    )

    # 讀取
    cached = cache_manager.get_cached_translation(
        "Hello",
        [],
        "test-model"
    )

    assert cached == "你好"
```

---

## 程式碼品質

### Ruff（Linter & Formatter）

```bash
# 檢查程式碼
uv run ruff check

# 自動修復問題
uv run ruff check --fix

# 格式化程式碼
uv run ruff format

# 檢查特定檔案
uv run ruff check src/srt_translator/core/config.py

# 檢查特定目錄
uv run ruff check src/srt_translator/core/
```

### Mypy（型別檢查）

```bash
# 型別檢查
uv run mypy src/srt_translator

# 嚴格模式
uv run mypy --strict src/srt_translator

# 檢查特定檔案
uv run mypy src/srt_translator/core/config.py
```

### Pre-commit Hooks（可選）

安裝 pre-commit：

```bash
pip install pre-commit
pre-commit install
```

建立 `.pre-commit-config.yaml`：

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
```

---

## 建構與發布

### 本地建構

```bash
# 使用 uv 建構
uv build

# 檢查生成的檔案
ls dist/
# srt_subtitle_translator-1.0.0-py3-none-any.whl
# srt_subtitle_translator-1.0.0.tar.gz
```

### 本地安裝測試

```bash
# 安裝建構的套件
pip install dist/srt_subtitle_translator-1.0.0-py3-none-any.whl

# 測試執行
srt-translator

# 解除安裝
pip uninstall srt-subtitle-translator
```

### 發布到 PyPI

```bash
# 安裝 twine
pip install twine

# 上傳到 Test PyPI（測試）
twine upload --repository testpypi dist/*

# 上傳到 PyPI（正式）
twine upload dist/*
```

---

## 除錯技巧

### 日誌除錯

```python
import logging

# 設定日誌級別
logging.basicConfig(level=logging.DEBUG)

# 在程式碼中加入日誌
logger = logging.getLogger(__name__)
logger.debug(f"變數值: {variable}")
logger.info("進入函數")
logger.error(f"發生錯誤: {e}")
```

### 使用 pdb 除錯

```python
# 在想要中斷的地方加入
import pdb; pdb.set_trace()

# 或使用 Python 3.7+ 的 breakpoint()
breakpoint()
```

### VS Code 除錯配置

建立 `.vscode/launch.json`：

```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Current File",
      "type": "python",
      "request": "launch",
      "program": "${file}",
      "console": "integratedTerminal"
    },
    {
      "name": "Python: Main",
      "type": "python",
      "request": "launch",
      "module": "srt_translator",
      "console": "integratedTerminal"
    },
    {
      "name": "Python: Pytest",
      "type": "python",
      "request": "launch",
      "module": "pytest",
      "args": ["-v", "${file}"],
      "console": "integratedTerminal"
    }
  ]
}
```

### 檢查快取狀態

```bash
# 使用 SQLite CLI 檢查快取資料庫
sqlite3 data/translation_cache.db

# 檢視所有表
.tables

# 檢視快取內容
SELECT * FROM translations LIMIT 10;

# 統計快取數量
SELECT COUNT(*) FROM translations;

# 離開
.quit
```

---

## 常見問題

### Q1：虛擬環境無法啟動

**A**：確認 Python 版本 >= 3.8，並檢查虛擬環境路徑。

```bash
# 檢查 Python 版本
python --version

# 刪除並重新建立虛擬環境
rm -rf .venv
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

### Q2：測試失敗

**A**：常見原因：

```bash
# 1. 依賴未安裝
uv sync --all-extras --dev

# 2. 快取問題
pytest --cache-clear

# 3. 檢查特定測試
pytest tests/unit/core/test_config.py -vv

# 4. 查看詳細錯誤
pytest -vv -s
```

### Q3：Import 錯誤

**A**：確認套件已安裝為可編輯模式：

```bash
pip install -e .
```

### Q4：Ruff 檢查失敗

**A**：自動修復大部分問題：

```bash
uv run ruff check --fix
uv run ruff format
```

### Q5：記憶體使用過高

**A**：大型檔案處理時：

```python
# 調整批次大小
BATCH_SIZE = 50  # 降低批次大小

# 或降低並發數
concurrent_limit = 3  # 降低並發數
```

---

## 效能分析

### 使用 cProfile

```bash
python -m cProfile -o profile.stats -m srt_translator

# 分析結果
python -m pstats profile.stats
# 進入互動模式後：
# sort cumulative
# stats 10
```

### 使用 line_profiler

```bash
# 安裝
pip install line_profiler

# 在函數上加裝飾器
@profile
def slow_function():
    pass

# 執行
kernprof -l -v your_script.py
```

---

## 持續整合（CI）

### GitHub Actions 範例

建立 `.github/workflows/tests.yml`：

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ${{ matrix.os }}
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ['3.8', '3.9', '3.10', '3.11', '3.12']

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install uv
        run: pip install uv

      - name: Install dependencies
        run: uv sync --all-extras --dev

      - name: Run tests
        run: uv run pytest -v

      - name: Check code quality
        run: uv run ruff check
```

---

## 資源連結

- [Python 官方文檔](https://docs.python.org/zh-tw/3/)
- [Pytest 文檔](https://docs.pytest.org/)
- [Ruff 文檔](https://docs.astral.sh/ruff/)
- [uv 文檔](https://github.com/astral-sh/uv)
- [專案 GitHub](https://github.com/charles1018/srt-subtitle-translator)

---

**最後更新**：2025-01-28
**版本**：1.0.0
