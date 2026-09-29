SRT Subtitle Translator（Rust 版）
==================================

單一執行檔的字幕翻譯 CLI，支援 llama.cpp（本地）、OpenAI、Google Gemini。
翻譯行為（prompt、採樣參數、後處理、快取鍵）與 Python 版 srt-translator 相同，
兩版可共用同一份設定與翻譯快取。

執行檔
------
  Linux   : srt-translator-rs      （x86_64，glibc 2.28 以上，例如 Ubuntu 20.04+ / Debian 10+）
  Windows : srt-translator-rs.exe  （x86_64，Windows 10 以上，不需另裝執行環境）

工作目錄
--------
設定、快取與日誌都放在「目前工作目錄」底下（與 Python 版相同）：

  config/   設定檔（user_settings.json、model_config.json 等，首次執行自動產生）
  data/     翻譯快取 translation_cache.db、術語表 glossaries/
  logs/     日誌

若要與 Python 版共用設定與快取，請在 Python 版的專案目錄執行本程式；
也可以用環境變數 CONFIG_DIR 指定設定目錄。

API 金鑰
--------
依序讀取環境變數與目前目錄的 .env 檔：

  OPENAI_API_KEY=sk-...
  GOOGLE_API_KEY=...        （或 GEMINI_API_KEY）

llama.cpp 預設連線 http://localhost:8080，可在 config/model_config.json 的
llamacpp_url 修改。

常用指令
--------
  # 日文字幕 → 繁體中文（本地 llama.cpp）
  srt-translator-rs translate movie.srt -s 日文 -t 繁體中文

  # 英文字幕，OpenAI，批次模式 + Netflix 風格
  srt-translator-rs translate ep01.srt -s 英文 -t 繁體中文 -p openai --structure-text --netflix-style

  # 整個目錄、雙語對照、輸出到另一個目錄
  srt-translator-rs translate ./subs -s 英文 -t 繁體中文 -d 雙語對照 -o ./out
  （-o 的目錄必須已存在，否則會輸出到輸入檔旁邊）

  srt-translator-rs models            列出可用模型
  srt-translator-rs glossary list     術語表管理
  srt-translator-rs cache --stats     快取統計
  srt-translator-rs --help            完整說明（每個子命令也有 --help）

授權
----
本程式以 MIT 授權（LICENSE）。執行檔內嵌 OpenCC 繁簡轉換字典（Apache License 2.0），
來源與授權全文見 THIRD-PARTY/。

與 Python 版的差異
------------------
  - 沒有圖形介面（GUI 開發中）
  - -o/--output-dir 只作用於該次執行，不會寫回設定檔
  - 新建的文字檔一律使用 LF 換行（讀取既有 SRT 時保留原換行）
