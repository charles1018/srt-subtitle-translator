# SRT 字幕翻譯器



# SRT 字幕翻譯器

這是一個基於 Python 的 SRT 字幕翻譯工具，使用 Ollama API 進行翻譯，支持並行處理、自定義翻譯 Prompt 和檔案拖放功能。項目採用模組化設計，便於維護和擴展。

## 功能

- 批量翻譯 `.srt` 字幕檔案。
- 支持自定義翻譯 Prompt，適應不同語氣和在地化需求。
- 可並行處理多個字幕，提升翻譯效率。
- 提供進度條和狀態顯示，支援暫停/停止翻譯。
- 支持檔案拖放（需安裝 `tkinterdnd2`）。
- 緩存翻譯結果，減少重複請求。

## 檔案結構

srt_translator/
├── srt-translator.py # 主腳本，應用程式入口
├── cache.py # 緩存管理模組
├── ollama_client.py # 翻譯客戶端模組
├── translation_manager.py # 翻譯流程管理模組
├── model_manager.py # 模型管理模組
├── gui_components.py # GUI 組件模組
├── file_handler.py # 檔案處理模組
├── prompt.py # Prompt 管理模組
├── requirements.txt # 依賴清單
├── README.md # 本文件



## 安裝步驟

### 前置條件

- **Python 版本**：3.8 或更高版本。
- **Ollama 服務**：需在本地運行 Ollama（默認地址 `http://localhost:11434`），並確保模型（如 `gemma2:9b`）已下載。
- **操作系統**：Windows、Linux 或 macOS。

### 步驟

1. **克隆或下載項目**：

git clone https://github.com/charles1018/srt-subtitle-translator 
cd srt_translator

或直接下載並解壓縮項目檔案。

2. **設置虛擬環境（可選但推薦）**：

python -m venv venv
source venv/bin/activate # Linux/macOS
venv\Scripts\activate # Windows

3. **安裝依賴**：

pip install -r requirements.txt

- 若不需要拖放功能，可手動移除 `tkinterdnd2` 的安裝。
4. **啟動 Ollama 服務**：
- 確保 Ollama 已安裝並運行：

ollama run gemma2:9b

- 檢查服務是否在 `http://localhost:11434` 可訪問。
5. **運行程式**：

python srt-translator.py

## 依賴

- **必要依賴**：
- `pysrt`：處理 SRT 字幕檔案。
- `aiohttp`：非同步 HTTP 請求。
- `backoff`：API 請求重試機制。
- **可選依賴**：
- `tkinterdnd2`：啟用檔案拖放功能。
- **內建依賴**（Python 標準庫）：
- `tkinter`：GUI 界面。
- `sqlite3`：緩存數據庫。
- `json`、`urllib.request`：模型列表獲取。
- `threading`、`asyncio`：線程和非同步管理。

詳見 `requirements.txt`。

## 使用方法

1. **啟動應用**：
- 運行 `python srt-translator.py`，顯示 GUI 界面。
2. **添加檔案**：
- 點擊「選擇 SRT 檔案」按鈕，或拖放 `.srt` 檔案到列表中（需 `tkinterdnd2`）。
3. **設置參數**：
- 選擇原文語言（預設：日文）和目標語言（預設：繁體中文）。
- 選擇模型（預設從 Ollama API 獲取）。
- 設置並行請求數（建議 1-8，預設 6）。
4. **編輯 Prompt**（可選）：
- 點擊「編輯 Prompt」，自定義翻譯規則，保存後生效。
5. **開始翻譯**：
- 點擊「開始翻譯」，觀察進度條和狀態更新。
- 可點擊「暫停」/「繼續」或「停止」控制翻譯。
6. **結果**：
- 翻譯完成後，檔案保存為 `<原文件名>.zh_tw.srt`（或根據目標語言變化）。
- 若檔案衝突，會提示選擇覆蓋、重新命名或跳過。

## 注意事項

- **Ollama 配置**：確保 Ollama 服務運行，且模型支援繁體中文翻譯。
- **記憶體使用**：並行請求數過高可能導致記憶體壓力，建議根據系統資源調整。
- **日誌**：運行時會輸出詳細日誌，便於除錯。

## 未來擴展

- **支援新格式**：修改 `file_handler.py` 和 `translation_manager.py` 以支持 `.ass` 等格式。
- **多模型支持**：擴展 `model_manager.py`，整合其他翻譯 API。
- **批量 Prompt**：在 `gui_components.py` 中添加批量設定功能。

## 維護

若遇到問題，請檢查日誌輸出並提交以下資訊：

- Python 版本
- 依賴版本（`pip list`）
- Ollama 服務狀態
- 完整錯誤訊息

## 注意事項

- 確保 Ollama 服務運行中（http://localhost:11434）
- 建議使用 gemma2:9b 模型
- 並行請求數建議設為 5
- 翻譯大量字幕時請耐心等待

## 授權協議

MIT License