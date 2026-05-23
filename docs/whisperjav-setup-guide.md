# WhisperJAV 字幕轉錄上游工具設定指南

本指南說明如何安裝與使用 [WhisperJAV](https://github.com/meizhong986/WhisperJAV) — 為日文成人字幕（JAV）轉錄專門設計的開源 pipeline。本工具是 SRT Subtitle Translator 的**上游**配套：負責把 `.mp4` 影片轉成 `.srt`，再由本 repo 的翻譯流水線把 `.srt` 翻成繁體中文。

## 為什麼需要這個

通用 Whisper 對 JAV 場景有顯著的轉錄品質劣化：

- **低訊噪比與大量非語言發聲（NVV）**：喘息、嬌喘、呻吟具備類似日文音節的頻譜特徵，會觸發 Whisper 把無意義音頻轉成幻覺文字
- **長片段觸發 attention collapse**：120 分鐘級的影片含大量「曖昧音訊」段落，Whisper 會進入幻覺迴圈

實證：本 repo `data/benchmark-2026-05-23-ipzz810/` 用 IPZZ-810 全片（466 條字幕、127 分鐘）測試後發現，預設 Whisper Balanced 模式產出 ≥12 處「日文語言上不可能正確的字串」（如 `童貞のマヴァ`、`冷房をガンガンナイフで食べる`、`水塗ってさ`）。改用 WhisperJAV anime-whisper + Qwen3-ASR Ensemble 模式後這些字串全部消除，女主角名「ミツリ」也首次穩定識別。

## 路徑佔位符約定

以下指令使用佔位符代替個人路徑，實際使用時請替換或設成環境變數：

| 佔位符 | 意義 | 範例 |
|---|---|---|
| `<WHISPERJAV_BIN>` | WhisperJAV 執行檔絕對路徑 | Linux: `~/tools/WhisperJAV/.venv/bin/whisperjav`<br>Windows: `C:\Users\<USER>\AppData\Local\WhisperJAV\Scripts\whisperjav.exe` |
| `<INPUT_VIDEO>` | 輸入影片絕對路徑 | `~/videos/sample.mp4` / `C:\Videos\sample.mp4` |
| `<OUTPUT_DIR>` | 輸出 SRT 資料夾 | `~/srt-out/` / `C:\Videos\srt-out\` |
| `<LLAMACPP_BIN_DIR>` | llama.cpp 預編譯目錄 | 參見本 repo `CLAUDE.md` |
| `<MODEL_DIR>` | GGUF 模型目錄 | 參見本 repo `CLAUDE.md` |

## 安裝步驟（Linux + CUDA）

### 1. 取得原始碼

clone 到固定位置（例如 `~/tools/WhisperJAV/`），後續以 `<WHISPERJAV_DIR>` 表示：

```bash
git clone https://github.com/meizhong986/WhisperJAV.git <WHISPERJAV_DIR>
cd <WHISPERJAV_DIR>
```

### 2. 安裝系統依賴

`pyaudio` 需要 `portaudio` 標頭檔才能編譯；`soundfile` 在 Linux 需要 `libsndfile`：

```bash
sudo apt install -y portaudio19-dev libsndfile1
```

### 3. 跑安裝腳本

WhisperJAV 用 `uv` 管理 Python 環境，安裝腳本 `install.py` 會自動偵測 GPU 並選擇對應 PyTorch wheel。CUDA 12.x 驅動環境用 cu128：

```bash
python3 install.py --cuda cu128 --no-local-llm
```

選項說明：
- `--cuda cu128`：明示用 CUDA 12.8 PyTorch wheel
- `--no-local-llm`：跳過 `llama-cpp-python` 本地 LLM 安裝（本 repo 已有自己的 llama.cpp 翻譯堆疊）

完成後二進位位於 `<WHISPERJAV_DIR>/.venv/bin/whisperjav`（即 `<WHISPERJAV_BIN>`）。

### 4. 驗證

```bash
<WHISPERJAV_BIN> --check
<WHISPERJAV_BIN> --help
```

## 安裝步驟（Windows + CUDA）

Windows 端 WhisperJAV 提供官方 installer，預設安裝路徑為 `C:\Users\<USER>\AppData\Local\WhisperJAV\`，執行檔位於 `Scripts\whisperjav.exe`。

驗證環境：

```powershell
& "<WHISPERJAV_BIN>" --check
```

預期看到 Python、CUDA、PyTorch、GPU 記憶體、FFmpeg、Python 依賴全部 ✓。

## 推薦 CLI：Ensemble Mode（anime-whisper + Qwen3-ASR）

2026-05-23 驗證最佳設定（語法樹形式，下方分 shell 展開實際指令）：

```text
<WHISPERJAV_BIN> <INPUT_VIDEO>
  --ensemble --ensemble-serial
  --pass1-pipeline qwen --pass1-qwen-params '{"generator_backend":"anime-whisper"}'
  --pass2-pipeline qwen --pass2-qwen-params '{"generator_backend":"qwen3"}'
  --merge-strategy smart_merge
  --language japanese
  --output-dir <OUTPUT_DIR>
```

### Linux / macOS / Git Bash

Bash 系列 shell 中單引號內為字面字串，JSON 雙引號可直接寫：

```bash
<WHISPERJAV_BIN> <INPUT_VIDEO> \
  --ensemble --ensemble-serial \
  --pass1-pipeline qwen --pass1-qwen-params '{"generator_backend":"anime-whisper"}' \
  --pass2-pipeline qwen --pass2-qwen-params '{"generator_backend":"qwen3"}' \
  --merge-strategy smart_merge \
  --language japanese \
  --output-dir <OUTPUT_DIR>
```

### Windows PowerShell 7+

PowerShell 單引號內的 `"` 需要 escape 成 `""`：

```powershell
& "<WHISPERJAV_BIN>" `
  "<INPUT_VIDEO>" `
  --ensemble --ensemble-serial `
  --pass1-pipeline qwen --pass1-qwen-params '{""generator_backend"":""anime-whisper""}' `
  --pass2-pipeline qwen --pass2-qwen-params '{""generator_backend"":""qwen3""}' `
  --merge-strategy smart_merge `
  --language japanese `
  --output-dir "<OUTPUT_DIR>"
```

或用 stop-parsing token `--%` 跳過 PowerShell 的引號處理，直接交由執行檔解析：

```powershell
& "<WHISPERJAV_BIN>" --% "<INPUT_VIDEO>" --ensemble --ensemble-serial --pass1-pipeline qwen --pass1-qwen-params {"generator_backend":"anime-whisper"} --pass2-pipeline qwen --pass2-qwen-params {"generator_backend":"qwen3"} --merge-strategy smart_merge --language japanese --output-dir "<OUTPUT_DIR>"
```

注意：`--%` 之後不能再做變數展開，所有路徑要寫死。

### Windows CMD

CMD 用 `\"` escape 雙引號、`^` 接續行：

```cmd
"<WHISPERJAV_BIN>" ^
  "<INPUT_VIDEO>" ^
  --ensemble --ensemble-serial ^
  --pass1-pipeline qwen --pass1-qwen-params "{\"generator_backend\":\"anime-whisper\"}" ^
  --pass2-pipeline qwen --pass2-qwen-params "{\"generator_backend\":\"qwen3\"}" ^
  --merge-strategy smart_merge ^
  --language japanese ^
  --output-dir "<OUTPUT_DIR>"
```

### 參數說明

| 參數 | 說明 |
|------|------|
| `--ensemble --ensemble-serial` | 雙 backend 序列模式，每檔跑完整 Pass1→Pass2→Merge 後才開始下一檔 |
| `--pass1-qwen-params '{"generator_backend":"anime-whisper"}'` | Pass 1 用 [`litagin/anime-whisper`](https://huggingface.co/litagin/anime-whisper)（kotoba-whisper-v2.0 基底，5,300h anime/JAV fine-tune）。**強項**：轉得出 NVV/喘息聲、JAV 慣用語、敬稱 |
| `--pass2-qwen-params '{"generator_backend":"qwen3"}'` | Pass 2 用 [`Qwen/Qwen3-ASR-1.7B`](https://github.com/QwenLM/Qwen3-ASR)（2026 Neosophie benchmark 日文 CER 0.140 SOTA）。**強項**：completion-style 把模糊發音補成自然句、抓 anime-whisper 漏掉的長對白 |
| `--merge-strategy smart_merge` | 智慧 overlap 偵測合併兩 pass。本機驗證淨值最佳 |
| `--language japanese` | 強制日文（避免自動偵測誤判） |

### 替代設定

| 場景 | 設定 |
|------|------|
| **趕時間 / 一般片源** | `--mode qwen --qwen-generator anime-whisper`（單 backend，wall ~8 分鐘 / 127 分鐘片） |
| 極致品質 | `--ensemble --merge-strategy full_merge`（保留所有字幕，下游需自行去重） |
| 主角名重要 | `--ensemble --merge-strategy pass2_primary`（Qwen3 主、anime 補；待驗證） |

## 本機資源使用實測

| 模型 | VRAM | 模型大小 | Wall（127 分鐘片源） |
|------|------|---------|----------------------|
| anime-whisper 單跑 | ~5.5 GB | ~1.5 GB | 8 分鐘（0.063x realtime） |
| Qwen3-ASR-1.7B 單跑 | ~7 GB | ~3.4 GB | ~10 分鐘 |
| **Ensemble** | 7.4 GB / 8 GB | ~4.9 GB（兩模型同時不駐留，序列載入） | **17 分鐘**（0.13x realtime） |

RTX 3070 Laptop 8GB VRAM 剛好塞下，無需特別量化設定。Qwen3-ASR-1.7B 首次執行會自動下載 ~3.4GB 權重至 HuggingFace 快取。

## 與 srt-subtitle-translator 串接

WhisperJAV 輸出標準 SRT，直接餵給本 repo 翻譯 CLI：

```bash
# 1. 轉錄（依平台選擇上方對應的 shell 寫法）
<WHISPERJAV_BIN> <INPUT_VIDEO> --ensemble --ensemble-serial \
  --pass1-pipeline qwen --pass1-qwen-params '{"generator_backend":"anime-whisper"}' \
  --pass2-pipeline qwen --pass2-qwen-params '{"generator_backend":"qwen3"}' \
  --merge-strategy smart_merge --language japanese \
  --output-dir <OUTPUT_DIR>

# 2. 啟 llama-server（路徑與旗標見本 repo CLAUDE.md 之 llama.cpp 章節）
GGML_CUDA_NO_VMM=1 LD_LIBRARY_PATH=<LLAMACPP_BIN_DIR> \
  <LLAMACPP_BIN_DIR>/llama-server \
    -m <MODEL_DIR>/Hy-MT2-7B-Q4_K_M.gguf -ngl auto -fa on \
    -ctk q8_0 -ctv q8_0 -kvu -cram 4096 --jinja -c 4096 -np 2 \
    --no-context-shift -rea off --cache-reuse 256 \
    --host 127.0.0.1 --port 8080 &

# 3. 翻譯（替換為實際 SRT 檔名；Ensemble 模式輸出為 <video>.ja.merged.whisperjav.srt）
uv run srt-translator translate <OUTPUT_DIR>/<video>.ja.merged.whisperjav.srt \
  -s 日文 -t 繁體中文 \
  --provider llamacpp -m Hy-MT2-7B-Q4_K_M \
  --content-type adult
```

## 驗證結論（IPZZ-810，2026-05-23）

| 設定 | 不劣化率 vs Claude 人工 baseline | 主要主軸錯誤修正 |
|------|---:|---:|
| 原預設 WhisperJAV Balanced | 88.1% | 0/12 |
| **anime-whisper 單跑** | ~92% (推估) | 5/12 |
| **Ensemble anime+qwen3** | ~94–96% (推估) | **8/12** |

完整數據見：
- `data/benchmark-2026-05-23-ipzz810/README.md` — 原版 baseline 對照（466 條）
- `data/benchmark-2026-05-23-ipzz810/anime-whisper-rerun/README.md` — anime-whisper 單跑
- `data/benchmark-2026-05-23-ipzz810/ensemble-rerun/README.md` — Ensemble 對照

## 方法論 caveat

本指南推薦設定的有效性，來自「日文語言可信度」比較，不是「轉錄正確率」(CER/WER) 的 ground truth 驗證 — 沒有人工聽寫的對照文本。但兩項強訊號支撐結論可信：

1. **女主角名「ミツリ」在多時間點重複穩定識別**（不太可能是巧合）
2. **長句「生まれ変わらせてあげようって思って」完整且語境正確**（要排出長片段機率上不可能是 ASR 隨機產生）

如需嚴格量化，需要人工聽寫一段做 ground truth、計算 CER/WER。

## 已知限制

| 限制 | 緩解 |
|------|------|
| 名字一致性仍會漂浮（同人在不同句譯不同字） | **下游用 glossary 強制統一**（本 repo `data/glossaries/`） |
| 句子粒度比預設粗（多句合併） | Ensemble 後條數較多（681 vs 預設 466），但仍偶有合併 |
| ~5–10% 句子兩 backend 都打不到（純喘息音段） | 接受。改用 NVV 字幕（如「あんっ」）至少不丟訊息 |
| 首次執行下載 ~5GB 模型權重 | 一次性 |

## 升級與維護

WhisperJAV 活躍維護中（2026 仍每季有 release），升級方式：

Linux / macOS：

```bash
cd <WHISPERJAV_DIR>
git pull
.venv/bin/python install.py --cuda cu128 --no-local-llm  # 或執行 <WHISPERJAV_BIN>-upgrade
```

Windows（官方 installer 安裝者）：執行開始功能表中的 **WhisperJAV → Upgrade** 捷徑，或直接跑 `whisperjav-upgrade.exe`（與 `whisperjav.exe` 同目錄）。

新 release 可能調整 CLI 參數，升級後務必 `whisperjav --help` 確認 Ensemble 設定仍適用。

## 參考

- [WhisperJAV GitHub](https://github.com/meizhong986/WhisperJAV)
- [WhisperJAV Docs](https://meizhong986.github.io/WhisperJAV/)
- [litagin/anime-whisper (HuggingFace)](https://huggingface.co/litagin/anime-whisper)
- [Qwen3-ASR GitHub](https://github.com/QwenLM/Qwen3-ASR)
- [Neosophie 2026 日文 ASR Benchmark](https://neosophie.com/en/blog/20260226-japanese-asr-benchmark)
