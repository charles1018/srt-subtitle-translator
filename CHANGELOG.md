# 變更日誌

本檔案記錄專案的所有重要變更。

格式基於 [Keep a Changelog](https://keepachangelog.com/zh-TW/1.0.0/)，
版本號遵循 [Semantic Versioning](https://semver.org/lang/zh-TW/)。

## [Unreleased]

### ✨ 新增

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

**最後更新**：2025-01-28

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
