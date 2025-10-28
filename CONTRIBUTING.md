# 貢獻指南

> 感謝您對 SRT Subtitle Translator 專案的興趣！

## 目錄

- [行為準則](#行為準則)
- [我可以如何貢獻](#我可以如何貢獻)
- [開發環境設定](#開發環境設定)
- [提交變更](#提交變更)
- [編碼規範](#編碼規範)
- [測試要求](#測試要求)
- [文檔要求](#文檔要求)
- [提交訊息規範](#提交訊息規範)
- [Pull Request 流程](#pull-request-流程)
- [問題回報](#問題回報)

---

## 行為準則

### 我們的承諾

為了營造開放友善的環境，我們承諾讓每個人都能自由參與本專案，無論其經驗水平、性別、性別認同與表達、性取向、殘疾、外貌、身材、種族、年齡、宗教或國籍。

### 我們的標準

有助於創造正面環境的行為包括：

- 使用友善和包容的語言
- 尊重不同的觀點和經驗
- 優雅地接受建設性批評
- 關注對社群最有利的事情
- 對其他社群成員表現同理心

不可接受的行為包括：

- 使用性暗示的語言或圖像
- 人身攻擊或侮辱性評論
- 公開或私下騷擾
- 未經許可發布他人的私人資訊
- 其他在專業環境中被視為不適當的行為

---

## 我可以如何貢獻

### 回報 Bug

在回報 Bug 之前：

1. 檢查 [FAQ](docs/USER_GUIDE.md#faq)
2. 搜尋 [Issues](https://github.com/charles1018/srt-subtitle-translator/issues)，確認問題尚未回報
3. 嘗試在最新版本中重現問題

**優秀的 Bug 回報應包含**：

- 清晰的標題和描述
- 重現步驟
- 預期行為 vs 實際行為
- 環境資訊（OS、Python 版本等）
- 錯誤訊息和日誌（如適用）
- 螢幕截圖（如適用）

**範例**：

```markdown
### Bug 描述
使用 Ollama 模式時，翻譯進度卡在 50%

### 重現步驟
1. 選擇 Ollama 模式
2. 選擇 llama2 模型
3. 開始翻譯包含 100 條字幕的檔案
4. 進度在 50% 處停止

### 預期行為
翻譯應該持續進行直到完成

### 實際行為
進度卡在 50%，沒有錯誤訊息

### 環境
- OS: Windows 11
- Python: 3.11.0
- 專案版本: 1.0.0
- Ollama 版本: 0.1.5

### 日誌
[附上相關日誌]
```

### 建議新功能

**優秀的功能建議應包含**：

- 功能的動機和使用場景
- 詳細的功能描述
- 可能的實作方式（可選）
- 相關的螢幕截圖或模擬圖（可選）

**範例**：

```markdown
### 功能描述
支援翻譯記憶導出功能

### 動機
使用者可能希望將翻譯記憶導出為 TMX 格式，以便在其他翻譯工具中使用

### 建議實作
1. 在 GUI 新增「導出翻譯記憶」按鈕
2. 從 SQLite 讀取快取
3. 轉換為 TMX 格式
4. 允許使用者選擇儲存位置

### 相關資源
- TMX 規範：https://www.gala-global.org/tmx-14b
```

### 改進文檔

文檔改進永遠都很歡迎！這包括：

- 修正錯別字或不清楚的說明
- 新增範例
- 翻譯成其他語言
- 改進 API 文檔

---

## 開發環境設定

### 前置需求

- Python 3.8+
- uv 或 pip
- Git

### 設定步驟

```bash
# 1. Fork 儲存庫
# 在 GitHub 上點擊 Fork 按鈕

# 2. 克隆您的 fork
git clone https://github.com/YOUR_USERNAME/srt-subtitle-translator.git
cd srt-subtitle-translator

# 3. 新增上游遠端
git remote add upstream https://github.com/charles1018/srt-subtitle-translator.git

# 4. 安裝依賴
uv sync --all-extras --dev

# 5. 執行測試確認環境正常
uv run pytest -v
```

### 開發工具

```bash
# 安裝開發依賴（如果使用 pip）
pip install -e ".[dev]"

# 程式碼檢查
uv run ruff check

# 自動修復
uv run ruff check --fix

# 執行測試
uv run pytest -v

# 生成覆蓋率報告
uv run pytest --cov=src/srt_translator --cov-report=html
```

---

## 提交變更

### 建立分支

```bash
# 確保您的 master 分支是最新的
git checkout master
git pull upstream master

# 建立功能分支
git checkout -b feature/your-feature-name

# 或修復分支
git checkout -b fix/your-bug-fix
```

### 分支命名規範

- `feature/功能名稱` - 新功能
- `fix/問題描述` - Bug 修復
- `docs/文檔主題` - 文檔更新
- `refactor/重構範圍` - 程式碼重構
- `test/測試範圍` - 測試改進
- `chore/雜項描述` - 雜項任務

**範例**：
- `feature/export-translation-memory`
- `fix/ollama-connection-timeout`
- `docs/api-examples`
- `refactor/config-manager`

---

## 編碼規範

### Python 風格指南

本專案遵循 [PEP 8](https://peps.python.org/pep-0008/) 風格指南，並使用 Ruff 進行檢查。

#### 重要規則

1. **縮排**：使用 4 個空格
2. **行長度**：最多 120 字符
3. **命名**：
   - 類別：`PascalCase`
   - 函數/變數：`snake_case`
   - 常數：`UPPER_CASE`
4. **導入順序**：
   - 標準庫
   - 第三方套件
   - 本地模組

**範例**：

```python
# ✅ 正確
import os
import sys
from typing import List, Optional

import pysrt
from openai import OpenAI

from srt_translator.core.config import ConfigManager
from srt_translator.utils import safe_execute

class TranslationManager:
    """翻譯管理器類別"""

    def __init__(self, config: ConfigManager) -> None:
        self.config = config
        self._client: Optional[OpenAI] = None

    def translate_text(self, text: str, context: List[str]) -> str:
        """翻譯文本"""
        pass

# ❌ 錯誤
class translationManager:  # 類別名稱應為 PascalCase
    def TranslateText(self, Text, Context):  # 函數和參數應為 snake_case
        pass
```

### 型別提示

使用型別提示提高程式碼可讀性：

```python
from typing import List, Optional, Dict, Any

def get_translation(
    text: str,
    context: List[str],
    model: str = "gpt-3.5-turbo"
) -> Optional[str]:
    """獲取翻譯結果

    參數:
        text: 要翻譯的文本
        context: 上下文列表
        model: 使用的模型

    回傳:
        翻譯結果，失敗則回傳 None
    """
    pass
```

### 文檔字串

使用 Google 風格的文檔字串：

```python
def translate_batch(
    texts: List[str],
    source_lang: str,
    target_lang: str
) -> List[str]:
    """批量翻譯文本

    Args:
        texts: 要翻譯的文本列表
        source_lang: 源語言
        target_lang: 目標語言

    Returns:
        翻譯結果列表

    Raises:
        TranslationError: 翻譯失敗時拋出

    Example:
        >>> results = translate_batch(
        ...     ["Hello", "World"],
        ...     "English",
        ...     "Chinese"
        ... )
        >>> print(results)
        ['你好', '世界']
    """
    pass
```

---

## 測試要求

### 測試覆蓋率

- 新功能必須包含測試
- 目標覆蓋率：80%+
- 所有測試必須通過

### 執行測試

```bash
# 執行所有測試
uv run pytest -v

# 執行特定測試檔案
uv run pytest tests/unit/core/test_config.py -v

# 執行特定測試
uv run pytest tests/unit/core/test_config.py::test_get_config -v

# 生成覆蓋率報告
uv run pytest --cov=src/srt_translator --cov-report=html
```

### 測試類型

#### 單元測試

測試單一函數或方法：

```python
import pytest
from srt_translator.core.config import ConfigManager

def test_get_config_value():
    """測試獲取配置值"""
    config = ConfigManager.get_instance("app")
    version = config.get_value("version")

    assert version is not None
    assert isinstance(version, str)
```

#### 整合測試

測試多個組件的整合：

```python
import pytest
from srt_translator.services.factory import ServiceFactory

@pytest.mark.asyncio
async def test_translation_integration():
    """測試翻譯整合流程"""
    translation_service = ServiceFactory.get_translation_service()
    cache_service = ServiceFactory.get_cache_service()

    # 測試翻譯和快取整合
    result = await translation_service.translate_text(
        "Hello",
        [],
        "openai",
        "gpt-3.5-turbo"
    )

    # 驗證結果被快取
    cached = cache_service.get_cached_translation(
        "Hello",
        [],
        "gpt-3.5-turbo"
    )

    assert cached == result
```

#### E2E 測試

測試完整使用者流程：

```python
import pytest
from pathlib import Path

@pytest.mark.asyncio
async def test_file_translation_e2e(tmp_path):
    """測試完整檔案翻譯流程"""
    input_file = tmp_path / "input.srt"
    output_file = tmp_path / "output.srt"

    # 建立測試檔案
    input_file.write_text("1\n00:00:01,000 --> 00:00:03,000\nHello")

    # 執行翻譯
    success = await translate_file(
        str(input_file),
        str(output_file),
        "English",
        "Chinese"
    )

    assert success
    assert output_file.exists()
```

---

## 文檔要求

### 必要文檔

1. **程式碼註解**：複雜邏輯必須註解
2. **文檔字串**：所有公開 API 必須有文檔字串
3. **README 更新**：新功能需更新 README
4. **CHANGELOG 更新**：所有變更需記錄在 CHANGELOG

### 文檔風格

- 使用繁體中文（台灣）
- 程式碼範例必須可執行
- 提供清晰的範例和說明

---

## 提交訊息規範

### 格式

```
<type>(<scope>): <subject>

<body>

<footer>
```

### Type

- `feat`: 新功能
- `fix`: Bug 修復
- `docs`: 文檔變更
- `style`: 格式調整（不影響程式碼運行）
- `refactor`: 重構
- `test`: 測試相關
- `chore`: 構建過程或輔助工具變動

### 範例

```
feat(translation): 新增批量翻譯功能

實作批量翻譯 API，支援並發處理多個文本。
包含快取整合和進度追蹤功能。

Closes #123
```

```
fix(cache): 修復快取過期時間計算錯誤

快取過期時間計算錯誤導致快取過早失效。
修正時間戳計算邏輯。

Fixes #456
```

---

## Pull Request 流程

### 提交前檢查清單

- [ ] 程式碼符合編碼規範
- [ ] 所有測試通過
- [ ] 新增了必要的測試
- [ ] 更新了相關文檔
- [ ] 提交訊息清晰且符合規範
- [ ] 分支基於最新的 master

### 建立 Pull Request

1. **推送分支到您的 fork**

   ```bash
   git push origin feature/your-feature-name
   ```

2. **開啟 Pull Request**
   - 前往 GitHub 上您的 fork
   - 點擊 "New Pull Request"
   - 選擇您的分支
   - 填寫 PR 模板

3. **PR 描述應包含**：
   - 變更摘要
   - 相關 Issue 編號
   - 測試說明
   - 截圖（如適用）
   - 檢查清單

### PR 範例

```markdown
## 變更摘要
新增翻譯記憶導出功能，支援導出為 TMX 格式

## 相關 Issue
Closes #123

## 變更類型
- [ ] Bug 修復
- [x] 新功能
- [ ] 文檔更新
- [ ] 重構

## 測試
- [x] 單元測試已新增
- [x] 整合測試已新增
- [x] 所有測試通過

## 檢查清單
- [x] 程式碼符合專案規範
- [x] 已更新相關文檔
- [x] 已更新 CHANGELOG.md
- [x] 提交訊息符合規範
```

### Code Review

- 保持開放態度接受建議
- 及時回應審查意見
- 根據反饋進行調整
- 感謝審查者的時間

---

## 問題回報

### Security Issues

如果發現安全漏洞，請**不要**公開提交 Issue。

請直接發送 email 至：chmadux8@gmail.com

---

## 社群

- **GitHub Discussions**: [討論區](https://github.com/charles1018/srt-subtitle-translator/discussions)
- **Issue Tracker**: [問題追蹤](https://github.com/charles1018/srt-subtitle-translator/issues)

---

## 授權

提交貢獻即表示您同意您的程式碼將以 MIT 授權發布。

---

## 感謝

感謝所有貢獻者！您的付出讓這個專案變得更好。

---

**最後更新**：2025-01-28
