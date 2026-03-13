# API 文檔

> SRT Subtitle Translator 開發者 API 參考

## 目錄

- [概述](#概述)
- [核心模組 (core)](#核心模組-core)
  - [ConfigManager](#configmanager)
  - [CacheManager](#cachemanager)
  - [GlossaryManager](#glossarymanager)
  - [ModelManager](#modelmanager)
  - [PromptManager](#promptmanager)
- [翻譯模組 (translation)](#翻譯模組-translation)
  - [TranslationClient](#translationclient)
  - [TranslationManager](#translationmanager)
- [檔案處理模組 (file_handling)](#檔案處理模組-file_handling)
  - [FileHandler](#filehandler)
- [服務工廠 (services)](#服務工廠-services)
  - [ServiceFactory](#servicefactory)
- [SRT 工具模組 (tools)](#srt-工具模組-tools)
  - [extract / assemble / qa / cps_audit](#extract--assemble--qa--cps_audit)
  - [批次文本輔助函式](#批次文本輔助函式)
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

### 現況提醒

- 文件若與 `src/` 內實作衝突，請以 `src/` 為準
- provider 相關資訊需要區分「模型資訊 / 可用模型發現」與「真正可執行的翻譯 runtime」
- 目前 `TranslationClient` 的翻譯執行路徑實作為 `ollama`、`openai`、`google`、`llamacpp`
- `llamacpp` 透過 OpenAI 相容 API 連接本地 `llama-server`，不需要 API 金鑰
- `anthropic` 目前主要接在模型資訊與金鑰層，尚未是第一級翻譯 runtime
- provider 支援目前仍有分層差異：runtime 為 `ollama` / `openai` / `google` / `llamacpp`；CLI parser 為 `ollama` / `openai` / `anthropic` / `llamacpp`；GUI 下拉為 `ollama` / `openai` / `anthropic` / `google` / `llamacpp`
- OpenRouter 仍屬規劃中，不在目前 public API 範圍內

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
├── tools/             # SRT 工具箱
│   └── srt_tools.py   # extract/assemble/qa/cps-audit
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

##### `store_translation(source_text: str, target_text: str, context_texts: List[str], model_name: str, style: str = "standard", prompt_version: str = "") -> bool`

儲存翻譯到快取。

**參數**：
- `text` (str): 原始文本
- `translation` (str): 翻譯結果
- `context` (List[str]): 上下文列表
- `model_name` (str): 模型名稱

**回傳**：`bool` - 是否成功

**範例**：
```python
cache_manager.store_translation(
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

### GlossaryManager

術語表管理器，確保專有名詞翻譯一致性。

#### 類別簽名

```python
class GlossaryManager:
    """管理翻譯術語表"""
```

#### 建立實例

```python
from srt_translator.core.glossary import GlossaryManager

glossary_manager = GlossaryManager()
```

#### 主要方法

##### `create_glossary(name: str, source_lang: str, target_lang: str) -> bool`

建立新術語表。

**參數**：
- `name` (str): 術語表名稱
- `source_lang` (str): 來源語言
- `target_lang` (str): 目標語言

**回傳**：`bool` - 是否成功

**範例**：
```python
glossary_manager.create_glossary("anime", "日文", "繁體中文")
```

##### `add_term(glossary_name: str, source: str, target: str) -> bool`

新增術語到術語表。

**參數**：
- `glossary_name` (str): 術語表名稱
- `source` (str): 原始詞彙
- `target` (str): 翻譯詞彙

**範例**：
```python
glossary_manager.add_term("anime", "エレン", "艾連")
```

##### `get_terms(glossary_name: str) -> Dict[str, str]`

取得術語表中所有詞彙。

**回傳**：`Dict[str, str]` - `{source: target}` 字典

**範例**：
```python
terms = glossary_manager.get_terms("anime")
# {"エレン": "艾連", "ミカサ": "米卡莎"}
```

##### `list_glossaries() -> List[str]`

列出所有術語表名稱。

**回傳**：`List[str]` - 術語表名稱列表

##### `export_glossary(name: str, format: str = "json") -> str`

匯出術語表為指定格式（json / csv / txt）。

**回傳**：`str` - 序列化後的內容

##### `import_glossary(name: str, content: str, format: str = "json") -> bool`

從字串匯入術語表。

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

##### `get_model_list_async(llm_type: str, api_key: str | None = None) -> list[ModelInfo]`

獲取可用模型列表。

**參數**：
- `llm_type` (str): LLM 類型（`"ollama"`、`"openai"`、`"anthropic"`、`"google"`、`"llamacpp"`）
- `api_key` (str | None): 覆蓋預設金鑰的可選值

**回傳**：`list[ModelInfo]` - 包含 provider、能力、可用性等資訊的模型列表

**範例**：
```python
models = await model_manager.get_model_list_async("openai")
model_ids = [model.id for model in models]

# ['gpt-4o', 'gpt-4-turbo', ...]
```

##### `get_model_list(llm_type: str, api_key: str | None = None) -> list[str]`

同步包裝版，回傳純模型 ID 清單，主要用於向後相容。

##### `get_recommended_model(task_type: str = "translation", provider: str | None = None) -> ModelInfo | None`

獲取推薦模型。

**參數**：
- `task_type` (str): 任務類型
- `provider` (str | None): 指定 provider；未指定時依目前設定挑選

**回傳**：`ModelInfo | None` - 推薦模型資訊；若找不到則回傳 `None`

**範例**：
```python
model = model_manager.get_recommended_model("translation", "openai")
if model:
    print(model.id, model.provider)
```

##### `test_model_connection(model_name: str, provider: str, api_key: str | None = None) -> dict[str, Any]`

測試模型連線。

**參數**：
- `model_name` (str): 模型名稱
- `provider` (str): provider 名稱
- `api_key` (str | None): 可選覆蓋金鑰

**回傳**：`dict[str, Any]` - 包含 `success` 與 `message`

**範例**：
```python
result = await model_manager.test_model_connection("gpt-4o", "openai")
print(result["success"], result["message"])
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

##### `get_prompt(llm_type: str = "ollama", content_type: str | None = None, style: str | None = None, model_name: str | None = None) -> str`

獲取翻譯提示詞。

**參數**：
- `llm_type` (str): LLM 類型
- `content_type` (str): 內容類型 ("general", "anime", "movie", "adult", "english_drama")
- `style` (str): 翻譯風格 ("standard", "literal", "localized", "specialized")
- `model_name` (str | None): 模型名稱；部分模型特化 prompt 會使用此值

**回傳**：`str` - 提示詞文本

**範例**：
```python
# 一般內容標準翻譯
prompt = prompt_manager.get_prompt("openai", "general", "standard")

# 動畫內容本地化翻譯
prompt = prompt_manager.get_prompt("openai", "anime", "localized")
```

##### `set_prompt(new_prompt: str, llm_type: str = "ollama", content_type: str | None = None) -> bool`

設定自訂提示詞。

**參數**：
- `new_prompt` (str): 提示詞文本
- `llm_type` (str): LLM 類型
- `content_type` (str | None): 內容類型；未指定時沿用當前設定

**回傳**：`bool` - 是否成功

**範例**：
```python
custom_prompt = """Translate the following subtitle to Traditional Chinese.
Focus on natural expression and cultural adaptation."""

prompt_manager.set_prompt(custom_prompt, "openai", "movie")
```

##### `get_available_content_types() -> list[str]`

獲取所有內容類型。

**回傳**：`List[str]` - 內容類型列表

**範例**：
```python
types = prompt_manager.get_available_content_types()
# ['general', 'anime', 'movie', 'adult', 'english_drama']
```

##### `get_batch_line_mapping_instruction() -> str`

取得批次翻譯的行對應說明，供 `--structure-text` 模式使用。

**回傳**：`str` - 說明文字，要求模型保持嚴格 1:1 行數對應

**範例**：
```python
instruction = prompt_manager.get_batch_line_mapping_instruction()
# 回傳要求 LLM 保持行數 1:1 的指令字串
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
    api_key="your-api-key",
    cache_db_path="data/translation_cache.db"
)
```

> `TranslationClient` 目前的翻譯執行路徑實作為 `ollama`、`openai`、`google`、`llamacpp`；`anthropic` 尚未是第一級 runtime。

#### 主要方法

##### `__init__(llm_type: str, base_url: str = "http://localhost:11434", api_key: str | None = None, cache_db_path: str = "data/translation_cache.db", netflix_style_config: dict[str, Any] | None = None)`

初始化翻譯客戶端。

**參數**：
- `llm_type` (str): runtime 支援的 LLM 類型（`"ollama"`、`"openai"`、`"google"`、`"llamacpp"`）
- `base_url` (str): API 基礎位址（Ollama / llamacpp 可覆蓋）
- `api_key` (Optional[str]): API 金鑰（Ollama / llamacpp 不需要）
- `cache_db_path` (str): 翻譯快取資料庫路徑
- `netflix_style_config` (dict | None): 後處理配置

##### `translate_text(text: str, context_texts: list[str], model_name: str) -> str`

翻譯文本。

**參數**：
- `text` (str): 要翻譯的文本
- `context_texts` (list[str]): 上下文列表
- `model_name` (str): 模型名稱

**回傳**：`str` - 翻譯結果

**範例**：
```python
translation = await client.translate_text(
    "Hello, world!",
    ["Previous subtitle here"],
    "gpt-4o"
)
# '你好，世界！'
```

##### `translate_with_retry(text: str, context_texts: list[str], model_name: str, max_retries: int = 3, use_fallback: bool = True) -> str`

帶有重試與 fallback 的單句翻譯入口，通常是上層服務真正呼叫的方法。

##### `translate_batch(texts: list[tuple[str, list[str]]], model_name: str, concurrent_limit: int = 5) -> list[str]`

批量翻譯。

**參數**：
- `texts` (list[tuple[str, list[str]]]): `(text, context_texts)` 組成的列表
- `model_name` (str): 模型名稱
- `concurrent_limit` (int): 並發限制

**回傳**：`list[str]` - 翻譯結果列表

**範例**：
```python
texts = [
    ("Hello", []),
    ("World", ["Hello"]),
    ("How are you?", ["Hello", "World"]),
]
translations = await client.translate_batch(
    texts,
    "gpt-4o",
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

manager = TranslationManager(
    file_path="input.srt",
    source_lang="日文",
    target_lang="繁體中文",
    model_name="gpt-4o",
    parallel_requests=3,
    progress_callback=None,
    complete_callback=None,
    display_mode="雙語對照",
    llm_type="openai",
)
```

#### 主要方法

##### `initialize() -> None`

初始化所需服務、模型客戶端與統計狀態。

##### `translate_subtitles() -> None`

執行整個字幕翻譯流程。

##### `cleanup() -> None`

釋放客戶端與執行期資源。

##### `pause() / resume() / stop()`

控制長時間翻譯任務。

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

## SRT 工具模組 (tools)

### extract / assemble / qa / cps_audit

SRT 工具箱提供結構-文本分離工作流和品質檢驗功能。

#### 使用方式

```python
from srt_translator.tools import extract, assemble, qa, cps_audit
```

##### `extract(srt_path: str, output_prefix: str | None = None) -> tuple[str, str]`

將 SRT 拆分為結構檔和純文字檔。

**參數**：
- `srt_path` (str): SRT 檔案路徑
- `output_prefix` (str, 可選): 輸出檔案前綴，預設使用原檔名

**回傳**：`tuple[str, str]` - (結構檔路徑, 文字檔路徑)

**範例**：
```python
structure_path, text_path = extract("video.srt")
# ('video_structure.json', 'video_text.txt')
```

##### `assemble(base_prefix: str, text_suffix: str = "_translated_text.txt", output_path: str | None = None) -> str`

將翻譯後的文字與結構重組為 SRT。

**參數**：
- `base_prefix` (str): 基礎前綴（對應 extract 的輸出）
- `text_suffix` (str): 翻譯文字檔後綴
- `output_path` (str, 可選): 輸出 SRT 路徑

**回傳**：`str` - 輸出 SRT 路徑

##### `qa(source_srt_path: str, target_srt_path: str) -> QAResult`

比對源檔與翻譯檔的結構完整性。

**回傳**：`QAResult` - 包含 `passed`、`issues` 等屬性

```python
result = qa("source.srt", "translated.srt")
if result.passed:
    print("結構完整性檢查通過")
else:
    for issue in result.issues:
        print(f"問題: {issue}")
```

##### `cps_audit(srt_path: str, max_cps: float = 17.0, ...) -> CpsAuditReport`

CPS 可讀性審計。

**回傳**：`CpsAuditReport` - 包含 `total`、`flagged`、`entries` 等屬性

```python
report = cps_audit("translated.srt")
print(f"總字幕: {report.total}, 有問題: {report.flagged}")
for entry in report.entries:
    print(f"#{entry.index}: CPS={entry.cps:.1f}, 問題={entry.issues}")
```

### 批次文本輔助函式

##### `texts_to_batch_string(texts: list[str]) -> str`

將字幕文本列表序列化為批次字串（每行一字幕，多行字幕用 literal `\n` 合併）。

##### `batch_string_to_texts(batch_string: str, expected_count: int) -> list[str]`

將批次翻譯結果反序列化為字幕文本列表，含行數驗證。

```python
from srt_translator.tools import texts_to_batch_string, batch_string_to_texts

batch = texts_to_batch_string(["Hello\nWorld", "Goodbye"])
# "Hello\\nWorld\nGoodbye"

texts = batch_string_to_texts("你好\\n世界\n再見", 2)
# ["你好\n世界", "再見"]
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
    translation = "你好"
    cache_manager.store_translation(
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
    client = TranslationClient("openai", api_key="your-api-key")

    texts = [
        ("Hello, world!", []),
        ("How are you?", ["Hello, world!"]),
        ("Nice to meet you.", ["Hello, world!", "How are you?"]),
    ]

    results = await client.translate_batch(
        texts,
        "gpt-3.5-turbo",
        concurrent_limit=3
    )

    for (original, _), translated in zip(texts, results):
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
    result = await client.translate_text(text, [], "gpt-3.5-turbo")
except TranslationError as e:
    logger.error(format_exception(e))
```

### 3. 非同步操作

翻譯操作是非同步的，務必使用 `async/await`：

```python
# ✅ 正確
translation = await client.translate_text(text, context_texts, "gpt-3.5-turbo")

# ❌ 錯誤
translation = client.translate_text(text, context_texts, "gpt-3.5-turbo")
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

**最後更新**：2026-03-12
**版本**：1.1.0+
