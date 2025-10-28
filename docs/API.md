# API 文檔

> SRT Subtitle Translator 開發者 API 參考

## 目錄

- [概述](#概述)
- [核心模組 (core)](#核心模組-core)
  - [ConfigManager](#configmanager)
  - [CacheManager](#cachemanager)
  - [ModelManager](#modelmanager)
  - [PromptManager](#promptmanager)
- [翻譯模組 (translation)](#翻譯模組-translation)
  - [TranslationClient](#translationclient)
  - [TranslationManager](#translationmanager)
- [檔案處理模組 (file_handling)](#檔案處理模組-file_handling)
  - [FileHandler](#filehandler)
- [服務工廠 (services)](#服務工廠-services)
  - [ServiceFactory](#servicefactory)
- [工具模組 (utils)](#工具模組-utils)
  - [錯誤類別](#錯誤類別)
  - [輔助函數](#輔助函數)
- [使用範例](#使用範例)
- [最佳實踐](#最佳實踐)

---

## 概述

本 API 文檔提供 SRT Subtitle Translator 各模組的詳細說明，適合以下場景：

- 🔧 整合到自己的專案
- 📦 擴展功能
- 🐛 問題除錯
- 🧪 單元測試

### 架構概覽

```
src/srt_translator/
├── core/              # 核心模組
│   ├── config.py      # ConfigManager
│   ├── cache.py       # CacheManager
│   ├── models.py      # ModelManager
│   └── prompt.py      # PromptManager
├── translation/       # 翻譯模組
│   ├── client.py      # TranslationClient
│   └── manager.py     # TranslationManager
├── file_handling/     # 檔案處理
│   └── handler.py     # FileHandler
├── services/          # 服務工廠
│   └── factory.py     # ServiceFactory
└── utils/             # 工具模組
    ├── errors.py
    ├── helpers.py
    └── logging_config.py
```

---

## 核心模組 (core)

### ConfigManager

配置管理器，統一管理應用程式的各種配置。

#### 類別簽名

```python
class ConfigManager:
    """配置管理器，統一管理系統的各種配置"""
```

#### 建立實例

```python
from srt_translator.core.config import ConfigManager

# 獲取單例實例
config_manager = ConfigManager.get_instance("user")
```

#### 主要方法

##### `get_instance(config_type: str) -> ConfigManager`

獲取配置管理器實例（單例模式）。

**參數**：
- `config_type` (str): 配置類型，可選值：
  - `"app"`: 應用程式配置
  - `"user"`: 使用者設定
  - `"model"`: 模型配置
  - `"prompt"`: 提示詞配置
  - `"file"`: 檔案處理配置
  - `"cache"`: 快取配置

**回傳**：`ConfigManager` - 配置管理器實例

**範例**：
```python
app_config = ConfigManager.get_instance("app")
user_config = ConfigManager.get_instance("user")
```

##### `get_config() -> Dict[str, Any]`

獲取完整配置。

**回傳**：`Dict[str, Any]` - 完整配置字典

**範例**：
```python
config = config_manager.get_config()
print(config["version"])
```

##### `get_value(key: str, default: Any = None) -> Any`

獲取單一配置值。

**參數**：
- `key` (str): 配置鍵
- `default` (Any, 可選): 預設值

**回傳**：`Any` - 配置值

**範例**：
```python
version = config_manager.get_value("version", "1.0.0")
debug_mode = config_manager.get_value("debug_mode", False)
```

##### `set_value(key: str, value: Any, auto_save: bool = True) -> None`

設定配置值。

**參數**：
- `key` (str): 配置鍵
- `value` (Any): 配置值
- `auto_save` (bool): 是否自動儲存，預設 True

**範例**：
```python
config_manager.set_value("theme", "dark")
config_manager.set_value("debug_mode", True, auto_save=False)
```

##### `save_config() -> bool`

儲存配置到檔案。

**回傳**：`bool` - 是否成功

**範例**：
```python
success = config_manager.save_config()
```

##### `reload_config() -> bool`

從檔案重新載入配置。

**回傳**：`bool` - 是否成功

**範例**：
```python
config_manager.reload_config()
```

#### 快捷函數

```python
from srt_translator.core.config import get_config, set_config

# 快速獲取配置
value = get_config("user", "theme", "default")

# 快速設定配置
set_config("user", "theme", "dark")
```

---

### CacheManager

翻譯快取管理器，使用 SQLite 儲存翻譯記憶。

#### 類別簽名

```python
class CacheManager:
    """管理翻譯緩存的 SQLite 數據庫"""
```

#### 建立實例

```python
from srt_translator.core.cache import CacheManager

cache_manager = CacheManager(db_path="data/translation_cache.db")
```

#### 主要方法

##### `__init__(db_path: str = "data/translation_cache.db")`

初始化快取管理器。

**參數**：
- `db_path` (str): SQLite 資料庫路徑

##### `get_cached_translation(text: str, context: List[str], model_name: str) -> Optional[str]`

從快取獲取翻譯。

**參數**：
- `text` (str): 要翻譯的文本
- `context` (List[str]): 上下文列表
- `model_name` (str): 模型名稱

**回傳**：`Optional[str]` - 快取的翻譯結果，未命中則回傳 None

**範例**：
```python
translation = cache_manager.get_cached_translation(
    "Hello, world!",
    ["Previous subtitle"],
    "gpt-3.5-turbo"
)
```

##### `save_translation(text: str, translation: str, context: List[str], model_name: str) -> bool`

儲存翻譯到快取。

**參數**：
- `text` (str): 原始文本
- `translation` (str): 翻譯結果
- `context` (List[str]): 上下文列表
- `model_name` (str): 模型名稱

**回傳**：`bool` - 是否成功

**範例**：
```python
cache_manager.save_translation(
    "Hello, world!",
    "你好，世界！",
    ["Previous subtitle"],
    "gpt-3.5-turbo"
)
```

##### `get_cache_stats() -> Dict[str, Any]`

獲取快取統計資訊。

**回傳**：`Dict[str, Any]` - 快取統計

**範例**：
```python
stats = cache_manager.get_cache_stats()
print(f"總快取數: {stats['total_entries']}")
print(f"快取大小: {stats['size_mb']} MB")
```

##### `clear_cache(older_than_days: Optional[int] = None) -> int`

清理快取。

**參數**：
- `older_than_days` (Optional[int]): 清理超過指定天數的快取，None 則清除全部

**回傳**：`int` - 刪除的條目數

**範例**：
```python
# 清除所有快取
deleted = cache_manager.clear_cache()

# 清除 30 天以前的快取
deleted = cache_manager.clear_cache(older_than_days=30)
```

---

### ModelManager

AI 模型管理器，管理模型清單和推薦。

#### 類別簽名

```python
class ModelManager:
    """管理 AI 模型清單和選擇"""
```

#### 建立實例

```python
from srt_translator.core.models import ModelManager

model_manager = ModelManager()
```

#### 主要方法

##### `get_available_models(llm_type: str) -> List[str]`

獲取可用模型列表。

**參數**：
- `llm_type` (str): LLM 類型 ("ollama", "openai", "anthropic")

**回傳**：`List[str]` - 模型名稱列表

**範例**：
```python
# 獲取 OpenAI 模型
models = await model_manager.get_available_models("openai")
# ['gpt-3.5-turbo', 'gpt-4', 'gpt-4-turbo']

# 獲取 Ollama 本地模型
models = await model_manager.get_available_models("ollama")
# ['llama2', 'mistral', 'codellama']
```

##### `get_recommended_model(task: str, llm_type: str) -> str`

獲取推薦模型。

**參數**：
- `task` (str): 任務類型 ("translation", "summarization", etc.)
- `llm_type` (str): LLM 類型

**回傳**：`str` - 推薦的模型名稱

**範例**：
```python
model = model_manager.get_recommended_model("translation", "openai")
# 'gpt-3.5-turbo'
```

##### `validate_model(model_name: str, llm_type: str) -> bool`

驗證模型是否可用。

**參數**：
- `model_name` (str): 模型名稱
- `llm_type` (str): LLM 類型

**回傳**：`bool` - 模型是否可用

**範例**：
```python
is_valid = model_manager.validate_model("gpt-4", "openai")
```

---

### PromptManager

提示詞管理器，管理翻譯提示詞模板。

#### 類別簽名

```python
class PromptManager:
    """管理翻譯提示詞"""
```

#### 建立實例

```python
from srt_translator.core.prompt import PromptManager

prompt_manager = PromptManager()
```

#### 主要方法

##### `get_prompt(llm_type: str, content_type: str = "general", style: str = "standard") -> str`

獲取翻譯提示詞。

**參數**：
- `llm_type` (str): LLM 類型
- `content_type` (str): 內容類型 ("general", "anime", "movie", "adult")
- `style` (str): 翻譯風格 ("standard", "literal", "localized", "specialized")

**回傳**：`str` - 提示詞文本

**範例**：
```python
# 一般內容標準翻譯
prompt = prompt_manager.get_prompt("openai", "general", "standard")

# 動畫內容本地化翻譯
prompt = prompt_manager.get_prompt("openai", "anime", "localized")
```

##### `set_prompt(llm_type: str, content_type: str, style: str, prompt: str) -> bool`

設定自訂提示詞。

**參數**：
- `llm_type` (str): LLM 類型
- `content_type` (str): 內容類型
- `style` (str): 翻譯風格
- `prompt` (str): 提示詞文本

**回傳**：`bool` - 是否成功

**範例**：
```python
custom_prompt = """Translate the following subtitle to Traditional Chinese.
Focus on natural expression and cultural adaptation."""

prompt_manager.set_prompt("openai", "movie", "standard", custom_prompt)
```

##### `get_all_content_types() -> List[str]`

獲取所有內容類型。

**回傳**：`List[str]` - 內容類型列表

**範例**：
```python
types = prompt_manager.get_all_content_types()
# ['general', 'anime', 'movie', 'adult']
```

---

## 翻譯模組 (translation)

### TranslationClient

翻譯 API 客戶端，封裝各種 AI 引擎的 API 呼叫。

#### 類別簽名

```python
class TranslationClient:
    """翻譯客戶端，封裝 API 呼叫"""
```

#### 建立實例

```python
from srt_translator.translation.client import TranslationClient

client = TranslationClient(
    llm_type="openai",
    model_name="gpt-3.5-turbo",
    api_key="your-api-key"
)
```

#### 主要方法

##### `__init__(llm_type: str, model_name: str, api_key: Optional[str] = None)`

初始化翻譯客戶端。

**參數**：
- `llm_type` (str): LLM 類型 ("ollama", "openai", "anthropic")
- `model_name` (str): 模型名稱
- `api_key` (Optional[str]): API 金鑰（Ollama 不需要）

##### `translate(text: str, source_lang: str, target_lang: str, context: Optional[List[str]] = None) -> str`

翻譯文本。

**參數**：
- `text` (str): 要翻譯的文本
- `source_lang` (str): 源語言
- `target_lang` (str): 目標語言
- `context` (Optional[List[str]]): 上下文列表

**回傳**：`str` - 翻譯結果

**範例**：
```python
translation = await client.translate(
    "Hello, world!",
    "English",
    "Traditional Chinese",
    context=["Previous subtitle here"]
)
# '你好，世界！'
```

##### `translate_batch(texts: List[str], source_lang: str, target_lang: str, concurrent_limit: int = 5) -> List[str]`

批量翻譯。

**參數**：
- `texts` (List[str]): 要翻譯的文本列表
- `source_lang` (str): 源語言
- `target_lang` (str): 目標語言
- `concurrent_limit` (int): 並發限制

**回傳**：`List[str]` - 翻譯結果列表

**範例**：
```python
texts = ["Hello", "World", "How are you?"]
translations = await client.translate_batch(
    texts,
    "English",
    "Traditional Chinese",
    concurrent_limit=3
)
# ['你好', '世界', '你好嗎？']
```

---

### TranslationManager

翻譯流程管理器，協調翻譯過程。

#### 類別簽名

```python
class TranslationManager:
    """管理翻譯流程"""
```

#### 建立實例

```python
from srt_translator.translation.manager import TranslationManager

manager = TranslationManager()
```

#### 主要方法

##### `translate_file(input_path: str, output_path: str, source_lang: str, target_lang: str, llm_type: str, model_name: str, display_mode: str = "bilingual", progress_callback: Optional[Callable] = None) -> bool`

翻譯整個字幕檔案。

**參數**：
- `input_path` (str): 輸入檔案路徑
- `output_path` (str): 輸出檔案路徑
- `source_lang` (str): 源語言
- `target_lang` (str): 目標語言
- `llm_type` (str): LLM 類型
- `model_name` (str): 模型名稱
- `display_mode` (str): 顯示模式
- `progress_callback` (Optional[Callable]): 進度回調函數

**回傳**：`bool` - 是否成功

**範例**：
```python
def on_progress(current, total):
    print(f"進度: {current}/{total}")

success = await manager.translate_file(
    "input.srt",
    "output.srt",
    "Japanese",
    "Traditional Chinese",
    "openai",
    "gpt-3.5-turbo",
    display_mode="bilingual",
    progress_callback=on_progress
)
```

---

## 檔案處理模組 (file_handling)

### FileHandler

字幕檔案處理器，處理檔案的讀取、解析和儲存。

#### 類別簽名

```python
class FileHandler:
    """處理字幕檔案的讀取、解析和儲存"""
```

#### 建立實例

```python
from srt_translator.file_handling.handler import FileHandler

file_handler = FileHandler()
```

#### 主要方法

##### `read_subtitle_file(file_path: str) -> SubtitleInfo`

讀取字幕檔案。

**參數**：
- `file_path` (str): 檔案路徑

**回傳**：`SubtitleInfo` - 字幕資訊物件

**範例**：
```python
subtitle_info = file_handler.read_subtitle_file("input.srt")
print(f"字幕數量: {len(subtitle_info.subtitles)}")
print(f"檔案格式: {subtitle_info.format}")
```

##### `write_subtitle_file(file_path: str, subtitles: List[Subtitle], format: str = "srt") -> bool`

寫入字幕檔案。

**參數**：
- `file_path` (str): 輸出路徑
- `subtitles` (List[Subtitle]): 字幕列表
- `format` (str): 檔案格式

**回傳**：`bool` - 是否成功

**範例**：
```python
success = file_handler.write_subtitle_file(
    "output.srt",
    translated_subtitles,
    format="srt"
)
```

##### `detect_encoding(file_path: str) -> str`

偵測檔案編碼。

**參數**：
- `file_path` (str): 檔案路徑

**回傳**：`str` - 編碼名稱

**範例**：
```python
encoding = file_handler.detect_encoding("input.srt")
# 'utf-8'
```

---

## 服務工廠 (services)

### ServiceFactory

服務工廠，統一管理所有服務實例（單例模式）。

#### 類別簽名

```python
class ServiceFactory:
    """服務工廠類，管理所有服務實例"""
```

#### 主要方法

##### `get_translation_service() -> TranslationService`

獲取翻譯服務實例。

**回傳**：`TranslationService` - 翻譯服務

**範例**：
```python
from srt_translator.services.factory import ServiceFactory

translation_service = ServiceFactory.get_translation_service()
```

##### `get_model_service() -> ModelService`

獲取模型服務實例。

**回傳**：`ModelService` - 模型服務

**範例**：
```python
model_service = ServiceFactory.get_model_service()
models = await model_service.get_available_models("openai")
```

##### `get_cache_service() -> CacheService`

獲取快取服務實例。

**回傳**：`CacheService` - 快取服務

**範例**：
```python
cache_service = ServiceFactory.get_cache_service()
stats = cache_service.get_cache_stats()
```

##### `get_file_service() -> FileService`

獲取檔案服務實例。

**回傳**：`FileService` - 檔案服務

**範例**：
```python
file_service = ServiceFactory.get_file_service()
subtitle_info = file_service.read_subtitle_file("input.srt")
```

##### `reset_services() -> None`

重置所有服務實例（清理資源）。

**範例**：
```python
# 應用程式關閉時呼叫
ServiceFactory.reset_services()
```

---

## 工具模組 (utils)

### 錯誤類別

#### AppError

應用程式基礎錯誤類別。

```python
from srt_translator.utils.errors import AppError

class AppError(Exception):
    """應用程式基礎錯誤"""
```

#### TranslationError

翻譯相關錯誤。

```python
from srt_translator.utils.errors import TranslationError

class TranslationError(AppError):
    """翻譯過程錯誤"""
```

#### FileHandlingError

檔案處理錯誤。

```python
from srt_translator.utils.errors import FileHandlingError

class FileHandlingError(AppError):
    """檔案處理錯誤"""
```

#### APIError

API 呼叫錯誤。

```python
from srt_translator.utils.errors import APIError

class APIError(AppError):
    """API 呼叫錯誤"""
```

### 輔助函數

#### `safe_execute(func: Callable, *args, **kwargs) -> Tuple[bool, Any, Optional[Exception]]`

安全執行函數，捕獲異常。

**參數**：
- `func` (Callable): 要執行的函數
- `*args`: 位置參數
- `**kwargs`: 關鍵字參數

**回傳**：`Tuple[bool, Any, Optional[Exception]]` - (成功, 結果, 異常)

**範例**：
```python
from srt_translator.utils import safe_execute

success, result, error = safe_execute(risky_function, arg1, arg2)
if success:
    print(f"結果: {result}")
else:
    print(f"錯誤: {error}")
```

#### `format_exception(e: Exception) -> str`

格式化異常訊息。

**參數**：
- `e` (Exception): 異常物件

**回傳**：`str` - 格式化的錯誤訊息

**範例**：
```python
from srt_translator.utils import format_exception

try:
    # some code
except Exception as e:
    error_msg = format_exception(e)
    logger.error(error_msg)
```

#### `check_internet_connection() -> bool`

檢查網路連接。

**回傳**：`bool` - 是否連接網路

**範例**：
```python
from srt_translator.utils import check_internet_connection

if not check_internet_connection():
    print("無網路連接")
```

---

## 使用範例

### 範例 1：簡單翻譯流程

```python
import asyncio
from srt_translator.services.factory import ServiceFactory

async def translate_file():
    # 獲取服務
    translation_service = ServiceFactory.get_translation_service()
    file_service = ServiceFactory.get_file_service()

    # 讀取字幕
    subtitle_info = file_service.read_subtitle_file("input.srt")

    # 翻譯
    translated = await translation_service.translate_text(
        subtitle_info.subtitles[0].text,
        ["Previous context"],
        "openai",
        "gpt-3.5-turbo"
    )

    print(f"翻譯結果: {translated}")

# 執行
asyncio.run(translate_file())
```

### 範例 2：使用快取

```python
from srt_translator.core.cache import CacheManager

cache_manager = CacheManager()

# 嘗試從快取獲取
cached = cache_manager.get_cached_translation(
    "Hello",
    [],
    "gpt-3.5-turbo"
)

if cached:
    print(f"快取命中: {cached}")
else:
    # 翻譯並儲存到快取
    translation = await translate("Hello")
    cache_manager.save_translation(
        "Hello",
        translation,
        [],
        "gpt-3.5-turbo"
    )
```

### 範例 3：自訂配置

```python
from srt_translator.core.config import ConfigManager

# 獲取配置管理器
config = ConfigManager.get_instance("user")

# 設定自訂值
config.set_value("theme", "dark")
config.set_value("parallel_requests", 10)
config.set_value("auto_save", True)

# 儲存配置
config.save_config()
```

### 範例 4：批量處理

```python
import asyncio
from srt_translator.translation.client import TranslationClient

async def batch_translate():
    client = TranslationClient("openai", "gpt-3.5-turbo", "your-api-key")

    texts = [
        "Hello, world!",
        "How are you?",
        "Nice to meet you."
    ]

    results = await client.translate_batch(
        texts,
        "English",
        "Traditional Chinese",
        concurrent_limit=3
    )

    for original, translated in zip(texts, results):
        print(f"{original} → {translated}")

asyncio.run(batch_translate())
```

---

## 最佳實踐

### 1. 使用服務工廠

始終透過 `ServiceFactory` 獲取服務實例，確保單例模式：

```python
# ✅ 正確
translation_service = ServiceFactory.get_translation_service()

# ❌ 錯誤（不建議）
translation_service = TranslationService()
```

### 2. 錯誤處理

使用專案提供的錯誤類別和輔助函數：

```python
from srt_translator.utils import safe_execute, format_exception
from srt_translator.utils.errors import TranslationError

try:
    result = await translate(text)
except TranslationError as e:
    logger.error(format_exception(e))
```

### 3. 非同步操作

翻譯操作是非同步的，務必使用 `async/await`：

```python
# ✅ 正確
translation = await client.translate(text, source_lang, target_lang)

# ❌ 錯誤
translation = client.translate(text, source_lang, target_lang)
```

### 4. 資源清理

應用程式關閉時清理資源：

```python
# 在應用程式結束時
ServiceFactory.reset_services()
```

### 5. 配置管理

使用配置管理器集中管理配置：

```python
# ✅ 正確
from srt_translator.core.config import get_config
theme = get_config("user", "theme", "default")

# ❌ 錯誤（硬編碼）
theme = "dark"
```

---

## 型別提示

本專案支援型別提示，建議使用 mypy 進行型別檢查：

```bash
uv run mypy src/srt_translator
```

---

**最後更新**：2025-01-28
**版本**：1.0.0
