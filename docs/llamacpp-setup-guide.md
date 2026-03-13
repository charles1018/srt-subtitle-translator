# llama.cpp 本地模型設定指南

本指南說明如何使用 llama.cpp 的 `llama-server` 搭配 SRT Subtitle Translator 進行字幕翻譯。相較於 Ollama，llama.cpp 提供更直接的 GPU 控制、更低的包裝層開銷，以及對進階量化格式（如 IQ4_NL）的完整支援。

---

## 目錄

- [前置需求](#前置需求)
- [取得 llama.cpp](#取得-llamacpp)
- [啟動 llama-server](#啟動-llama-server)
- [設定翻譯工具](#設定翻譯工具)
- [效能調校建議](#效能調校建議)
- [常見問題與解決方案](#常見問題與解決方案)

---

## 前置需求

- Linux / Windows / macOS 系統
- 已下載的 GGUF 格式量化模型檔案（如 `Qwen3.5-9B-UD-Q8_K_XL.gguf`）
- 足夠的 VRAM 或系統記憶體（依模型大小與量化等級而定）
- 本專案已安裝 `openai` Python 套件（預設已包含）

### VRAM 需求參考

| 模型大小 | Q4_K_M | Q8_0 | IQ4_NL |
|----------|--------|------|--------|
| 7B       | ~4.5 GB | ~8 GB | ~3.8 GB |
| 9B       | ~5.5 GB | ~12 GB | ~5 GB |
| 14B      | ~8.5 GB | ~16 GB | ~7.5 GB |
| 27B      | ~16 GB | ~30 GB | ~14 GB |

> VRAM 不足時，llama-server 會自動將部分層放到 CPU 執行（混合推理），速度較慢但仍可運作。

---

## 取得 llama.cpp

### 方式一：下載預建二進位檔（推薦）

到 [llama.cpp Releases](https://github.com/ggml-org/llama.cpp/releases) 下載對應平台的壓縮包：

- **Linux + NVIDIA GPU**：`llama-*-bin-ubuntu-x64-cuda-*` 或 `llama-*-bin-ubuntu-x64-vulkan-*`
- **Linux + AMD GPU**：`llama-*-bin-ubuntu-x64-vulkan-*`
- **Windows + NVIDIA GPU**：`llama-*-bin-win-cuda-*` 或 `llama-*-bin-win-vulkan-*`
- **macOS (Apple Silicon)**：`llama-*-bin-macos-arm64.zip`

解壓縮到任意目錄，例如：

```bash
# Linux
mkdir -p ~/dev/llama-bin
unzip llama-*-bin-ubuntu-x64-vulkan-*.zip -d ~/dev/llama-bin

# 確認 llama-server 可執行
ls ~/dev/llama-bin/llama-server
```

### 方式二：從原始碼編譯

```bash
git clone https://github.com/ggml-org/llama.cpp
cd llama.cpp

# CUDA（NVIDIA GPU）
cmake -B build -DGGML_CUDA=ON
cmake --build build --config Release -j

# Vulkan（跨平台 GPU）
cmake -B build -DGGML_VULKAN=ON
cmake --build build --config Release -j

# Metal（macOS Apple Silicon）
cmake -B build -DGGML_METAL=ON
cmake --build build --config Release -j
```

編譯完成後，執行檔位於 `build/bin/llama-server`。

---

## 啟動 llama-server

### 基本啟動

```bash
# Linux（使用預建二進位，需設定 LD_LIBRARY_PATH）
LD_LIBRARY_PATH=~/dev/llama-bin ~/dev/llama-bin/llama-server \
    -m ~/dev/model/your-model.gguf \
    --port 8080

# macOS / Windows 或從原始碼編譯時，不需要 LD_LIBRARY_PATH
llama-server -m ~/dev/model/your-model.gguf --port 8080
```

llama-server 會自動偵測 GPU 並決定最佳的層分配。

### 推薦啟動參數

```bash
LD_LIBRARY_PATH=~/dev/llama-bin ~/dev/llama-bin/llama-server \
    -m ~/dev/model/Qwen3.5-9B-UD-Q8_K_XL.gguf \
    --port 8080 \
    -c 4096 \
    --parallel 2 \
    --reasoning-budget 0
```

| 參數 | 說明 | 建議值 |
|------|------|--------|
| `-m` | GGUF 模型檔案路徑 | 必填 |
| `--port` | HTTP 服務埠號 | `8080`（預設） |
| `-c` | Context 長度（token 數） | `2048`~`4096`（字幕翻譯不需要太長） |
| `-ngl` | 放到 GPU 的層數 | 省略讓 llama-server 自動決定 |
| `--parallel` | 同時處理的請求數 | `1`~`4`（依 VRAM 餘量） |
| `--reasoning-budget 0` | 關閉思考模式 | 翻譯任務建議關閉 |
| `--flash-attn on` | 啟用 Flash Attention | 可降低記憶體使用 |
| `--host 0.0.0.0` | 監聽所有網路介面 | 僅在需要遠端存取時使用 |

### 驗證伺服器狀態

```bash
# 檢查健康狀態
curl http://localhost:8080/health
# 預期回應: {"status":"ok"}

# 查看載入的模型
curl http://localhost:8080/v1/models
```

### 快速測試翻譯

```bash
curl -s http://localhost:8080/v1/chat/completions \
    -H "Content-Type: application/json" \
    -d '{
        "model": "test",
        "messages": [
            {"role": "system", "content": "Translate to Traditional Chinese (Taiwan). Output only the translation."},
            {"role": "user", "content": "Hello, how are you?"}
        ],
        "temperature": 0.4,
        "max_tokens": 96,
        "chat_template_kwargs": {"enable_thinking": false}
    }'
```

如果看到翻譯結果（如 `你好，你還好嗎？`），表示伺服器運作正常。

---

## 設定翻譯工具

### 方式一：使用 GUI

1. 啟動翻譯工具：`uv run srt-translator`
2. 在「LLM 類型」下拉選單中選擇 **llamacpp**
3. 模型列表會自動從 llama-server 取得目前載入的模型
4. 選擇模型後即可開始翻譯

### 方式二：使用 CLI

```bash
uv run python -m srt_translator.cli translate input.srt \
    -s 日文 \
    -t 繁體中文 \
    -p llamacpp \
    -m "your-model.gguf" \
    -c 1
```

### 方式三：修改設定檔

編輯 `config/model_config.json`，設定 llama-server 的連線位址：

```json
{
    "llamacpp_url": "http://localhost:8080"
}
```

如果 llama-server 運行在其他主機或埠號（例如 `http://192.168.1.100:8080`），修改此值即可。

### 不需要 API Key

llama.cpp 是本地推理，不需要任何 API 金鑰。本專案會自動處理認證（傳送 `sk-no-key-required`）。

---

## 效能調校建議

### GPU 層分配

llama-server 預設會自動偵測 VRAM 並決定放多少層到 GPU。如果想手動控制：

```bash
# 全部放 GPU（需要足夠 VRAM）
llama-server -m model.gguf -ngl 999

# 只放一部分到 GPU（VRAM 不足時）
llama-server -m model.gguf -ngl 20

# 完全使用 CPU（無 GPU 或 GPU 被其他程式佔用）
llama-server -m model.gguf -ngl 0
```

### 思考模式與翻譯速度

Qwen3.5 等模型預設啟用思考模式（`<think>` 標籤），會大幅增加 token 消耗和延遲。本專案已在程式碼中自動關閉思考模式，但建議在啟動 llama-server 時也加上 `--reasoning-budget 0` 做雙重保險：

```bash
llama-server -m model.gguf --reasoning-budget 0
```

### 量化格式選擇

| 量化格式 | 品質 | 大小 | 速度 | 適用場景 |
|----------|------|------|------|----------|
| Q8_0 / Q8_K_XL | 最高 | 最大 | 較慢 | VRAM 充足、追求品質 |
| Q4_K_M | 良好 | 中等 | 快 | 通用推薦 |
| IQ4_NL | 良好 | 較小 | 快 | VRAM 有限但要求品質 |
| Q4_K_S | 可接受 | 較小 | 最快 | VRAM 非常有限 |

### llama.cpp vs Ollama 效能差異

| 項目 | llama.cpp | Ollama |
|------|-----------|--------|
| 架構 | 直接執行 C++ 推理 | Go 包裝層 + llama.cpp |
| 單一請求速度 | 基準 | 慢約 9% |
| 併發效能 | 優（維持穩定） | 差（高併發時溢出到 CPU） |
| GPU 記憶體管理 | 精確控制 | 自動管理（較鬆散） |
| 量化格式支援 | 完整（含 IQ 系列） | 部分 |
| 設定彈性 | 高（每個參數可調） | 中（透過 Modelfile） |
| 使用便利性 | 需手動啟動伺服器 | 自動管理、systemd 整合 |

---

## 常見問題與解決方案

### 1. llama-server 啟動時 VRAM 不足

**錯誤訊息：**
```
ggml_vulkan: Device memory allocation of size XXXXXXXX failed.
ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory
```

**解決方法：**

- 減少 GPU 層數：加上 `-ngl 15`（或更少）讓更多層在 CPU 上執行
- 減少 context 長度：`-c 2048` 或 `-c 1024`
- 減少並行數：`--parallel 1`
- 使用更小的量化格式（Q4_K_M 或 IQ4_NL）
- 不指定 `-ngl`，讓 llama-server 自動 fit

```bash
# 讓 llama-server 自動決定最佳配置
llama-server -m model.gguf -c 2048 --parallel 1
```

### 2. 翻譯超時

**現象：** 翻譯請求在等待很久後失敗。

**原因：** CPU-only 模式下，大型模型推理較慢（可能只有 ~5 tok/s）。

**解決方法：**

- 本專案對 llamacpp 已設定 600 秒（10 分鐘）的超時，大多數情況足夠
- 確認有足夠的 GPU layers 被使用（檢查 llama-server 啟動日誌中的 `offloaded X/Y layers to GPU`）
- 嘗試使用更小的量化模型

### 3. 翻譯結果包含 `</think>` 或其他標籤殘留

**現象：** 翻譯結果中出現 `</think>`、`<|im_start|>` 等標記。

**解決方法：** 本專案已內建自動清理機制，會移除這些殘留標籤。如果問題持續：

- 啟動 llama-server 時加上 `--reasoning-budget 0`
- 確認使用最新版本的本專案

### 4. 模型列表顯示「llama-server (未連線)」

**原因：** llama-server 未在運行，或連線位址不正確。

**解決方法：**

1. 確認 llama-server 已啟動：`curl http://localhost:8080/health`
2. 確認埠號正確：預設是 `8080`
3. 如果使用非預設埠號，修改 `config/model_config.json` 中的 `llamacpp_url`

### 5. llama-server 在 Linux 上找不到共享函式庫

**錯誤訊息：**
```
error while loading shared libraries: libggml.so: cannot open shared object file
```

**解決方法：** 設定 `LD_LIBRARY_PATH` 指向解壓縮的目錄：

```bash
LD_LIBRARY_PATH=~/dev/llama-bin ~/dev/llama-bin/llama-server -m model.gguf
```

或寫成 shell 腳本方便日後使用：

```bash
#!/bin/bash
# ~/start-llama-server.sh
export LD_LIBRARY_PATH=~/dev/llama-bin
~/dev/llama-bin/llama-server \
    -m ~/dev/model/Qwen3.5-9B-UD-Q8_K_XL.gguf \
    --port 8080 \
    -c 4096 \
    --parallel 2 \
    --reasoning-budget 0
```

### 6. 多 GPU 系統指定使用哪張顯卡

**Vulkan 後端：**
```bash
# 使用第二張 GPU（索引從 0 開始）
llama-server -m model.gguf --gpu-device 1
```

**CUDA 後端：**
```bash
# 使用第二張 GPU
CUDA_VISIBLE_DEVICES=1 llama-server -m model.gguf -ngl 999
```

---

## 附錄：實用指令速查

| 用途 | 指令 |
|------|------|
| 啟動伺服器 | `llama-server -m model.gguf --port 8080` |
| 檢查伺服器狀態 | `curl http://localhost:8080/health` |
| 查看載入的模型 | `curl http://localhost:8080/v1/models` |
| 關閉思考模式啟動 | `llama-server -m model.gguf --reasoning-budget 0` |
| 自動 GPU fit | 不指定 `-ngl`，llama-server 自動決定 |
| 手動指定 GPU 層數 | `llama-server -m model.gguf -ngl 20` |
| 完全 CPU 模式 | `llama-server -m model.gguf -ngl 0` |
| 停止伺服器 | `Ctrl+C` 或 `pkill -f llama-server` |

---

## 附錄：與 Ollama 的使用場景比較

| 場景 | 推薦方案 |
|------|----------|
| 第一次使用本地模型 | Ollama（安裝簡單、自動管理） |
| 追求最大推理速度 | llama.cpp（少一層 Go 包裝、Flash Attention） |
| 使用 IQ4_NL 等進階量化 | llama.cpp（Ollama 不支援部分量化格式） |
| 需要精確控制 GPU 記憶體 | llama.cpp（-ngl、-c 等精確參數） |
| 有 DGX / 5090 等高階硬體 | llama.cpp（直接控制，無中間層開銷） |
| 需要 systemd 自動啟動 | Ollama（內建服務管理） |
| 多人共用一台推理伺服器 | llama.cpp（--parallel 參數、無額外記憶體開銷） |
