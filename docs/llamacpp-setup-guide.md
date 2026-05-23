# llama.cpp 本地模型設定指南

本指南說明如何讓 SRT Subtitle Translator 透過 `llama-server` 使用本地 GGUF 模型翻譯字幕。本 repo 的 `llamacpp` provider 直接走 OpenAI 相容 `/v1/chat/completions` API，並對特定模型家族（Hunyuan-MT、Qwen3.x、Gemma 4）套用專用 prompt 與 sampling 策略，無需額外整合工作。

generic llama.cpp 編譯、跨平台支援等內容請參考 [上游官方說明](https://github.com/ggml-org/llama.cpp)，本指南只記錄與本專案搭配時實際會用到的部分。

---

## 1. 前置需求

- 已下載並可執行的 `llama-server`（CUDA / Vulkan / Metal 任一後端均可）
- GGUF 量化模型檔案
- 本專案已安裝 `openai` 套件（`uv sync --all-extras --dev` 預設會裝）

---

## 2. 本 repo 已內建專用支援的模型家族

`TranslationClient._detect_model_family` 會用模型名稱關鍵字決定走哪一條 prompt / sampling 路徑。**模型檔名或 `-m` 參數必須包含該關鍵字**，否則只會走 default profile，失去家族專屬最佳化（如日文名字保護、reasoning 控制、JSON schema 跳過等）。

| 家族 key | 名稱關鍵字 | 推薦模型範例 | 備註 |
|---|---|---|---|
| `hunyuan-mt` | `hunyuan-mt` / `hy-mt` | `Hy-MT2-7B-Q4_K_M`、`Hy-MT2-1.8B-Q8_0` | 翻譯專用模型，跳過 JSON schema、走精簡 prompt |
| `qwen3.5-ud` | `qwen3.5` + UD 變體關鍵字 | `Qwen3.5-9B-UD-Q8_K_XL`、`Qwen3.5-9B-Uncensored-...` | 含日文名字保護、thinking=off |
| `qwen3.5` | `qwen3.5` / `qwen35` | `Qwen3.5-9B-...` | 同上但無 UD 強化 |
| `qwen3.6` / `qwen3.6-ud` | `qwen3.6` / `qwen36` | `Qwen3.6-...` | 跳過 JSON schema（schema 模式會劣化） |
| `qwen3` | `qwen3` | `Qwen3-14B-Q5_K_M` | 標準 Transformer Qwen3 |
| `gemma4` | `gemma-4` | `gemma-4-E4B-it-UD-Q8_K_XL` | `reasoning: off` + 不同 thinking 控制 |
| `llama` / `gemma` / `mistral` | 同名 | – | 走 default profile |

本機開發環境下 `D:\dev\model\` 已備有 `Hy-MT2-7B-Q4_K_M.gguf`、`Hy-MT2-1.8B-Q8_0.gguf`、`Qwen3.5-9B-UD-Q8_K_XL.gguf` 等檔案，可直接使用（詳見專案根目錄 `CLAUDE.md`）。

---

## 3. 啟動 llama-server

### Windows（CUDA build，本機推薦）

llama.cpp 已加入系統 `PATH`，直接呼叫：

```powershell
llama-server.exe `
    -m D:\dev\model\Hy-MT2-7B-Q4_K_M.gguf `
    --port 8080 `
    --jinja `
    -c 2048 `
    --parallel 1
```

或 Git Bash：

```bash
llama-server.exe -m /d/dev/model/Hy-MT2-7B-Q4_K_M.gguf --port 8080 --jinja -c 2048 --parallel 1
```

### Linux（CUDA build）

```bash
GGML_CUDA_NO_VMM=1 LD_LIBRARY_PATH=~/dev/llama-bin \
    ~/dev/llama-bin/llama-server \
    -m ~/dev/model/Hy-MT2-7B-Q4_K_M.gguf \
    --port 8080 --jinja -c 2048 --parallel 1
```

`GGML_CUDA_NO_VMM=1` 是 Linux + CUDA build **必須**的環境變數，否則 CUDA VMM 預分配機制會在模型載入前就佔光 VRAM，導致 `-ngl auto` 算出 0 GPU 層、整個跑回 CPU。

### 共通核心參數

| 參數 | 說明 | 一般建議 |
|---|---|---|
| `-m` | GGUF 路徑 | 必填 |
| `--port` | 服務埠 | `8080`（本 repo 預設） |
| `--jinja` | 啟用 GGUF 內嵌 chat template | **必設**（多數模型需要） |
| `-c` | Context 長度 | `2048`（單 slot 起跳），多 slot 請 ×slot 數 |
| `--parallel N` | server 端 slot 數 | 1（穩定）；多 slot 見 §5 |
| `--reasoning-format deepseek` | 將 thinking 內容分離 | Qwen3/3.5 系列必設 |
| `--reasoning-budget 0` | 強制不思考 | Qwen3.5 強烈建議；client 端也會送 per-request 同設定 |

### 家族專屬建議

**Hunyuan-MT2**（翻譯專用、無 thinking）— 基本參數即可：
```bash
llama-server -m Hy-MT2-7B-Q4_K_M.gguf --jinja -c 2048 --parallel 1
```

**Qwen3.5 / Qwen3.5-UD**（thinking-capable，必須關閉）：
```bash
llama-server -m Qwen3.5-9B-UD-Q8_K_XL.gguf --jinja -c 2048 --parallel 1 \
    --reasoning-format deepseek --reasoning-budget 0
```

**Gemma 4**（非 DeepSeek thinking 格式）：
```bash
llama-server -m gemma-4-E4B-it-UD-Q8_K_XL.gguf --jinja -c 2048 --parallel 1 \
    --reasoning off --reasoning-format none --temp 1.0 --top-p 0.95 --top-k 64
```

### 驗證

```bash
curl http://localhost:8080/health     # 預期: {"status":"ok"}
curl http://localhost:8080/v1/models  # 確認載入的模型
curl http://localhost:8080/slots      # 確認 slot 數
```

---

## 4. 與翻譯工具搭配使用

### CLI

```bash
uv run srt-translator translate input.srt \
    -s 日文 -t 繁體中文 \
    --provider llamacpp \
    -m Hy-MT2-7B-Q4_K_M
```

關鍵點：
- `--provider llamacpp` 對應 OpenAI 相容 API client
- `-m` 名稱要含家族關鍵字（見 §2 表格），不需與 GGUF 檔名完全相同
- `-c / --concurrency` 預設 3。client 端會再被 server `total_slots` 上限制約 — 例如 server 跑 `--parallel 1` 時，client 自動限為 1
- `--content-type adult / anime / movie / english_drama` 觸發不同 prompt 模板
- 輸出預設與來源檔同目錄（`-o` 可覆蓋）；跨磁碟也已支援（C: ↔ D:）

### GUI

`uv run srt-translator` → 在「LLM 類型」選 **llamacpp** → 模型清單會從 `llama-server` 自動抓取。

### 連線位址設定

預設連 `http://localhost:8080`。若 server 在別處（含 LAN 或非預設 port），編輯 `config/model_config.json`：

```json
{
    "llamacpp_url": "http://192.168.1.50:8080"
}
```

無需 API key —— client 會送出 placeholder `sk-no-key-required`。

---

## 5. 並發與效能調校

### Server slots 與 CLI concurrency 的對應

client 並發數 = `min(--concurrency, server total_slots, adaptive_controller_max=10)`。所以調並發要同時調兩邊：

| 場景 | server `--parallel` | CLI `-c` | 適用 |
|---|---|---|---|
| 穩定優先 | 1 | 1-3 | 字幕翻譯、低延遲、預測性高 |
| 吞吐優先 | 4 | 4-8 | 大量檔案批次、VRAM 充足 |

### 實測結果（466 條日文字幕、Windows + CUDA 13.1 + RTX 級顯卡，2026-05-24）

| 模型 | server slots | CLI 並發 | 耗時 |
|---|---|---|---|
| Hy-MT2-7B-Q4 | 1 | 1 | 87s |
| Hy-MT2-7B-Q4 | 4 | 4 | 65s |
| Hy-MT2-1.8B-Q8 | 4 | 4 | 29s |

7B 模型在此硬體上於 3 並發就近乎飽和 GPU；繼續加並發收益遞減。1.8B 速度約 3x，但翻譯品質明顯下降（角色代詞、抽象語義易出錯），通常仍建議用 7B。

### CUDA 專屬：KV cache 量化

```bash
-fa on -ctk q8_0 -ctv q8_0
```

可降低 ~47% 的 KV cache VRAM 用量、品質幾乎無感。**Vulkan / Metal build 不支援**。

### 量化檔選擇參考

| 量化 | 品質 | 適用 |
|---|---|---|
| Q8_0 / Q8_K_XL | 最高 | VRAM 充足 |
| Q4_K_M / IQ4_NL | 良好 | 通用推薦 |
| Q4_K_S | 可接受 | VRAM 緊張 |

---

## 6. 常見問題

### Linux + CUDA：模型全跑在 CPU、`offloaded 0/N layers to GPU`

加 `GGML_CUDA_NO_VMM=1`（見 §3）。VMM 預分配機制會誤吃 VRAM，使 `-ngl auto` 算不出空間。

### 翻譯結果出現 `</think>`、`<|im_start|>` 等殘留標記

通常是 Qwen3.5 等 thinking-capable 模型沒關掉思考：
1. server 端加 `--reasoning-format deepseek --reasoning-budget 0`
2. 用最新版 client（已自動送 `reasoning_budget_tokens: 0`）

Hunyuan-MT2 不會有這問題（無 thinking 模式）。

### 翻譯逾時

CPU-only 模式下大模型可能 < 5 tok/s。本 repo 對 llamacpp 已設 600 秒逾時。檢查：
- llama-server 啟動 log 是否有 `offloaded N/M layers to GPU` 且 N > 0
- 換更小或更高量化效率的模型

### CLI 顯示「上限: 1」即使 server `--parallel 4`

CLI 仍用預設 `-c 3`，但 server 報的 `total_slots` 才是真正瓶頸 — 反之亦然。要拉並發到 4，兩邊都要：server `--parallel 4` + CLI `-c 4`。

### 「llama-server (未連線)」/ GUI 模型列表為空

```bash
curl http://localhost:8080/health  # 應回 {"status":"ok"}
```
若 server 在別處，記得改 `config/model_config.json` 的 `llamacpp_url`。

### 模型家族專屬功能沒生效（如 Qwen3.5 的日文名字保護）

`-m` 名稱沒包含家族關鍵字。檢查 §2 表格，必要時加上識別字串（不需與檔名一致）：

```bash
# 不會觸發 qwen3.5-ud 路徑
-m local-model

# 會觸發
-m Qwen3.5-9B-UD
```

---

## 7. 速查

| 用途 | 指令 |
|---|---|
| 健康檢查 | `curl http://localhost:8080/health` |
| 模型列表 | `curl http://localhost:8080/v1/models` |
| Slot 狀態 | `curl http://localhost:8080/slots` |
| 停止 server | `Ctrl+C` 或 Windows: `taskkill /F /IM llama-server.exe` |
| Windows 推薦啟動（Hy-MT2-7B） | `llama-server.exe -m D:\dev\model\Hy-MT2-7B-Q4_K_M.gguf --jinja -c 2048 --parallel 1` |
| Linux 推薦啟動（CUDA + Hy-MT2-7B） | `GGML_CUDA_NO_VMM=1 LD_LIBRARY_PATH=~/dev/llama-bin ~/dev/llama-bin/llama-server -m model.gguf --jinja -c 2048 --parallel 1` |
