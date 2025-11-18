# SRT Subtitle Translator

[![Python Version](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Tests](https://img.shields.io/badge/tests-515%20passing-brightgreen.svg)](tests/)
[![Code Coverage](https://img.shields.io/badge/coverage-22%25-yellow.svg)](htmlcov/)

基於 Python 的 SRT 字幕檔自動翻譯工具，支援使用 Ollama 本地模型、OpenAI API 或 Anthropic API 進行多語言翻譯。本工具提供批量處理、翻譯記憶快取、多種顯示模式等功能，並配備友善的圖形使用者介面。

## ✨ 功能特點

### 核心功能
- 🌍 **多語言支援**：支援 10+ 種語言（日文、英文、韓文、法文、德文、西班牙文、俄文、繁體中文、簡體中文等）
- 🤖 **多引擎支援**：
  - Ollama 本地 AI 模型
  - OpenAI API (GPT-3.5、GPT-4 等)
  - Anthropic API (Claude 系列模型)
- 📝 **多格式支援**：SRT、VTT、ASS/SSA 字幕格式

### 進階功能
- ⚡ **批量處理**：同時處理多個字幕檔案
- 🔄 **並發翻譯**：可調整並發數，優化翻譯效率
- 💾 **翻譯快取**：自動快取翻譯結果，減少重複 API 呼叫
  - 🆕 **GUI 快取管理**：完整的快取管理界面，支援查看統計資訊和一鍵清除快取
- 🎨 **多種顯示模式**：
  - 僅顯示翻譯
  - 雙語對照
  - 翻譯在上/原文在上
- 🎬 **Netflix 繁體中文字幕風格**：
  - 自動套用 Netflix 繁體中文字幕規範
  - 智慧修正標點符號、引號、數字格式
  - 檢查字符限制（每行最多 16 字符，最多 2 行）
  - 🆕 **智慧自動斷行**：過長字幕自動在標點符號、連接詞或空格處斷行
  - 提供詳細的格式警告和修正統計
  - 可透過 GUI 一鍵啟用/停用
- 🎯 **自訂提示詞**：支援五種內容類型（一般、成人、動畫、電影、英語劇集）和四種翻譯風格
  - 🆕 **英語劇集模式**：專為英語影視作品優化，包含人名保留規則和專業術語映射
- 🖱️ **拖放操作**：支援拖放檔案到介面
- 🔧 **智慧衝突處理**：自動處理檔案名稱衝突（覆蓋/重新命名/跳過）
- 🔍 **自動編碼偵測**：自動偵測字幕檔案編碼

## 📋 系統需求

- **Python**：3.8 或更高版本
- **網路連接**：使用 API 模式時需要
- **API 金鑰**（依使用模式）：
  - OpenAI 模式：需要 OpenAI API 金鑰
  - Anthropic 模式：需要 Anthropic API 金鑰
  - Ollama 模式：需要在本機安裝 [Ollama](https://ollama.ai) 服務

## 🚀 快速開始

### 安裝

#### 方法 1：使用 uv（推薦）

```bash
# 克隆儲存庫
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator

# 使用 uv 安裝依賴
uv sync --all-extras --dev

# 執行程式
uv run srt-translator
```

#### 方法 2：使用 pip

```bash
# 克隆儲存庫
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator

# 安裝依賴
pip install -r requirements.txt

# 執行程式
python -m srt_translator
```

### API 金鑰設定

#### OpenAI API
將您的 API 金鑰放入 `openapi_api_key.txt` 檔案中：

```bash
echo "your-openai-api-key" > openapi_api_key.txt
```

#### Anthropic API
將您的 API 金鑰放入 `anthropic_api_key.txt` 檔案中：

```bash
echo "your-anthropic-api-key" > anthropic_api_key.txt
```

#### Ollama（本地模型）
確保 Ollama 服務正在運行：

```bash
# 安裝 Ollama（參考 https://ollama.ai）
# 啟動 Ollama 服務
ollama serve

# 拉取模型（例如）
ollama pull llama2
```

### 基本使用

1. 啟動應用程式：
   ```bash
   uv run srt-translator
   ```

2. 在圖形介面中：
   - 選擇字幕檔案（可拖放）
   - 設定源語言和目標語言
   - 選擇 AI 引擎和模型
   - 調整並發數和顯示模式
   - 點擊「開始翻譯」

3. 翻譯完成後，檔案會自動儲存在原檔案目錄

## 📚 文檔

- [使用者指南](docs/USER_GUIDE.md) - 詳細使用說明
- [API 文檔](docs/API.md) - 開發者 API 參考
- [開發者指南](docs/DEVELOPMENT.md) - 開發環境設定與貢獻指南
- [變更日誌](CHANGELOG.md) - 版本更新記錄
- [貢獻指南](CONTRIBUTING.md) - 如何為專案做出貢獻

## 🏗️ 專案架構

```
src/srt_translator/
├── core/              # 核心模組
│   ├── config.py      # 配置管理器
│   ├── cache.py       # 翻譯快取管理
│   ├── models.py      # AI 模型管理
│   └── prompt.py      # 提示詞管理
├── translation/       # 翻譯服務
│   ├── client.py      # API 客戶端
│   └── manager.py     # 翻譯流程管理
├── file_handling/     # 檔案處理
│   └── handler.py     # 字幕檔案處理
├── gui/               # GUI 組件
│   └── components.py  # 圖形介面組件
├── services/          # 服務層
│   └── factory.py     # 服務工廠模式
├── utils/             # 工具模組
│   ├── errors.py      # 錯誤定義
│   ├── helpers.py     # 輔助函數
│   └── logging_config.py
└── __main__.py        # 主程式入口
```

### 核心模組說明

| 模組 | 說明 |
|------|------|
| **ConfigManager** | 統一管理應用程式配置，支援多種配置類型 |
| **CacheManager** | 管理翻譯快取，使用 SQLite 儲存翻譯記憶 |
| **ModelManager** | 管理 AI 模型清單，提供模型推薦功能 |
| **PromptManager** | 管理翻譯提示詞，支援多種內容類型和風格 |
| **TranslationClient** | 封裝 API 呼叫，支援多種 AI 引擎 |
| **FileHandler** | 處理字幕檔案的讀取、解析和儲存 |
| **ServiceFactory** | 服務工廠，統一管理所有服務實例 |

## 🛠️ 開發

### 執行測試

```bash
# 執行所有測試
uv run pytest -v

# 執行單元測試
uv run pytest tests/unit -v

# 執行 E2E 測試
uv run pytest tests/e2e -v

# 生成覆蓋率報告
uv run pytest --cov=src/srt_translator --cov-report=html
```

### 程式碼品質檢查

```bash
# 使用 Ruff 檢查程式碼
uv run ruff check

# 自動修復問題
uv run ruff check --fix

# 型別檢查（可選）
uv run mypy src/srt_translator
```

## 📊 測試狀態

本專案擁有完整的測試體系：

- **總測試數**：515 個
- **單元測試**：477 個
- **整合測試**：20 個
- **E2E 測試**：38 個
- **測試通過率**：100%
- **覆蓋率**：22%（E2E 測試覆蓋）

## ⚙️ 配置

所有配置檔案位於 `config/` 目錄：

| 檔案 | 說明 |
|------|------|
| `app_config.json` | 應用程式通用設定 |
| `user_settings.json` | 使用者偏好設定 |
| `prompt_config.json` | 翻譯提示詞設定 |
| `model_config.json` | 模型相關設定 |
| `file_handler_config.json` | 檔案處理設定 |
| `cache_config.json` | 快取系統設定 |

## 🎯 效能優化建議

### 🆕 動態並發控制（自適應）

本工具現已支援**自適應並發控制**，根據 API 回應時間自動調整並發數（範圍 2-10）：

- **API 回應快**（< 0.5 秒）：自動增加並發數，提升翻譯速度
- **API 回應慢**（> 1.5 秒）：自動降低並發數，避免過載
- **平滑調整**：使用指數移動平均（EMA）避免頻繁波動
- **預期效果**：平均翻譯時間減少 25%（4 分鐘 → 3 分鐘）

### 並發數設定（手動模式）

如需手動控制，可根據不同 AI 引擎調整並發數：

- **Ollama**：1-3（視 GPU 資源而定）
- **OpenAI**：3-6（避免觸發速率限制）
- **Anthropic**：5-15（相對寬鬆的速率限制）

### 🆕 快取系統優化

**智慧快取清理機制**：

- ✅ **觸發閾值**：記憶體使用達 120% 才清理（減少不必要的清理）
- ✅ **保留比例**：清理時保留 70% 快取（原 50%）
- ✅ **預期效果**：快取清理次數減少 88%（82 次 → 5-10 次）
- 快取自動儲存翻譯結果
- 相同文本和上下文會直接從快取讀取
- 不同模型的翻譯結果分別快取
- 預設快取有效期：30 天

### 🆕 智慧自動斷行

**Netflix 風格後處理器整合**：

- ✅ **智慧分割**：過長字幕自動在標點符號（逗號、頓號）後斷行
- ✅ **優先位置**：連接詞（和、與、或、但）前後、空格處
- ✅ **自動修正**：確保每行不超過字符限制（預設 16 字符）
- ✅ **預期效果**：過長字幕警告減少 77%（133/200 → <30/200）

## 🤝 貢獻

歡迎貢獻！請參閱 [貢獻指南](CONTRIBUTING.md) 了解詳細資訊。

### 快速貢獻步驟

1. Fork 本儲存庫
2. 建立功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交變更 (`git commit -m 'Add some amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 開啟 Pull Request

## 📝 授權條款

本專案採用 MIT 授權條款 - 詳見 [LICENSE](LICENSE) 檔案。

## 🙏 致謝

- [pysrt](https://github.com/byroot/pysrt) - SRT 字幕解析
- [OpenAI](https://openai.com/) - GPT 系列模型
- [Anthropic](https://www.anthropic.com/) - Claude 系列模型
- [Ollama](https://ollama.ai/) - 本地 LLM 運行平台

## 📮 問題反饋

如果您遇到任何問題或有改進建議，請：

1. 查看 [FAQ](docs/USER_GUIDE.md#faq)
2. 搜尋 [已知問題](https://github.com/charles1018/srt-subtitle-translator/issues)
3. 建立新的 [Issue](https://github.com/charles1018/srt-subtitle-translator/issues/new)

## 🗺️ 未來規劃

- [ ] 支援更多字幕格式
- [ ] 語音識別功能
- [ ] 批量時間軸調整
- [ ] 使用者字典和術語庫
- [ ] Web 介面版本
- [ ] 更多主題和自訂選項
- [ ] 翻譯品質評估
- [ ] 多人協作翻譯

## 📊 專案統計

- **開發開始**：2023
- **當前版本**：1.0.0
- **程式碼行數**：3500+ 行
- **測試行數**：10000+ 行
- **支援語言**：10+ 種

---

**Made with ❤️ by charles1018**
