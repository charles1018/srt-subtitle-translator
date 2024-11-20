# SRT 字幕翻譯器

這是一個使用 Python 和 tkinter 開發的 SRT 字幕翻譯工具。它可以批量翻譯 SRT 格式的字幕文件，使用本地運行的 Ollama AI 模型進行翻譯。

## 功能

- 批量選擇和翻譯 SRT 文件
- 支持多種語言翻譯
- 可選擇不同的 AI 模型
- 可調整並行請求數量
- 實時顯示翻譯進度

## 安裝

1. 確保您的系統已安裝 Python 3.7 或更高版本。

2. 克隆此儲存庫或下載源代碼。

3. 安裝所需的依賴項：

   ```bash
   pip install -r requirements.txt
   ```

4. 確保您已經安裝並運行了 Ollama，並且有可用的 AI 模型。

## 使用方法

### 使用源代碼運行

1. 打開命令提示符或終端機，導航到項目目錄。

2. 運行以下命令：

   ```bash
   python main.py
   ```

3. 在打開的圖形界面中，選擇 SRT 文件，設置翻譯選項，然後點擊"開始翻譯"。

### 編譯成可執行文件（.exe）

如果您想將程式編譯成 Windows 可執行文件（.exe），請按照以下步驟操作：

1. 確保您已經安裝了 PyInstaller。如果沒有，可以使用以下命令安裝：

   ```bash
   pip install pyinstaller
   ```

2. 打開命令提示符或終端機，導航到項目目錄。

3. 運行以下命令來創建單個可執行文件：

   ```bash
   pyinstaller --onefile --windowed main.py
   ```

   這個命令會在 `dist` 目錄下創建一個名為 `main.exe` 的可執行文件。

4. 如果您想要自定義圖標，可以使用 `--icon` 選項：

   ```bash
   pyinstaller --onefile --windowed --icon=path/to/your/icon.ico main.py
   ```

   請將 `path/to/your/icon.ico` 替換為您的圖標文件路徑。

5. 編譯完成後，您可以在 `dist` 目錄中找到 `main.exe` 文件。

6. 將 `main.exe` 文件複製到您想要的位置。請注意，該可執行文件需要能夠訪問到運行中的 Ollama 服務。

### 使用編譯後的可執行文件運行（僅限 Windows）

1. 找到編譯後的 `main.exe` 文件。

2. 雙擊運行 `main.exe`。

3. 在打開的圖形界面中，選擇 SRT 文件，設置翻譯選項，然後點擊"開始翻譯"。

## 注意事項

- 請確保 Ollama 服務正在運行，且設置了正確的模型。
- 翻譯速度取決於您的電腦性能和選擇的 AI 模型。
- 翻譯結果將保存在原 SRT 文件的相同目錄下，文件名會添加語言後綴。
- 如果使用編譯後的 .exe 文件，確保您的防毒軟件不會誤判它為威脅。
- 編譯後的 .exe 文件可能會比源代碼大很多，這是正常的，因為它包含了運行所需的所有依賴。

## 故障排除

如果您在運行編譯後的 .exe 文件時遇到問題：

1. 確保您的系統已安裝所有必要的 Visual C++ 可再發行套件。
2. 嘗試在命令提示符中運行 .exe 文件，以查看是否有錯誤消息輸出。
3. 如果仍然有問題，可以嘗試使用源代碼直接運行程序。

## 許可證

本項目採用 MIT 許可證。詳情請見 [LICENSE](LICENSE) 文件。