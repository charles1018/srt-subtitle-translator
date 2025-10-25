# 🔄 續接指南 - 繼續完成套件重組

> **建立日期**：2025-10-26
> **當前進度**：階段一任務 2 - 70% 完成
> **下一步**：修正所有模組的導入語句

---

## 📋 當前狀態快照

### ✅ 已完成工作（70%）

1. **套件結構建立完成**
   - ✅ 建立 `src/srt_translator/` 主套件
   - ✅ 建立 6 個子套件（core, translation, file_handling, gui, services, utils）
   - ✅ 創建所有 __init__.py 檔案（7 個）
   - ✅ 總計 20 個 Python 檔案，約 11,045 行代碼

2. **模組檔案已重組**
   - ✅ 核心模組：config.py, cache.py, models.py, prompt.py
   - ✅ 翻譯模組：client.py, manager.py
   - ✅ 檔案處理：handler.py
   - ✅ GUI 模組：components.py
   - ✅ 服務層：factory.py
   - ✅ 工具模組：errors.py, logging_config.py, helpers.py

3. **配置檔案已更新**
   - ✅ pyproject.toml 已更新（支持新套件結構）
   - ✅ .gitignore 已更新（排除 .venv, uv.lock 等）

### ⏳ 待完成工作（30%）

**關鍵任務**：修正所有模組的導入語句

- ❌ 約 10 個檔案需要修正導入語句
- ❌ 測試應用程式能否啟動
- ❌ 根據錯誤訊息調整
- ❌ 刪除根目錄的舊檔案（清理）

**預估時間**：4-6 小時

---

## 🚀 新對話開場白（複製並使用）

當您準備好繼續時，請在新的對話視窗中使用以下開場白：

```
我要繼續之前的專案：SRT 字幕翻譯器的套件重組工作。

## 當前狀態
- 專案路徑：D:\dev\project\coding_assistant\charles1018\claude\srt-subtitle-translator
- 當前分支：feature/modularity
- 已完成：階段一任務 2 的 70%（套件結構已建立）
- 待完成：修正所有模組的導入語句（30%）

## 上下文檔案
請先閱讀以下檔案以了解當前進度：
1. CONTINUE.md - 續接指南（本檔案）
2. STATE/stage1_task2_progress.md - 詳細進度報告
3. STATE/context.json - 專案上下文
4. .summary.txt - 任務摘要

## 下一步任務
執行選項 1：繼續完成導入語句修正

具體步驟：
1. 從 src/srt_translator/__main__.py 開始修正導入語句
2. 逐步修正其他模組（約 10 個檔案）
3. 測試應用程式能否啟動
4. 根據錯誤訊息調整
5. 全面測試功能
6. 清理根目錄的舊 .py 檔案

請確認您已閱讀上述檔案，然後我們開始繼續工作。
```

---

## 📚 必讀文檔清單

在開始繼續之前，請確保閱讀以下文檔：

1. **CONTINUE.md**（本檔案）
   - 提供續接指南和開場白模板

2. **STATE/stage1_task2_progress.md**
   - 詳細的進度報告
   - 完整的導入映射表
   - 修正範例
   - 測試計劃

3. **STATE/context.json**
   - 機器可讀的專案上下文
   - 包含當前狀態、已完成和待辦事項

4. **.summary.txt**
   - 人類可讀的任務摘要
   - 快速了解當前進度

5. **CLAUDE.md**
   - Claude Code 執行指南
   - 環境設定和最佳實踐

---

## 🗺️ 導入語句修正指南

### 導入映射表（完整版）

以下是所有需要修正的導入語句映射：

#### 從 config_manager.py → core.config

```python
# 舊導入
from config_manager import ConfigManager, get_config, set_config

# 新導入
from srt_translator.core.config import ConfigManager, get_config, set_config
```

#### 從 cache.py → core.cache

```python
# 舊導入
from cache import CacheManager

# 新導入
from srt_translator.core.cache import CacheManager
```

#### 從 model_manager.py → core.models

```python
# 舊導入
from model_manager import ModelManager, ModelInfo

# 新導入
from srt_translator.core.models import ModelManager, ModelInfo
```

#### 從 prompt.py → core.prompt

```python
# 舊導入
from prompt import PromptManager

# 新導入
from srt_translator.core.prompt import PromptManager
```

#### 從 translation_client.py → translation.client

```python
# 舊導入
from translation_client import TranslationClient, ApiErrorType, ApiMetrics

# 新導入
from srt_translator.translation.client import TranslationClient, ApiErrorType, ApiMetrics
```

#### 從 translation_manager.py → translation.manager

```python
# 舊導入
from translation_manager import TranslationManager, TranslationThread, TranslationStats

# 新導入
from srt_translator.translation.manager import TranslationManager, TranslationThread, TranslationStats
```

#### 從 file_handler.py → file_handling.handler

```python
# 舊導入
from file_handler import FileHandler, SubtitleInfo

# 新導入
from srt_translator.file_handling.handler import FileHandler, SubtitleInfo
```

#### 從 gui_components.py → gui.components

```python
# 舊導入
from gui_components import GUIComponents, PromptEditorWindow

# 新導入
from srt_translator.gui.components import GUIComponents, PromptEditorWindow
```

#### 從 services.py → services.factory

```python
# 舊導入
from services import ServiceFactory, TranslationService, ModelService, CacheService

# 新導入
from srt_translator.services.factory import ServiceFactory, TranslationService, ModelService, CacheService
```

#### 從 utils.py → utils.*

```python
# 舊導入（錯誤類別）
from utils import AppError, ConfigError, ModelError, TranslationError, FileError, NetworkError
from utils import format_exception, safe_execute

# 新導入
from srt_translator.utils.errors import (
    AppError, ConfigError, ModelError, TranslationError, FileError, NetworkError,
    format_exception, safe_execute
)

# 舊導入（工具函數）
from utils import ProgressTracker, LocaleManager, MemoryCache
from utils import clean_text, detect_language, check_internet_connection

# 新導入
from srt_translator.utils.helpers import (
    ProgressTracker, LocaleManager, MemoryCache,
    clean_text, detect_language, check_internet_connection
)

# 舊導入（日誌配置）- 如果有使用
from utils import setup_logger

# 新導入
from srt_translator.utils.logging_config import setup_logger
```

---

## 📝 修正步驟（建議順序）

### 步驟 1：修正 utils 模組

**為什麼先修正 utils？**
因為 utils 被其他所有模組依賴，先修正它可以避免循環導入。

1. **src/srt_translator/utils/errors.py**
   - 檢查是否有外部導入（通常沒有）
   - 確保所有錯誤類別定義正確

2. **src/srt_translator/utils/logging_config.py**
   - 檢查是否有外部導入（通常沒有）
   - 確保日誌配置函數正確

3. **src/srt_translator/utils/helpers.py**
   - 修正從 utils 內部的導入
   - 例如：`from utils import AppError` → `from srt_translator.utils.errors import AppError`

### 步驟 2：修正 core 模組

1. **src/srt_translator/core/config.py**
   - 通常無外部依賴（或僅依賴 utils）
   - 修正任何 utils 的導入

2. **src/srt_translator/core/cache.py**
   - 依賴：config
   - 修正：`from config_manager import` → `from srt_translator.core.config import`

3. **src/srt_translator/core/models.py**
   - 依賴：config, utils
   - 修正所有導入

4. **src/srt_translator/core/prompt.py**
   - 依賴：config
   - 修正所有導入

### 步驟 3：修正 translation 模組

1. **src/srt_translator/translation/client.py**
   - 依賴：core (cache, prompt, config), utils
   - 修正所有導入

2. **src/srt_translator/translation/manager.py**
   - 依賴：translation.client, core, utils
   - 修正所有導入

### 步驟 4：修正 file_handling 模組

1. **src/srt_translator/file_handling/handler.py**
   - 依賴：core.config, utils
   - 修正所有導入

### 步驟 5：修正 services 模組

1. **src/srt_translator/services/factory.py**
   - 依賴：所有其他模組（translation, core, file_handling, utils）
   - 這是最複雜的，最後修正
   - 修正所有導入

### 步驟 6：修正 gui 模組

1. **src/srt_translator/gui/components.py**
   - 依賴：file_handling, services, core.prompt, utils
   - 修正所有導入

### 步驟 7：修正主程式

1. **src/srt_translator/__main__.py**
   - 依賴：core.config, services, utils, gui
   - 修正所有導入
   - 確保 `main()` 函數存在

---

## 🧪 測試計劃

### 階段 1：導入測試

修正每個模組後，立即測試能否導入：

```bash
# 測試 utils
uv run python -c "from srt_translator.utils import errors"
uv run python -c "from srt_translator.utils import logging_config"
uv run python -c "from srt_translator.utils import helpers"

# 測試 core
uv run python -c "from srt_translator.core import config"
uv run python -c "from srt_translator.core import cache"
uv run python -c "from srt_translator.core import models"
uv run python -c "from srt_translator.core import prompt"

# 測試 translation
uv run python -c "from srt_translator.translation import client"
uv run python -c "from srt_translator.translation import manager"

# 測試 file_handling
uv run python -c "from srt_translator.file_handling import handler"

# 測試 services
uv run python -c "from srt_translator.services import factory"

# 測試 gui
uv run python -c "from srt_translator.gui import components"

# 測試主模組
uv run python -c "from srt_translator import __main__"
```

### 階段 2：應用程式啟動測試

```bash
# 測試能否啟動
uv run python -m srt_translator

# 如果出現錯誤，根據錯誤訊息繼續修正
```

### 階段 3：功能測試

1. GUI 能否正常顯示
2. 檔案選擇功能
3. 配置載入
4. （不需要測試翻譯功能，只要確保啟動即可）

---

## 🔍 常見問題與解決方案

### 問題 1：循環導入錯誤

**症狀**：
```
ImportError: cannot import name 'XXX' from partially initialized module
```

**解決方案**：
- 檢查是否有 A 導入 B，B 又導入 A 的情況
- 將共用的類別移到獨立檔案
- 使用延遲導入（在函數內部導入）

### 問題 2：找不到模組

**症狀**：
```
ModuleNotFoundError: No module named 'srt_translator'
```

**解決方案**：
```bash
# 重新安裝套件
uv sync --all-extras --reinstall-package srt-subtitle-translator
```

### 問題 3：導入路徑錯誤

**症狀**：
```
ImportError: cannot import name 'XXX' from 'srt_translator.xxx'
```

**解決方案**：
- 檢查類別或函數名稱是否正確
- 檢查檔案路徑是否正確
- 檢查 __init__.py 是否存在

---

## 📦 完成後的清理工作

當所有導入修正完成並測試通過後：

### 1. 刪除根目錄的舊檔案

```bash
# 建議先備份
mkdir -p backup_old_files
cp *.py backup_old_files/

# 確認應用程式正常運作後，刪除舊檔案
rm config_manager.py cache.py model_manager.py prompt.py \
   translation_client.py translation_manager.py \
   file_handler.py gui_components.py services.py \
   utils.py srt-translator.py
```

### 2. 更新 .gitignore

確保以下內容在 .gitignore 中：
```
# 備份檔案
backup_old_files/
```

### 3. 提交最終版本

```bash
git add .
git commit -m "feat: 完成套件重組，修正所有導入語句

- 將所有模組重組為 src/srt_translator/ 套件結構
- 修正所有模組的導入語句
- 測試應用程式正常啟動
- 刪除根目錄的舊檔案

階段一任務 2 完成 ✅

🤖 Generated with Claude Code
Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 📊 進度檢查清單

在繼續之前，請確認：

- [ ] 已閱讀 CONTINUE.md
- [ ] 已閱讀 STATE/stage1_task2_progress.md
- [ ] 已查看 STATE/context.json
- [ ] 已查看 .summary.txt
- [ ] 理解當前 70% 的進度
- [ ] 理解剩餘 30% 的工作
- [ ] 準備好 4-6 小時的工作時間

---

## 🎯 成功標準

任務 2 完成的標準：

1. ✅ 所有模組的導入語句已修正
2. ✅ `uv run python -m srt_translator` 能正常啟動應用程式
3. ✅ GUI 能正常顯示
4. ✅ 沒有導入錯誤
5. ✅ 根目錄的舊 .py 檔案已刪除
6. ✅ 已提交到 Git

---

## 📞 需要幫助？

如果在繼續過程中遇到問題：

1. **檢查錯誤訊息**：Python 的錯誤訊息通常很明確
2. **查看進度報告**：STATE/stage1_task2_progress.md 有詳細的修正範例
3. **逐步測試**：修正一個模組就測試一次導入
4. **使用 Git**：隨時可以回退到當前的提交

---

## 🚀 準備好了嗎？

當您準備好繼續時：

1. 複製上面的"新對話開場白"
2. 在新的 Claude Code 對話視窗中貼上
3. 開始繼續完成剩餘的 30% 工作

**祝您順利完成套件重組！** 🎉

---

**建立日期**：2025-10-26
**文檔版本**：1.0
**預計完成時間**：4-6 小時
