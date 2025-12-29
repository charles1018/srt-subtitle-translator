# 變更日誌

本檔案記錄專案的所有重要變更。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)，
版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

## [Unreleased]

### 🔄 變更

#### 預設翻譯設定調整
- 🔧 調整預設設定以更符合常見使用情境
  - **來源語言**：日文 → 英文
  - **LLM 類型**：ollama → openai
  - **顯示模式**：雙語對照 → 僅顯示翻譯
  - **Commit**: 0cb0ca9

### 🐛 修復

#### 中期代碼審查修復 (ID 7-16)
- 🔧 **ConfigManager singleton 記憶體洩漏風險** (config.py)
  - 添加 `ALLOWED_CONFIG_TYPES` frozenset 限制有效的 config_type
  - 防止任意字串創建無限實例導致記憶體洩漏
  - **Commit**: 72fff28
- 🔧 **Rate limit 檢查 IndexError 風險** (client.py)
  - 在訪問 `request_timestamps[0]` 和 `token_usage[0]` 前添加空列表檢查
  - 防止極端並發情況下的 IndexError
  - **Commit**: 72fff28
- 🔧 **FileHandler Singleton 實作不完整** (handler.py)
  - 在 `__init__` 添加檢查，防止直接實例化繞過 singleton
  - 當 singleton 已存在時拋出 RuntimeError
  - **Commit**: 72fff28
- 🔧 **subprocess 缺少 timeout** (handler.py)
  - ffmpeg 版本檢查添加 10 秒 timeout
  - 字幕提取添加 300 秒 timeout
  - 添加 TimeoutExpired 異常處理
  - **Commit**: 72fff28
- 🔧 **快取清理觸發條件註解不一致** (cache.py)
  - 更新 `CLEANUP_TRIGGER_RATIO` 註解明確「嚴格超過」語義
  - 說明使用 `>` 而非 `>=` 的設計意圖
  - **Commit**: 72fff28
- 🔧 **編碼偵測只讀取 4KB** (handler.py)
  - 增加讀取大小至 16KB 以更好偵測 CJK 字符
  - 優先檢查 BOM（最可靠）
  - 低置信度時記錄警告
  - **Commit**: 72fff28
- 🔧 **語言偵測 regex 缺陷** (helpers.py)
  - 簡化為通用 CJK 範圍 `[\u4E00-\u9FFF]`
  - 移除錯誤的雙字符匹配模式
  - 中文默認返回 `zh-tw`（繁簡體區分困難）
  - **Commit**: 72fff28
- 🔧 **RLock 使用註解誤導** (cache.py)
  - 在 `_clean_memory_cache` 添加顯式鎖（RLock 允許重入）
  - 更新 docstring 說明重入行為
  - **Commit**: 72fff28
- 🔧 **Logger 配置重複風險** (logging_config.py, handler.py)
  - 使用自定義屬性 `_srt_translator_configured` 標記已配置的 logger
  - 比檢查 handlers 更可靠（並發安全）
  - **Commit**: 72fff28

#### 快取系統優化
- 🔧 修復資料庫連線未正確關閉的問題 (ResourceWarning)
  - 建立自訂 `sqlite_connection()` context manager
  - 確保事務正確提交和連線關閉
  - 解決 Python 3.11 及之前版本的 sqlite3 連線問題
  - ResourceWarning 從 218 個減少至 8 個（僅剩 mock 測試產生）
  - **Commit**: 081fb71
- 🔧 將快取清理閾值抽取為類別常數
  - 新增 `CLEANUP_TRIGGER_RATIO` (1.2) 和 `CLEANUP_KEEP_RATIO` (0.7)
  - 提高程式碼可讀性和維護性
  - 修正測試以使用類別常數進行斷言
  - **Commit**: 8d55c22

#### 連接詞保留問題修復
- 🔧 修復不完整句子中連接詞被忽略的問題
  - **問題**：當句子以連接詞結尾（when, if, because 等）時，AI 傾向於「完成」句子而忽略連接詞，導致語義連接丟失
  - **解決方案**：在提示詞中添加連接詞保留規則
    - 明確要求保留連接詞（when, if, because, although, while, before, after, unless, though 等）
    - 保持句子的不完整性，不要試圖「完成」或「截斷」句子
    - 提供具體範例說明正確處理方式
  - **影響範圍**：Ollama 和 OpenAI 兩個版本的 `english_drama` 提示詞
  - **測試**：53 個單元測試全部通過
  - **Commit**: b2e27b0

#### 翻譯斷句問題修復
- 🔧 修復 `english_drama` 模式翻譯長句時出現不必要換行的問題
  - **問題**：AI 在翻譯長句（如新聞播報）時會在翻譯結果中插入換行符，導致字幕顯示時出現不適當的斷行
  - **解決方案**：採用雙重保險機制
    1. **提示詞增強**：在 `english_drama` 提示詞中明確要求 "1 input line = 1 output line, NEVER insert newlines in single-line translations"
    2. **後處理清理**：在 `client.py` 新增 `_clean_single_line_translation()` 方法，自動清除單行原文翻譯結果中的多餘換行符和空白字符
  - **影響範圍**：所有內容類型均受益於後處理邏輯，確保單行字幕不會被意外拆分
- 🔧 修正配置驗證邏輯，添加 `english_drama` 到有效內容類型列表

### ✨ 新增

#### GUI 快取管理功能增強
- 🎨 重構快取管理器界面，提供完整的快取管理功能
  - **統計資訊顯示**：總條目數、資料庫大小、記憶體快取大小、命中率、查詢總數
  - **清除所有快取**：一鍵清除所有翻譯快取，附帶確認對話框和警告訊息
  - **自動備份**：清除前自動建立資料庫備份
  - **即時重新整理**：提供重新整理按鈕更新統計資訊
  - **熱門翻譯顯示**：展示前 5 筆最常使用的翻譯
  - **Commit**: bcfd3c8

#### 提示詞系統增強式整合
- 🎯 新增 `english_drama` 內容類型 - 專為英語劇集/影視作品優化
  - 整合網頁版 Claude 高質量翻譯提示詞
  - 包含詳細的人名保留規則（禁止音譯人名）
  - 提供專業術語映射表（消防、醫療等領域）
  - 包含豐富的翻譯範例和工作流程指導
- 🧩 創建可重用核心模組（適用於所有內容類型）
  - **人名保留規則模組** (`name_preservation_rules`)
    - 明確要求保留英文人名原文
    - 提供正確/錯誤範例對照
    - 支持職銜與人名組合翻譯
  - **台式口語表達模組** (`taiwanese_colloquial`)
    - 台灣與大陸用語對照表
    - 自然口語化表達指導
    - 文化適配性建議
- 🔄 增強現有內容類型
  - `general`: 添加台式表達模組
  - `anime`: 添加台式表達模組和動漫專用術語指導
  - `movie`: 添加人名保留、台式表達和 Netflix 規範
  - `adult`: 添加台式表達模組
- 🖥️ GUI 更新支持新內容類型選項
  - 在內容類型下拉選單中添加 "english_drama"
  - 完整兼容現有提示詞管理功能（版本歷史、匯入/匯出等）

#### Netflix 繁體中文字幕風格支援
- 🎬 整合 Netflix 繁體中文字幕風格規範到提示詞系統
- 🔧 新增 `NetflixStylePostProcessor` 後處理器
  - 自動修正標點符號格式（全形中文標點）
  - 轉換引號格式為中文引號「」和『』
  - 修正數字格式（全形轉半形，移除四位數逗號）
  - 統一省略號格式為 ⋯ (U+22EF)
  - 自動移除行尾的句號和逗號
  - 檢查字符限制（每行最多 16 個字符，最多 2 行）
  - 檢查問號使用（避免雙問號、雙驚嘆號）
- 🖥️ GUI 新增 Netflix 風格選項核取方塊
  - 使用者可透過介面簡單啟用/停用 Netflix 風格
  - 設定自動儲存到使用者配置檔案
- 📊 提供詳細的警告和自動修正統計（可在日誌中查看）

#### 自動斷行功能
- 🔧 新增智慧分割長行功能（`_smart_split_line()`）
  - 優先在標點符號（逗號、頓號）後斷行
  - 在連接詞（和、與、或、但）前後斷行
  - 在空格處斷行
  - 確保每行不超過字符限制
- 🎯 將 `_check_character_limit()` 升級為 `_check_and_fix_character_limit()`
  - 支援自動修正過長字幕行
  - 提供詳細的分割日誌和警告

### ⚡ 效能優化

#### 快取清理演算法優化
- 🚀 **MemoryCache 清理效能改進** (helpers.py)
  - 使用 `heapq.nsmallest()` 取代 `sorted()`
  - 時間複雜度從 O(n log n) 降為 O(n log k)
  - 僅找出需要刪除的項目，避免完整排序
  - **Commit**: 72fff28

#### 快取系統優化
- 🚀 優化快取清理觸發機制
  - 將觸發閾值從 100% 提升至 120%（減少不必要的清理）
  - 將保留比例從 50% 提升至 70%（保留更多快取）
  - 預期效果：快取清理次數 -88%（82 次 → 5-10 次）
- 📊 增強快取日誌記錄
  - 在初始化時記錄 `max_memory_cache` 實際值
  - 添加 debug 級別的清理檢查日誌
  - 添加 info 級別的執行結果日誌

#### 動態並發控制
- 🎛️ 新增 `AdaptiveConcurrencyController` 自適應並發控制器
  - 根據 API 回應時間動態調整並發數（範圍 2-10）
  - 使用指數移動平均（EMA）平滑回應時間波動
  - API 回應快時（< 0.5 秒）自動增加並發數
  - API 回應慢時（> 1.5 秒）自動降低並發數
- ⚙️ 在 `TranslationClient` 中整合動態並發控制
  - 每次翻譯後自動更新並發數
  - 預期效果：平均翻譯時間 -25%（4 分鐘 → 3 分鐘）

### 🔄 變更
- 🏭 更新 `ModelService.get_translation_client()` 從配置讀取 Netflix 風格設定
- ⚙️ 修改 `TranslationClient` 初始化支援 Netflix 風格配置參數
- 🎯 強化 Netflix 風格提示詞
  - 添加 ⚠️ 警告標記強調 16 字符限制
  - 提供具體的正確與錯誤分行範例
  - 添加明確的分行指引
  - 預期效果：Netflix 規範符合率 +121%（34% → 75%）

### 🐛 修復
- 🔧 修復 asyncio 事件循環警告
  - 改善 `get_model_list()` 的事件循環處理
  - 改善 `cleanup()` 的事件循環處理
  - 正確檢測並處理已關閉的循環
  - 避免在運行中的循環上調用 `close()`

### 計劃中的功能
- Web 介面版本
- 語音識別功能
- 批量時間軸調整
- 使用者字典和術語庫
- 翻譯品質評估
- 多人協作翻譯

---

## [1.0.0] - 2025-01-28

### 🎉 首個正式版本

經過三個階段的開發和完整的測試體系建立，SRT Subtitle Translator 1.0.0 正式發布！

### ✨ 新增

#### 核心功能
- 🌍 多語言字幕翻譯支援（10+ 種語言）
- 🤖 多 AI 引擎支援（Ollama、OpenAI、Anthropic）
- 📝 多字幕格式支援（SRT、VTT、ASS/SSA）
- ⚡ 批量處理和並發翻譯
- 💾 翻譯記憶快取系統（SQLite）
- 🎨 多種字幕顯示模式（雙語、單語、上下對調）

#### 使用者介面
- 🖥️ 友善的圖形使用者介面（Tkinter）
- 🖱️ 拖放檔案支援
- 📊 即時進度顯示
- ⏸️ 暫停/繼續/停止控制
- 🎯 自訂提示詞編輯器

#### 進階功能
- 🔄 智慧檔案衝突處理
- 🔍 自動編碼偵測
- 🎯 內容類型與翻譯風格選擇
- 📈 翻譯進度追蹤
- 🔔 完成通知

### 🏗️ 架構改進

#### 階段一：專案重構與模組化
- 建立清晰的模組化架構
- 實作服務工廠模式（ServiceFactory）
- 分離核心模組（core）、翻譯模組（translation）、檔案處理（file_handling）
- 統一配置管理系統（ConfigManager）
- 改進日誌系統

#### 階段二：單元測試體系建立
- 建立完整的單元測試框架（477 個測試）
- 核心模組測試覆蓋率 85%+
- 整合測試 20 個
- 測試通過率 100%

#### 階段三：E2E 測試完整覆蓋
- 建立 E2E 測試框架（38 個測試）
- 基本翻譯流程測試（5 個測試）
- 翻譯工作流測試（8 個測試）
- 配置整合與錯誤處理測試（14 個測試）
- 批量處理與效能測試（11 個測試）
- E2E 測試覆蓋率 22%

### 📚 文檔

#### 階段四：文檔完善與發布準備
- 📖 完整的 README.md（反映新架構）
- 📕 詳細的使用者指南（USER_GUIDE.md）
- 📘 開發者 API 文檔（API.md）
- 📗 貢獻指南（CONTRIBUTING.md）
- 📙 開發者文檔（DEVELOPMENT.md）
- 📋 變更日誌（CHANGELOG.md）

### 🛠️ 技術細節

#### 依賴更新
- Python 3.8+ 支援
- pysrt >= 1.1.2
- openai >= 1.12.0
- anthropic >= 0.8.0
- aiohttp >= 3.9.0
- pytest >= 7.4.0（開發依賴）
- ruff >= 0.1.0（開發依賴）

#### 配置系統
- 支援 6 種配置類型（app、user、model、prompt、file、cache）
- JSON 格式配置檔案
- 自動載入與儲存
- 配置變更監聽器

#### 快取系統
- SQLite 資料庫儲存
- 基於文本、上下文和模型的快取鍵
- 自動過期機制（預設 30 天）
- 快取統計與管理

### 🎯 效能優化
- 並發翻譯支援（可調整並發數）
- 批量處理優化
- 快取命中率追蹤
- 非同步 I/O

### 🐛 已知問題
- GUI 在某些 Linux 發行版可能需要額外的 TkDnD 支援
- 大型檔案（1000+ 字幕）處理時記憶體使用較高
- Ollama 連接超時可能需要手動重試

### 📊 專案統計
- 總程式碼行數：3500+
- 總測試數：515 個
  - 單元測試：477 個
  - 整合測試：20 個
  - E2E 測試：38 個
- 測試通過率：100%
- 測試覆蓋率：22%（E2E 覆蓋）
- 支援語言：10+ 種

---

## [0.9.0] - 2025-01-27

### ✨ 新增
- E2E 測試框架建立
- 批量處理與效能測試

### 🔧 改進
- 測試架構完善
- 測試覆蓋率提升至 22%

---

## [0.8.0] - 2025-01-26

### ✨ 新增
- 核心模組單元測試（477 個測試）
- 整合測試框架（20 個測試）

### 🔧 改進
- CacheManager 測試覆蓋率達 94%
- ConfigManager 測試覆蓋率達 94%
- ModelManager 測試覆蓋率達 66%
- helpers.py 測試覆蓋率達 88%
- 整體測試覆蓋率達 82%

---

## [0.7.0] - 2025-01-25

### 🏗️ 重構
- 完成專案模組化重構
- 實作服務工廠模式
- 建立 src/srt_translator 套件結構
- 統一配置管理系統

### 📦 構建
- 新增 pyproject.toml
- 設定 uv 套件管理器支援
- 配置 Ruff、Mypy、Pytest

---

## [0.6.0] - 2024-12-15

### ✨ 新增
- Anthropic Claude API 支援
- 提示詞管理系統
- 多種內容類型支援（general、anime、movie、adult）
- 多種翻譯風格支援（standard、literal、localized、specialized）

### 🔧 改進
- 改進錯誤處理機制
- 優化 API 重試邏輯

---

## [0.5.0] - 2024-11-20

### ✨ 新增
- 翻譯快取系統（SQLite）
- 快取統計與管理功能
- 自動快取過期

### 🐛 修復
- 修正提示詞導致字幕翻譯格式不一致的問題

---

## [0.4.0] - 2024-10-15

### ✨ 新增
- OpenAI API 支援
- 批量翻譯功能
- 並發處理支援

### 🔧 改進
- 改進檔案編碼偵測
- 優化翻譯速度

---

## [0.3.0] - 2024-09-10

### ✨ 新增
- GUI 介面（Tkinter）
- 拖放檔案支援
- 進度顯示與控制（暫停/繼續/停止）

### 🔧 改進
- 改進使用者體驗
- 新增檔案衝突處理

---

## [0.2.0] - 2024-08-05

### ✨ 新增
- Ollama 本地模型支援
- 多語言支援
- 配置管理系統

### 🔧 改進
- 改進 SRT 檔案解析
- 新增日誌系統

---

## [0.1.0] - 2024-07-01

### 🎉 初始發布
- 基本 SRT 字幕翻譯功能
- 命令列介面
- 簡單的配置系統

---

## 版本號說明

版本格式：`主版本.次版本.修訂版本`

- **主版本**：不相容的 API 變更
- **次版本**：向下相容的功能新增
- **修訂版本**：向下相容的問題修復

---

**最後更新**：2025-12-29

[Unreleased]: https://github.com/charles1018/srt-subtitle-translator/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v1.0.0
[0.9.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.9.0
[0.8.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.8.0
[0.7.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.7.0
[0.6.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.6.0
[0.5.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.5.0
[0.4.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.4.0
[0.3.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.3.0
[0.2.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.2.0
[0.1.0]: https://github.com/charles1018/srt-subtitle-translator/releases/tag/v0.1.0
