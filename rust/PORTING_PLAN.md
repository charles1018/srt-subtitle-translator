# Rust 移植計畫

> 目標：以 Rust 重寫 SRT Subtitle Translator，**翻譯品質行為與 Python 版逐位元一致**（prompt、後處理、名字保護、快取鍵），同時取得單一執行檔、啟動快、低記憶體的好處。
> Python 版在移植期間保持為「行為規格」與對照基準，不刪除、不改動。

## 1. 原則

1. **行為對等優先於重新設計**。本專案品質來自大量經 A/B benchmark 調校的細節（見 `FUTURE_AGENT_REPO_GUIDE.md` §1）。移植時 prompt 文字、採樣參數、後處理規則、正則一律**逐字搬移**，不「順手改良」。
2. **Golden parity 測試**：`rust/tools/gen_golden.py` 以 Python 實作跑一組固定輸入，輸出 JSON 到 `rust/tests/golden/`；Rust 測試讀同一份 JSON 比對輸出。每個移植模組都要有 golden 覆蓋。
3. **資料相容**：沿用 `config/*.json`、`data/translation_cache.db`（同 schema、同 cache key/MD5）、`data/glossaries/*.json`，Rust 與 Python 版可共用同一份設定與快取。
4. **CLI 優先、GUI 最後**：先完成 CLI 對等，GUI 另案評估。
5. 由下而上：純函式 → I/O → 網路 → 編排 → CLI。

## 2. 架構（單一 crate，lib + bin）

```
rust/
├── Cargo.toml                 # package: srt-translator（binary 名稱 srt-translator-rs，避免與 Python 版衝突）
├── src/
│   ├── lib.rs
│   ├── main.rs                # clap CLI
│   ├── error.rs               # FileError / ValidationError / TranslationError…（thiserror）
│   ├── subtitle/              # 字幕模型 + 格式
│   │   ├── time.rs            # SubRipTime 對等（ordinal ms、寬鬆解析）
│   │   ├── srt.rs             # pysrt 對等解析/輸出
│   │   ├── encoding.rs        # BOM → UTF-8 → chardetng 偵測
│   │   ├── vtt.rs / ass.rs    # 第 4 階段
│   ├── tools/srt_tools.rs     # extract / assemble / qa / cps-audit / batch 字串
│   ├── text/
│   │   ├── post_processor.rs  # Netflix 風格後處理
│   │   ├── japanese.rs        # 名字保護、未翻譯日文偵測、快取拒絕原因
│   │   ├── normalize.rs       # 台灣詞彙正規化、原文感知片語、單行清理、本地模型輸出清理
│   ├── glossary.rs
│   ├── config.rs              # 第 2 階段
│   ├── cache.rs               # 第 2 階段（rusqlite, 與 Python 共用 DB）
│   ├── prompt.rs              # 第 2 階段（prompt 文字逐字搬移）
│   ├── client/                # 第 3 階段（reqwest + tokio）
│   └── service.rs             # 第 4 階段（TranslationService 檔案流水線）
├── tests/golden/*.json
└── tools/gen_golden.py
```

Python → Rust 對應：

| Python | Rust | 階段 |
|---|---|---|
| `tools/srt_tools.py` + pysrt | `subtitle/*`, `tools/srt_tools.rs` | 1 |
| `utils/post_processor.py` | `text/post_processor.rs` | 1 |
| `client.py` 名字保護/未翻譯偵測/詞彙正規化 | `text/japanese.rs`, `text/normalize.rs` | 1 |
| `factory.py` `_normalize_source_aware_subtitle_phrases` | `text/normalize.rs` | 1 |
| `core/glossary.py` | `glossary.rs` | 1 |
| `core/config.py` | `config.rs` | 2 |
| `core/cache.py` | `cache.rs` | 2 |
| `core/prompt.py` | `prompt.rs` | 2 |
| `translation/client.py`（OpenAI/llama.cpp/Gemini、重試、自適應並行、速率限制、model profiles） | `client/*` | 3 |
| `services/factory.py` `TranslationService`（上下文視窗、批次安全判斷、structure-text 批次、OpenCC s2twp） | `service.rs` | 4 |
| `file_handling/handler.py`（VTT/ASS、衝突處理） | `subtitle/vtt.rs`, `ass.rs`, `output.rs` | 4 |
| `cli.py` | `main.rs` | 1（工具子命令）→ 4（translate 等） |
| `gui/components.py` | 待定（egui / Slint / Tauri） | 5 |

主要相依：`clap`、`serde`/`serde_json`、`fancy-regex`（Python 正則的 lookaround）、`encoding_rs` + `chardetng`、`thiserror`、`indexmap`；之後 `rusqlite`（bundled）、`md-5`、`tokio`、`reqwest`（rustls）、`tiktoken-rs`、OpenCC 純 Rust 實作（候選 `ferrous-opencc`，需以 golden 驗證 s2twp 對等）。

## 3. 階段與驗收

| 階段 | 內容 | 驗收 |
|---|---|---|
| **0** | Cargo 專案骨架、錯誤型別、golden 產生器、CI job（fmt/clippy/test） | `cargo test` 綠燈 |
| **1** | SRT 解析/輸出、編碼偵測、extract/assemble/qa/cps-audit、batch 字串、Netflix 後處理、日文名字保護、詞彙正規化、glossary；CLI `extract`/`assemble`/`qa`/`cps-audit` | golden 全數一致；對 `tests/e2e/fixtures/*.srt` 與 Python 輸出逐位元相同 |
| **2** | config（讀寫同一批 JSON、預設值、驗證）、cache（同 schema、同 key、TTL/清理/匯入匯出）、prompt manager（全部模板 + 版本雜湊） | prompt 產出訊息與 `get_prompt_version` 與 Python golden 一致；Rust 可命中 Python 寫入的快取 |
| **3** | 翻譯 client：OpenAI 相容路徑（llama.cpp 共用）、Gemini、錯誤分類與退避重試、429 retry-after、自適應並行、RPM/TPM 限制、llama.cpp slot 診斷與 json_object 輸出 | 以 mock HTTP server（wiremock）測試；本地 llama-server 冒煙測試 |
| **4** | TranslationService 檔案流水線、structure-text 批次（1:1 驗證 + 退回單句）、上下文視窗、OpenCC、輸出衝突處理、VTT/ASS；CLI `translate`/`cache`/`config`/`glossary`/`prompt`/`models` | 以 `data/MIKR-059ja-test.srt`、`ChicagoFire-S14E18-en-test.srt` 跑 benchmark，與 Python 版同模型同參數比對（依 `BENCHMARK_PROCEDURE.md`） |
| **5** | GUI（另案評估）、打包發佈 | — |

## 4. 已知風險

- **正則語意差異**：Python `re` 與 `fancy-regex` 在 Unicode 類別、`\s`、`\d` 上大致相同，但需 golden 覆蓋所有正則；Python 用 `str.strip()`（多剝 `\x1c-\x1f`）與 Rust `trim()` 有極小差異。
- **編碼偵測**：chardet 與 chardetng 結果可能不同（主要影響 Big5/GBK/Shift-JIS 舊檔）；UTF-8/BOM 檔案行為一致。
- **tiktoken**：token 估算只影響速率限制，允許近似。
- **OpenCC s2twp**：純 Rust 實作的詞典版本可能不同，需 golden 驗證，必要時改用 C binding。
- **GUI**：Tkinter 無直接對應，是最大的重寫量，放最後。

## 5. 進度

- [x] **階段 0**（2026-09-29）：Cargo 骨架、`error.rs`、`py.rs`（Python 字串語意）、golden 產生器、CI `rust` job（fmt / clippy / test / golden freshness）
- [x] **階段 1**（2026-09-29）：`subtitle/`（pysrt 對等解析輸出 + 編碼偵測）、`tools/srt_tools.rs`、`text/post_processor.rs`、`text/japanese.rs`、`text/normalize.rs`、`glossary.rs`；CLI `extract` / `assemble` / `qa` / `cps-audit` / `version`
  - 驗證：golden 7 組全數一致（後處理 219 案例、13 個 SRT 檔含 466 條實際字幕、本地 526 條後處理）；CLI 輸出與產出檔案與 Python 逐位元相同；變異測試確認 golden 能抓到行為偏差
  - 尚未涵蓋：glossary 的 CLI 子命令（併入階段 4）
- [ ] 階段 2：config → cache → prompt（下一步從 `core/config.py` 的預設值與 JSON 合併邏輯開始）
- [ ] 階段 3
- [ ] 階段 4
- [ ] 階段 5

## 6. 開發指令

```bash
cd rust
cargo test                                   # 單元 + golden parity
cargo clippy --all-targets -- -D warnings
cargo fmt
../.venv/bin/python tools/gen_golden.py      # Python 行為改變後重新產生 golden（加 --local 納入 data/*.srt）
```
