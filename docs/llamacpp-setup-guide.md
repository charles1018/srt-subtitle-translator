# llama.cpp 本地模型設定指南

本指南說明如何使用 llama.cpp 的 `llama-server` 搭配 SRT Subtitle Translator 進行字幕翻譯。相較於 Ollama，llama.cpp 提供更直接的 GPU 控制、更低的包裝層開銷，以及對進階量化格式（如 IQ4_NL）的完整支援。

---

## 目錄

- [前置需求](#前置需求)
- [取得 llama.cpp](#取得-llamacpp)
- [啟動 llama-server](#啟動-llama-server)
- [CUDA 版本最佳化](#cuda-版本最佳化)
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
    --jinja \
    -c 2048 \
    --parallel 1 \
    --reasoning-format deepseek \
    --cache-ram 4096
```

> **關於 `--reasoning-budget 0`：** 本專案 client 端已透過 per-request `reasoning_budget_tokens: 0`
> 控制，經實測確認有效（token 使用量與 server 端設定一致），server 啟動時不再需要此參數。
> 若你的 llama-server 版本較舊或希望做雙重保險，仍可加上 `--reasoning-budget 0`。

| 參數 | 說明 | 建議值 |
|------|------|--------|
| `-m` | GGUF 模型檔案路徑 | 必填 |
| `--port` | HTTP 服務埠號 | `8080`（預設） |
| `--jinja` | 啟用 GGUF 內嵌 chat template | 必須開啟（Qwen3.5 需要） |
| `-c` | Context 長度（token 數） | `2048`（最低建議值；qwen3.5-ud adult prompt 含上下文約需 1200 tokens，加上 max_tokens 輸出需預留空間） |
| `-ngl` | 放到 GPU 的層數 | 省略讓 llama-server 自動決定 |
| `--parallel` | 同時處理的 request slot 數 | `1`（穩定優先；多 slot 需足夠 VRAM） |
| `--reasoning-format deepseek` | 將思考內容分離到 `reasoning_content` 欄位 | 必須設定（確保思考內容不混入翻譯結果） |
| `--cache-ram N` | Prompt cache 大小上限（MiB） | `4096`（8 GB VRAM 機器建議值；預設 8192） |
| `--flash-attn on` | 啟用 Flash Attention | 可降低記憶體使用（預設 auto） |
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
        "temperature": 1.0,
        "top_p": 1.0,
        "top_k": 20,
        "min_p": 0.0,
        "max_tokens": 256,
        "presence_penalty": 2.0,
        "reasoning_format": "deepseek",
        "chat_template_kwargs": {"enable_thinking": false}
    }'
```

如果看到翻譯結果（如 `你好，你還好嗎？`），表示伺服器運作正常。

---

## CUDA 版本最佳化

本節說明使用 NVIDIA GPU 搭配 CUDA build 時的專屬最佳化參數與注意事項。

### 關鍵環境變數：`GGML_CUDA_NO_VMM=1`

**這是 Linux + CUDA build 最重要的設定，直接影響是否能有效利用 GPU。**

CUDA build 在初始化時預設使用 VMM（Virtual Memory Management）預分配記憶體池，此行為會在模型載入前就佔用大量 VRAM（實測約 6.4 GB），導致 `-ngl auto` 計算可用空間時幾乎什麼層都放不進 GPU（回報 0 GPU 層），模型實際跑在 CPU 上。

設定 `GGML_CUDA_NO_VMM=1` 可禁用此預分配，讓 VRAM 真正用於模型推理。

```bash
# 必須加在啟動指令前
GGML_CUDA_NO_VMM=1 LD_LIBRARY_PATH=~/dev/llama-bin-ubuntu-cuda \
    ~/dev/llama-bin-ubuntu-cuda/llama-server ...
```

**未設定 vs 設定後的差異（RTX 3070 Laptop 8GB，Qwen3.5-9B Q8_K_XL）：**

| | 未設定 GGML_CUDA_NO_VMM | 設定後 |
|--|--|--|
| GPU 可用 VRAM（啟動時） | ~958 MiB | ~7534 MiB |
| 實際 GPU 層數 | 0/33（全 CPU） | 14/33 |
| 實用性 | 等同 CPU 模式 | 正常 GPU 加速 |

### KV Cache 量化（CUDA 專屬）

CUDA build 支援量化 KV cache（`-ctk`、`-ctv`），可將每個 slot 的 KV cache VRAM 使用量減半，讓有限 VRAM 能容納更多 GPU 層或更多並行 slot。**Vulkan build 不支援此功能。**

```bash
-ctk q8_0 -ctv q8_0   # q8_0：使用量減半，品質幾乎無損（推薦）
-ctk q4_0 -ctv q4_0   # q4_0：使用量降至 1/4，但可能影響品質
```

實測 KV cache VRAM 比較（Qwen3.5-9B，3 slots，4096 ctx，8 transformer 層）：

| KV cache 精度 | 大小 |
|---|---|
| f16（Vulkan 預設） | 144 MiB |
| q8_0（CUDA 最佳化） | 76.5 MiB（節省 47%） |

### CUDA 版 推薦啟動指令

```bash
GGML_CUDA_NO_VMM=1 \
LD_LIBRARY_PATH=~/dev/llama-bin-ubuntu-cuda \
~/dev/llama-bin-ubuntu-cuda/llama-server \
    -m ~/dev/model/Qwen3.5-9B-UD-Q8_K_XL.gguf \
    -ngl auto \
    -fa on \
    -ctk q8_0 \
    -ctv q8_0 \
    --jinja \
    -c 4096 \
    -np 3 \
    --no-context-shift \
    --chat-template-kwargs '{"enable_thinking":false}' \
    --host 127.0.0.1 \
    --port 8080
```

| 參數 | 說明 |
|------|------|
| `GGML_CUDA_NO_VMM=1` | 禁用 CUDA VMM 預分配，讓 VRAM 可實際用於模型層（**必設**） |
| `-ngl auto` | 自動最大化 GPU 層數（依剩餘 VRAM 決定） |
| `-fa on` | Flash Attention，CUDA 上效率優於 Vulkan 實作 |
| `-ctk q8_0 -ctv q8_0` | KV cache 量化，節省 47% KV cache VRAM（**CUDA 專屬**） |
| `-np 3` | 3 個並行 slot，對應 CLI 預設並行數 |
| `--no-context-shift` | 禁止上下文滑動，確保翻譯品質 |

### CUDA vs Vulkan 實測比較

**測試環境：** RTX 3070 Laptop（8GB VRAM），Qwen3.5-9B-UD-Q8_K_XL.gguf（13GB），30 條日文成人字幕，並行 3，2026-03-17

| 指標 | CUDA（最佳化） | Vulkan | 差距 |
|------|------|--------|------|
| 總耗時 | **81 秒** | **123 秒** | CUDA 快 **1.52x** |
| 平均每請求 | 5.62 秒 | 8.51 秒 | CUDA 快 1.51x |
| 最快請求 | 2.88 秒 | 3.78 秒 | |
| 最慢請求 | 12.88 秒 | 17.51 秒 | |
| KV cache VRAM | 76.5 MiB（q8_0） | 144 MiB（f16） | CUDA 省 47% |
| GPU 層數 | 14/33 | 14/33 | 相同 |

兩者 GPU 層數相同，速度差異主因：CUDA 的 Flash Attention kernel 效率更高，加上 KV cache 量化降低記憶體頻寬壓力。

### 注意：Qwen3.5 Hybrid SSM 架構

Qwen3.5 採用 **Hybrid SSM + Transformer 架構**（Gated Delta Net 遞迴層），並非純 Transformer，架構組成如下：

- 32 個 SSM（Gated Delta Net）遞迴層
- 8 個 Transformer 注意力層
- KV cache 僅服務 8 個 Transformer 層（因此 KV cache 很小）

啟動 log 中會出現以下訊息，屬正常現象：

```
sched_reserve: layer 0 is assigned to device CPU but the fused Gated Delta Net tensor
               is assigned to device CUDA0 (usually due to missing support)
```

此訊息表示 SSM 層的計算後端分配，不代表模型跑在 CPU；GPU 層數請以
`load_tensors: offloaded 14/33 layers to GPU` 為準。

---

## 設定翻譯工具

### 方式一：使用 GUI

1. 啟動翻譯工具：`uv run srt-translator`
2. 在「LLM 類型」下拉選單中選擇 **llamacpp**
3. 模型列表會自動從 llama-server 取得目前載入的模型
4. 選擇模型後即可開始翻譯

### 方式二：使用 CLI

```bash
uv run srt-translator translate input.srt \
    -s 日文 \
    -t 繁體中文 \
    -p llamacpp \
    -m Qwen3.5-9B-UD \
    --content-type adult
```

> **重要：** 使用 `--model`（`-m`）指定模型名稱時，名稱必須包含能讓程式辨識模型家族的關鍵字
> （如 `Qwen3.5`），否則會使用預設名稱 `local-model`，無法觸發該模型家族的專用功能
> （qwen3.5-ud 的日文名字保護、專用 sampling 參數、短語快取策略等）。
> 名稱不需要與實際 GGUF 檔名完全一致，只要包含模型家族辨識字串即可。

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

Qwen3.5 等模型在思考模式下會大幅增加 token 消耗和延遲。本專案透過三層機制確保翻譯時不啟用思考：

1. **Server 端**：`--reasoning-format deepseek`（必須設定，將思考內容分離到 `reasoning_content` 欄位）
2. **Client 端 per-request**：`reasoning_budget_tokens: 0`（經實測確認有效，限制思考 token 為 0）
3. **Chat template**：`chat_template_kwargs.enable_thinking=false`（從模板層面關閉思考）

```bash
# server 端必須設定 reasoning-format
llama-server -m model.gguf --reasoning-format deepseek
```

如果你改用思考模式做一般問答或推理任務，再另外切回 thinking 相關參數；字幕翻譯預設不建議啟用。

### Qwen3.5 與量化模型採樣建議

依 Qwen3.5 官方對非思考文字任務的建議，本專案 Qwen3.5 profile 使用以下參數：

- `temperature=1.0`（Qwen3.5 官方推薦；Qwen3 為 0.7）
- `top_p=1.0`（Qwen3.5 官方推薦，等於停用 nucleus sampling；Qwen3 為 0.8）
- `top_k=20`
- `min_p=0.0`
- `presence_penalty=2.0`（Qwen3.5 官方推薦；Qwen3 為 1.5）

> **注意**：Qwen3.5 的架構（Gated DeltaNet 混合注意力）與 Qwen3（標準 Transformer）完全不同，因此官方推薦的採樣參數差異很大。本專案會根據模型名稱自動偵測 Qwen3 或 Qwen3.5 並套用對應的 profile。

本專案在 `llamacpp` runtime 還會同時固定 `cache_prompt=true`、`seed=42`，且用 `response_format=json_object` 將輸出限制為 JSON 格式。若你使用其他 OpenAI 相容客戶端，也建議比照加入。

### 穩定模式與吞吐模式

- 穩定模式（推薦）：`--parallel 1 --no-cont-batching`
- 吞吐模式：`--parallel 2` 或更高，並保留 continuous batching

前者更適合字幕翻譯這種短句、高頻、需要可預期輸出的工作流；後者則適合多人共用或大量背景處理。

> **注意：** 使用 `--parallel 2` 以上時，每個 slot 都需要獨立的 KV cache 記憶體。在 VRAM 有限（≤ 8 GB）的消費型顯卡上，多 slot 會導致 per-request 延遲大幅上升，吞吐提升有限甚至品質退化。建議搭配 `-ctk q8_0 -ctv q8_0`（KV cache 量化）使用，但此功能僅 CUDA build 支援，Vulkan build 不可用。

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

### 1. CUDA build：模型全跑在 CPU，GPU 層數為 0

**現象：** 使用 CUDA build 啟動 llama-server，但 log 顯示 `offloaded 0/N layers to GPU`，nvidia-smi 顯示 VRAM 幾乎全被佔用（~6-7 GB），且翻譯速度與純 CPU 相當。

**原因：** CUDA VMM（Virtual Memory Management）預分配機制在模型載入前就佔用大量 VRAM，使 `-ngl auto` 算出沒有空間可用。

**解決方法：** 啟動時設定環境變數 `GGML_CUDA_NO_VMM=1`：

```bash
GGML_CUDA_NO_VMM=1 LD_LIBRARY_PATH=~/dev/llama-bin-ubuntu-cuda \
    ~/dev/llama-bin-ubuntu-cuda/llama-server -m model.gguf -ngl auto ...
```

**確認方法：** 啟動後查看 log，應看到 `offloaded N/M layers to GPU`（N > 0）。

### 2. llama-server 啟動時 VRAM 不足

**錯誤訊息：**
```
ggml_vulkan: Device memory allocation of size XXXXXXXX failed.
ggml_vulkan: vk::Device::allocateMemory: ErrorOutOfDeviceMemory
```

**解決方法：**

- 減少 GPU 層數：加上 `-ngl 15`（或更少）讓更多層在 CPU 上執行
- 減少 context 長度：`-c 2048`（字幕翻譯最低建議值）
- 減少並行數：`--parallel 1`
- 使用更小的量化格式（Q4_K_M 或 IQ4_NL）
- 不指定 `-ngl`，讓 llama-server 自動 fit

```bash
# 讓 llama-server 自動決定最佳配置
llama-server -m model.gguf -c 2048 --parallel 1 --reasoning-format deepseek
```

### 3. 翻譯超時

**現象：** 翻譯請求在等待很久後失敗。

**原因：** CPU-only 模式下，大型模型推理較慢（可能只有 ~5 tok/s）。

**解決方法：**

- 本專案對 llamacpp 已設定 600 秒（10 分鐘）的超時，大多數情況足夠
- 確認有足夠的 GPU layers 被使用（檢查 llama-server 啟動日誌中的 `offloaded X/Y layers to GPU`）
- 嘗試使用更小的量化模型

### 4. 翻譯結果包含 `</think>` 或其他標籤殘留

**現象：** 翻譯結果中出現 `</think>`、`<|im_start|>` 等標記。

**解決方法：** 本專案已內建自動清理機制，會移除這些殘留標籤。如果問題持續：

- 確認使用最新版本的本專案（client 端已自動送出 `reasoning_budget_tokens: 0`）
- 啟動 llama-server 時加上 `--reasoning-format deepseek`

### 5. 模型列表顯示「llama-server (未連線)」

**原因：** llama-server 未在運行，或連線位址不正確。

**解決方法：**

1. 確認 llama-server 已啟動：`curl http://localhost:8080/health`
2. 確認埠號正確：預設是 `8080`
3. 如果使用非預設埠號，修改 `config/model_config.json` 中的 `llamacpp_url`

### 6. llama-server 在 Linux 上找不到共享函式庫

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
    --jinja \
    -c 2048 \
    --parallel 1 \
    --reasoning-format deepseek \
    --cache-ram 4096
```

### 7. 多 GPU 系統指定使用哪張顯卡

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
| Vulkan 推薦啟動 | `llama-server -m model.gguf --jinja -c 4096 -np 3 -ngl auto -fa on --no-context-shift` |
| CUDA 推薦啟動 | `GGML_CUDA_NO_VMM=1 llama-server -m model.gguf --jinja -c 4096 -np 3 -ngl auto -fa on -ctk q8_0 -ctv q8_0 --no-context-shift` |
| 檢查伺服器狀態 | `curl http://localhost:8080/health` |
| 查看載入的模型 | `curl http://localhost:8080/v1/models` |
| 確認 GPU 層數 | 看啟動 log：`offloaded N/M layers to GPU` |
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
