# SRT Subtitle Translator

基於 Python 3.12 的 SRT 字幕檔自動翻譯工具，支援使用 Ollama 本地模型或 OpenAI API 進行多語言翻譯。本工具提供多種語言翻譯、批次處理、翻譯記憶緩存功能，並配備友好的圖形用戶界面。特別優化了日文字幕翻譯為繁體中文的功能。

## 功能特點

- 支持 SRT 格式字幕檔的自動翻譯
- 雙重翻譯引擎：支持 Ollama 本地 AI 模型和 OpenAI API
- 多語言支持（日文、英文、繁體中文）
- 批次處理多個檔案
- 拖放操作界面
- 翻譯記憶緩存功能，減少重複 API 呼叫
- 自訂翻譯提示詞
- 可調整字幕顯示模式（僅顯示翻譯、翻譯在原文上方、原文在翻譯上方）
- 可控制並行翻譯數量，優化效能

## 系統需求

- Python 3.12 或更高版本
- 使用 OpenAI 模式需要 OpenAI API 密鑰（存放於 openapi_api_key.txt）
- 使用 Ollama 模式需要在本機安裝 Ollama 服務 (http://localhost:11434)
- 網路連接

## 安裝指南

1. 克隆或下載本儲存庫

```bash
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator
```

2. 安裝必要的套件

```bash
pip install -r requirements.txt
```

3. 設定 OpenAI API 密鑰

將您的 OpenAI API 密鑰放入 `openapi_api_key.txt` 檔案中，或者在首次執行程式時通過介面設定。

## 使用方法

### 圖形介面模式

執行主程式以啟動圖形介面：

```bash
python srt-translator.py
```

在介面中：
1. 選擇要翻譯的 SRT 檔案（可通過「選擇 SRT 檔案」按鈕或直接拖放檔案到列表中）
2. 選擇源語言和目標語言
3. 選擇 LLM 類型（Ollama 本地模型或 OpenAI API）
4. 選擇使用的模型（會根據 LLM 類型自動列出可用模型）
5. 設定並行請求數量（建議值：Ollama 模式 4-8，OpenAI 模式 3-6）
6. 選擇字幕顯示模式：
   - target_only：僅顯示翻譯結果
   - target_above_source：翻譯在原文上方
   - source_above_target：原文在翻譯上方
7. 點擊「開始翻譯」按鈕

翻譯過程中可以：
- 暫停/繼續翻譯
- 停止翻譯
- 通過「編輯 Prompt」按鈕自訂翻譯提示詞

### 注意：目前版本不支援命令列模式

## 模組結構

- `srt-translator.py`: 主腳本，應用程式入口
- `cache.py`: 管理翻譯緩存的 SQLite 數據庫，提高重複翻譯效率
- `translation_client.py`: 翻譯客戶端模組，封裝 Ollama 和 OpenAI API 調用
- `translation_manager.py`: 管理翻譯流程，控制並行翻譯任務
- `model_manager.py`: 管理 AI 模型清單和選擇
- `gui_components.py`: GUI 界面組件，提供拖放功能和用戶交互
- `file_handler.py`: 處理檔案選擇、衝突解決和路徑管理
- `prompt.py`: 管理翻譯提示詞，針對不同 LLM 提供優化的提示

## 注意事項

- Ollama 模式需要先在本機安裝 Ollama 服務，並預先下載相關模型
- OpenAI 模式會消耗 API 配額，請確保您的帳戶有足夠的額度
- 首次使用請先將您的 OpenAI API 密鑰放入 `openapi_api_key.txt` 檔案中
- 翻譯速度取決於：
  - 選擇的 LLM 類型和模型
  - 網路連接速度和 API 響應時間
  - 並行請求數量設定
  - 字幕檔大小
- 大型字幕檔的翻譯可能需要較長時間，您可以隨時暫停並稍後繼續
- 預設翻譯提示詞針對日文到繁體中文翻譯進行了優化

## 授權條款

MIT 授權

## 問題反饋

如果您遇到任何問題或有改進建議，請在 GitHub 儲存庫中提出 Issue。

## 緩存系統

本程式使用 SQLite 數據庫實現翻譯緩存功能：
- 相同文本及上下文的翻譯結果會被緩存下來，避免重複調用 API
- 緩存系統記錄模型名稱，使不同模型的翻譯結果互不影響
- 預設緩存數據保存在 `translation_cache.db` 文件中

## 效能優化

- Ollama 模式下使用異步並行請求，可大幅提高翻譯效率
- OpenAI 模式實現了速率限制管理，避免超過 API 限制
- 批量翻譯處理針對不同 LLM 類型進行了優化
- 自動調整批次大小以適應不同規模的字幕檔

## 錯誤處理

- 程式會自動重試失敗的 API 請求
- 翻譯過程記錄到 `srt_translator.log` 日誌檔案
- 檔案衝突處理支持覆蓋、重命名或跳過選項

## 可定制性

您可以修改 `prompt_config.json` 中的提示詞以適應不同的翻譯場景和內容類型。通過「編輯 Prompt」按鈕修改後會自動保存。
