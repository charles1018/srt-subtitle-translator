# Ollama 本地模型設定指南

本指南說明如何在 Linux 環境下設定 Ollama，並搭配 SRT Subtitle Translator 使用本地 GGUF 模型進行字幕翻譯。

---

## 目錄

- [前置需求](#前置需求)
- [安裝 Ollama](#安裝-ollama)
- [匯入本地 GGUF 模型](#匯入本地-gguf-模型)
- [設定翻譯工具](#設定翻譯工具)
- [常見問題與解決方案](#常見問題與解決方案)

---

## 前置需求

- Linux 系統（本指南以 Linux Mint / Ubuntu 為例）
- 已下載的 GGUF 格式模型檔案
- 足夠的磁碟空間（模型大小 + 約 10% 額外空間）

## 安裝 Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

安裝完成後，Ollama 會自動以 systemd 服務的方式啟動。驗證服務狀態：

```bash
sudo systemctl status ollama
```

看到 `Active: active (running)` 即表示正常運行。

## 匯入本地 GGUF 模型

### 步驟一：建立 Modelfile

在任意位置建立一個 `Modelfile` 文字檔案，內容如下：

```dockerfile
FROM /path/to/your-model.gguf
```

將路徑替換為你的 GGUF 模型實際路徑，例如：

```dockerfile
FROM /home/user/models/Qwen3.5-9B-Q8_0.gguf
```

#### 進階：設定 Chat Template

如果匯入後模型的翻譯結果混亂（例如重複輸出、無法理解指令），很可能是缺少正確的 Chat Template。不同模型家族需要對應的 template 格式：

**Qwen3.5 系列（本專案推薦設定）：**

```dockerfile
FROM /path/to/qwen3.5-model.gguf

TEMPLATE """{{- if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
<think>

</think>

"""

PARAMETER stop <|im_start|>
PARAMETER stop <|im_end|>
PARAMETER temperature 0.7
PARAMETER top_p 0.8
PARAMETER top_k 20
PARAMETER min_p 0.0
PARAMETER num_predict 256
```

這個 template 會預先填入空的 `<think>...</think>` 區塊，讓自訂匯入的 Qwen3.5 GGUF 模型更穩定地直接輸出翻譯內容，而不是先吐出推理過程。

> 補充：本專案 runtime 也會傳送 `think: false`，並清理殘留的 `<think>` 與 ChatML assistant 標記；但對自訂 GGUF 匯入模型來說，仍建議在 `Modelfile` 端就先處理好。

**Qwen / Qwen3 系列（一般 ChatML 格式）：**

```dockerfile
FROM /path/to/qwen-model.gguf

TEMPLATE """{{- if .System }}<|im_start|>system
{{ .System }}<|im_end|>
{{ end }}<|im_start|>user
{{ .Prompt }}<|im_end|>
<|im_start|>assistant
{{ .Response }}<|im_end|>
"""

PARAMETER stop <|im_start|>
PARAMETER stop <|im_end|>
PARAMETER temperature 0.1
PARAMETER num_predict 256
```

**Llama 系列：**

```dockerfile
FROM /path/to/llama-model.gguf

TEMPLATE """<|begin_of_text|>{{- if .System }}<|start_header_id|>system<|end_header_id|>

{{ .System }}<|eot_id|>{{ end }}<|start_header_id|>user<|end_header_id|>

{{ .Prompt }}<|eot_id|><|start_header_id|>assistant<|end_header_id|>

{{ .Response }}<|eot_id|>"""

PARAMETER stop <|eot_id|>
PARAMETER temperature 0.1
PARAMETER num_predict 256
```

**Gemma 系列：**

```dockerfile
FROM /path/to/gemma-model.gguf

TEMPLATE """<start_of_turn>user
{{ if .System }}{{ .System }}

{{ end }}{{ .Prompt }}<end_of_turn>
<start_of_turn>model
{{ .Response }}<end_of_turn>
"""

PARAMETER stop <start_of_turn>
PARAMETER stop <end_of_turn>
PARAMETER temperature 0.1
PARAMETER num_predict 256
```

### 步驟二：建立模型

```bash
ollama create 模型名稱 -f Modelfile
```

例如：

```bash
ollama create qwen3.5-uncensored -f Modelfile
```

匯入過程中會顯示進度條，完成後驗證：

```bash
ollama list
```

應顯示剛匯入的模型名稱。

### 步驟三：測試模型

```bash
ollama run qwen3.5-uncensored "請將以下日文翻譯成繁體中文：こんにちは"
```

如果能正確回應繁體中文翻譯，即表示模型運作正常。

如果仍出現明顯的 `<think>` 區塊、重複輸出，或長段推理文字，通常表示 `Modelfile` template 未正確套用，建議重新檢查後執行：

```bash
ollama rm qwen3.5-uncensored
ollama create qwen3.5-uncensored -f Modelfile
```

## 設定翻譯工具

編輯專案中的 `config/model_config.json`：

```json
{
    "ollama_url": "http://localhost:11434",
    "default_ollama_model": "qwen3.5-uncensored"
}
```

- `ollama_url`：Ollama 服務的 API 位址，本機使用 `http://localhost:11434`
- `default_ollama_model`：填入你在 `ollama create` 時指定的模型名稱

設定完成後啟動翻譯工具：

```bash
uv run srt-translator
```

在 GUI 中選擇 Ollama 作為翻譯引擎，模型列表中應能看到你匯入的模型。

### Qwen3.5 使用注意事項

- 目前本專案會自動為偵測到的 Ollama Qwen3.5 模型套用專屬採樣參數：`temperature=0.7`、`top_p=0.8`、`top_k=20`、`min_p=0.0`
- 若 Ollama 回傳殘留的 `<think>` 或 `<|im_start|>assistant` 標記，程式會在翻譯結果寫回字幕前自動清理
- 由於目前 Ollama 對 Qwen3.5 仍有已知並行限制，批次翻譯時本專案會自動將該模型的並發數限制為 `1`
- 模型列表偵測會讀取 Ollama `/api/tags` 的 `details` 欄位，因此像 `HauhauCS/Qwen3.5-9B-Uncensored-HauhauCS-Aggressive` 這類自訂名稱也能被辨識為 Qwen3.5 家族

---

## 常見問題與解決方案

### 1. 匯入模型時磁碟空間不足

**錯誤訊息：**
```
Error: write /usr/share/ollama/.ollama/models/blobs/sha256-...: no space left on device
```

**原因：** Ollama 預設將模型儲存在根分區 `/usr/share/ollama/.ollama/models/`，而根分區空間有限。

**解決方法：** 將 Ollama 模型目錄指向空間充足的分區（如 `/home`）：

```bash
# 1. 建立新的模型目錄
sudo mkdir -p /home/user/ollama-models

# 2. 設定目錄擁有者為 ollama 使用者
sudo chown ollama:ollama /home/user/ollama-models

# 3. 建立 systemd override 設定
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf << 'EOF'
[Service]
Environment="OLLAMA_MODELS=/home/user/ollama-models"
EOF

# 4. 重新載入並重啟服務
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

### 2. Ollama 服務啟動失敗：permission denied

**錯誤訊息（透過 `sudo journalctl -u ollama -n 20` 查看）：**
```
Error: mkdir /home/user/...: permission denied: ensure path elements are traversable
```

**原因：** Ollama 服務以 `ollama` 系統使用者身份執行，需要對模型目錄路徑上的**每一層目錄**都有穿越（execute）權限。

**解決方法：**

```bash
# 讓路徑上每層目錄都可被 ollama 使用者穿越
sudo chmod o+x /home/user /home/user/子目錄 /home/user/子目錄/ollama-models

# 確保模型目錄本身歸 ollama 所有
sudo chown ollama:ollama /home/user/子目錄/ollama-models

# 重啟服務
sudo systemctl restart ollama
```

驗證服務是否正常：

```bash
sudo systemctl status ollama
# 應顯示 Active: active (running)
```

### 3. 無法連線到 Ollama 伺服器

**錯誤訊息：**
```
Error: could not connect to ollama server, run 'ollama serve' to start it
```

**解決方法：**

```bash
# 檢查服務狀態
sudo systemctl status ollama

# 如果服務未啟動
sudo systemctl start ollama

# 如果服務啟動失敗，查看詳細日誌
sudo journalctl -u ollama --no-pager -n 20
```

### 4. 翻譯結果混亂（重複輸出、不理解指令）

**現象：** 模型回傳大量不相關的文字、重複內容，或沒有按照指令翻譯。

**原因：** 從 GGUF 匯入時，Ollama 可能無法自動偵測正確的 Chat Template，導致 system prompt 和 user message 沒有被正確傳遞給模型。

**診斷方法：**

```bash
ollama show 模型名稱 --modelfile
```

如果看到 `TEMPLATE {{ .Prompt }}` 這樣過於簡單的 template，就是問題所在。

**解決方法：** 用正確的 template 重新建立模型（參考[進階：設定 Chat Template](#進階設定-chat-template)），然後重新匯入：

```bash
ollama rm 模型名稱
ollama create 模型名稱 -f Modelfile
```

### 5. 首次翻譯超時

**現象：** 第一次翻譯請求耗時 30 秒以上並超時失敗，之後的請求恢復正常。

**原因：** 大型模型（如 9GB+）首次執行時需要載入到記憶體中，這個過程較耗時。

**解決方法：**

- 翻譯前先手動暖機模型：
  ```bash
  ollama run 模型名稱 "test"
  ```
- 或在 Modelfile 中增加 `keep_alive` 參數，讓模型保持載入狀態：
  ```dockerfile
  PARAMETER keep_alive 30m
  ```

### 6. 模型列表中看不到匯入的模型

**解決方法：**

1. 確認模型已匯入：`ollama list`
2. 確認 `config/model_config.json` 中的 `ollama_url` 是 `http://localhost:11434`（而非其他主機名稱）
3. 重啟翻譯工具

---

## 附錄：實用指令速查

| 用途 | 指令 |
|------|------|
| 查看已安裝的模型 | `ollama list` |
| 查看模型詳細資訊 | `ollama show 模型名稱 --modelfile` |
| 測試模型 | `ollama run 模型名稱 "你好"` |
| 刪除模型 | `ollama rm 模型名稱` |
| 查看服務狀態 | `sudo systemctl status ollama` |
| 查看服務日誌 | `sudo journalctl -u ollama --no-pager -n 30` |
| 重啟服務 | `sudo systemctl restart ollama` |
