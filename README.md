# SRT Subtitle Translator

基於 Python 的 SRT 字幕檔自動翻譯工具，支援使用 Ollama 本地模型或 OpenAI API 進行多語言翻譯。本工具提供多種語言翻譯、批次處理、翻譯記憶緩存功能，並配備友好的圖形用戶界面。特別優化了日文字幕翻譯為繁體中文的功能。

## 功能特點

- 支持 SRT、VTT、ASS/SSA 格式字幕檔的自動翻譯
- 多引擎支援：
  - Ollama 本地 AI 模型
  - OpenAI API (GPT-3.5、GPT-4 等)
  - Anthropic API (Claude 系列模型)
- 多語言支持（日文、英文、韓文、法文、德文、西班牙文、俄文、繁體中文、簡體中文）
- 批次處理多個檔案
- 拖放操作界面
- 翻譯記憶緩存功能，減少重複 API 呼叫
- 自訂翻譯提示詞，支援四種內容類型和翻譯風格
- 可調整字幕顯示模式（僅顯示翻譯、翻譯在原文上方、原文在翻譯上方、雙語對照）
- 可控制並行翻譯數量，優化效能
- 檔案衝突處理（覆蓋、重新命名、跳過）
- 自動偵測檔案編碼

## 系統需求

- Python 3.8 或更高版本
- 使用 OpenAI 模式需要 OpenAI API 密鑰（存放於 openapi_api_key.txt）
- 使用 Anthropic 模式需要 Anthropic API 密鑰（存放於 anthropic_api_key.txt）
- 使用 Ollama 模式需要在本機安裝 Ollama 服務 (http://localhost:11434)
- 網路連接

## 安裝指南

1. 克隆或下載本儲存庫

```bash
git clone https://github.com/yourusername/srt-subtitle-translator.git
cd srt-subtitle-translator
```

2. 安裝必要的套件

```bash
pip install -r requirements.txt
```

3. 設定 API 密鑰（若需要）

將您的 OpenAI API 密鑰放入 `openapi_api_key.txt` 檔案中，或者在首次執行程式時通過介面設定。
如果要使用 Anthropic API，請將密鑰放入 `anthropic_api_key.txt` 檔案中。

## 使用方法

### 圖形介面模式

執行主程式以啟動圖形介面：

```bash
python srt-translator.py
```

在介面中：
1. 選擇要翻譯的字幕檔案（可通過「選擇檔案」按鈕或直接拖放檔案到列表中）
2. 選擇源語言和目標語言
3. 選擇 LLM 類型（Ollama 本地模型、OpenAI API 或 Anthropic API）
4. 選擇使用的模型（會根據 LLM 類型自動列出可用模型）
5. 設定並行請求數量（推薦值）：
   - Ollama 模式：1-3 (視 GPU 資源而定)
   - OpenAI 模式：3-6
   - Anthropic 模式：5-15
6. 選擇字幕顯示模式：
   - 雙語對照：同時顯示原文和翻譯
   - 僅顯示翻譯：只顯示翻譯結果
   - 翻譯在上：翻譯在原文上方
   - 原文在上：原文在翻譯上方
7. 點擊「開始翻譯」按鈕

翻譯過程中可以：
- 暫停/繼續翻譯
- 停止翻譯
- 通過「編輯 Prompt」按鈕自訂翻譯提示詞

## 模組結構

- `srt-translator.py`: 主腳本，應用程式入口
- `config_manager.py`: 管理應用配置，實現設定的讀取和保存
- `cache.py`: 管理翻譯緩存的 SQLite 數據庫，提高重複翻譯效率
- `translation_client.py`: 翻譯客戶端模組，封裝 Ollama、OpenAI 和 Anthropic API 調用
- `translation_manager.py`: 管理翻譯流程，控制並行翻譯任務
- `model_manager.py`: 管理 AI 模型清單和選擇
- `gui_components.py`: GUI 界面組件，提供拖放功能和用戶交互
- `file_handler.py`: 處理檔案選擇、衝突解決和路徑管理
- `prompt.py`: 管理翻譯提示詞，針對不同 LLM 和內容類型提供優化的提示
- `utils.py`: 公用工具和函數

## 自訂提示詞

本程式支援四種內容類型的提示詞：
- `general`: 一般內容翻譯
- `adult`: 成人內容翻譯
- `anime`: 動畫內容翻譯
- `movie`: 電影內容翻譯

同時支援四種翻譯風格：
- `standard`: 標準翻譯 - 平衡準確性和自然度
- `literal`: 直譯 - 更忠於原文的字面意思
- `localized`: 本地化翻譯 - 更適合台灣繁體中文文化
- `specialized`: 專業翻譯 - 保留專業術語

您可以在程式界面中通過「編輯 Prompt」按鈕自訂提示詞，修改後會自動保存。

## 緩存系統

本程式使用 SQLite 數據庫實現翻譯緩存功能：
- 相同文本及上下文的翻譯結果會被緩存下來，避免重複調用 API
- 緩存系統記錄模型名稱，使不同模型的翻譯結果互不影響
- 預設緩存數據保存在 `data/translation_cache.db` 文件中

## 效能優化

- Ollama 模式下使用異步並行請求，可大幅提高翻譯效率
- OpenAI 和 Anthropic 模式實現了速率限制管理，避免超過 API 限制
- 批量翻譯處理針對不同 LLM 類型進行了優化
- 自動調整批次大小以適應不同規模的字幕檔

## 其他功能

- 檔案編碼自動偵測
- 檔案格式的自動轉換（SRT/VTT）
- 檔案衝突處理（覆蓋、重新命名、跳過）
- 翻譯進度和剩餘時間估計
- 自動記憶上次使用的目錄
- 錯誤重試機制，提高穩定性

## 配置文件

所有設定都保存在 `config/` 目錄下：
- `app_config.json`: 應用程式通用設定
- `user_settings.json`: 用戶設定（語言、模型等）
- `prompt_config.json`: 翻譯提示詞設定
- `model_config.json`: 模型相關設定
- `file_handler_config.json`: 檔案處理相關設定
- `cache_config.json`: 緩存系統設定

## 錯誤處理

- 程式會自動重試失敗的 API 請求
- 翻譯過程記錄到 `logs/` 目錄下的日誌檔案
- 使用模型回退策略，當一個模型失敗時嘗試使用替代模型

## 授權條款

MIT 授權

## 問題反饋

如果您遇到任何問題或有改進建議，請在 GitHub 儲存庫中提出 Issue。

## 未來計劃

- 支援更多字幕格式
- 語音識別功能，從視頻直接生成字幕
- 批量字幕時間軸調整功能
- 用戶字典和術語庫
- 更多主題和界面自訂選項
