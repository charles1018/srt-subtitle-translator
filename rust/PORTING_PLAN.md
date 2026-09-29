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
- [x] **階段 2**（2026-09-29）：`config.rs`、`cache.rs`、`prompt/`；CLI `cache` / `config` / `prompt`
  - 驗證：golden 5 組全數一致——7 個預設設定檔原文、快取 schema 與 context hash、2400 組 prompt/版本雜湊（3 provider × 5 內容類型 × 4 風格 × 5 模型 × 4 語言對 × compact 開關）、1800 組訊息結構與快取上下文、自訂 prompt/模板/重置流程；4 項變異測試皆被抓到
  - 實測：以真實 `config/` 複本比對 `prompt show`（15 組）與 `config --show/--set` 寫回結果完全相同；快取雙向互通（Python 寫 → Rust 讀、Rust 寫 → Python 命中）
  - 內建預設 prompt 由 Python 匯出為 `src/prompt/default_prompts.json`（不要手改），`gen_golden.py --check` 於 CI 檢查是否過期
  - 未移植（Python 版正式流程無呼叫端）：config 備份/匯出/匯入/listener、`analyze_prompt`、prompt 版本歷史瀏覽/還原
  - 與 Python 的刻意差異：`cache --stats` 顯示正確的總筆數（Python 讀不存在的 `total_entries` 恆為 0）；`import_cache` 以實際新增列數計數
- [x] **階段 3**（2026-09-29）：`client/`（profiles、錯誤分類與 429 等待、自適應並行、RPM/TPM 限制、OpenAI 相容請求、Gemini REST、llama.cpp 診斷、translate_text/with_retry/batch）
  - 驗證：golden 336 組完整流水線（6 模型 × 2 內容類型 × Netflix 開關 × 14 情境）逐一比對「送出的請求 body + 最終結果」全數一致；profile/家族/錯誤分類/429 等待時間一致；6 項變異測試皆被抓到；wiremock 行為測試 6 項（SDK 式重試、401 錯誤標記、429、批次順序＋快取、slots 回退、Gemini）
  - 實機（Hy-MT2-7B-Q4_K_M、llama.cpp b11286）：逐句模式日文 30/30、英文 30/30、英文＋Netflix 30/30 與 Python **輸出完全相同**（排除 server 冷啟動第一輪）；並行批次模式差異與 Python 自身重跑的變異同級（llama.cpp 多 slot 推論非決定性）；IPZZ-810 466 條兩版皆 0 失敗，速度相同（GPU 瓶頸），RSS 11.7MB vs 83MB
  - 對照工具：`cargo run --release --example live_client` 與 `rust/tools/live_client.py`（參數相同）
  - 與 Python 的刻意差異（不影響翻譯內容）：連線/逾時錯誤依來源分類（Python 落入 unknown、重試前不等待）；OpenAI token 用估算法（Python 用 tiktoken，僅影響速率限制）；最後一次重試失敗後不再多等一輪
  - 觀察（Python 既有行為，未改動）：日文名字保護的正則會把 おじさん／おばあちゃん／おねえさん 等親屬稱謂當成名字保留成日文；若要調整需先跑 benchmark
- [x] **階段 4**（2026-09-29）：`service/`（上下文視窗與智慧批次啟發式、服務層後處理、structure-text 批次＋1:1 驗證＋句型檢查＋退回逐句、整份檔案流程）、`text/opencc.rs`（逐行移植 opencc-python-reimplemented 的 s2twp 演算法並內嵌其字典）、`output.rs`（輸出檔名樣式與衝突處理）、`models.rs`、glossary 匯入/匯出；CLI `translate` / `models` / `glossary`
  - 驗證：OpenCC 453 組（含 400 組隨機字典鍵壓力案例）、啟發式 38 句 × 9 項、後處理 36 組（術語表/標點開關）、端到端 5 情境（llama.cpp/OpenAI × 一般/structure-text × 顯示模式 × Netflix，含批次行數不符退回逐句）比對輸出 SRT 與全部請求 body，全數一致；後處理順序/上下文視窗/退回視窗/批次安全/顯示模式/OpenCC 最左匹配等變異皆被抓到
  - CLI 比對：`glossary`（create/add/show/list/export csv/txt/remove/import）與 `models` 輸出及寫出檔案逐位元相同
  - 實機（Hy-MT2-7B）：CLI 端到端逐句模式日文（adult＋Netflix）、英文（雙語）、日文 structure-text 輸出檔**完全相同**；快取雙向共用（Python 寫 → Rust 讀、Rust 寫 → Python 讀）皆命中且輸出相同；IPZZ-810 466 條並行 3 成功、殘留假名數與 Python 相同；RSS 約 21MB vs 98MB
  - 英文 structure-text＋Netflix 連跑 13 輪：Python 12/13、Rust 9/13 為同一輸出，其餘為 server 端非決定性變體（請求 body 已由 golden 證明相同；推測與 Rust 請求間隔較短、較常撞到 server 收尾時序有關）
  - 與 Python 的刻意差異：`-o/--output-dir` 不寫回 `file_handler_config.json`（Python 會永久寫入）；Google 模型列表不額外送請求驗證金鑰；目錄掃描結果依路徑排序
  - 既有限制（與 Python 相同）：.vtt/.ass 以 SRT 解析器讀取；structure-text 模式會把空白字幕也送進批次並套上譯文；`glossary activate` 只在單次執行有效（翻譯時用 `translate -g`）
  - 實機觀察：llama.cpp b11286（CUDA）在 `-np 3` 並行解碼時曾發生一次 `CUDA error: an illegal instruction`（dmesg NVRM Xid 13/43）導致 server 崩潰，重啟後同負載未重現；與 client 無關，但若頻繁發生可考慮退回 skill 記載的已驗證 build
- [x] **階段 5a**（2026-09-29）：打包發佈 + GUI 前置 API（決策：先打包 Linux/Windows，GUI 採 Tauri v2＋純 HTML/JS 前端，理由為中文輸入法/CJK 排版/原生拖放）
  - release profile（fat LTO、codegen-units 1、strip）：17.2MB → Linux 12.2MB / Windows 10.4MB；Windows MSVC 以 `rust/.cargo/config.toml` 靜態連結 CRT
  - `.github/workflows/rust-release.yml`：推 `rust-v*` 標籤（須與 Cargo 版本一致）→ 兩平台先跑 `cargo test` → Linux 以 cargo-zigbuild 連結 glibc 2.28、Windows MSVC → 冒煙 → tar.gz / zip＋sha256 → **草稿** Release；`workflow_dispatch` 只產 artifact。`ci.yml` 新增 `rust-windows` 測試 job（checkout 前關閉 autocrlf，golden 會讀 repo 內字幕 fixture）
  - 驗證：zig＋LTO 建置的 Linux 測試二進位 90 項全過；Windows GNU 交叉編譯（主程式＋測試）通過（本機無 wine，**Windows 上的測試尚未實際執行，待首次推送由 CI 驗證**）；actionlint 通過；打包內容解壓後於空目錄執行正常；打包的執行檔實機（Hy-MT2-7B，`-c 1 --no-cache`）日文 adult＋Netflix、英文雙語輸出與 Python **逐位元相同**
  - `service::TaskControl`（暫停/繼續/停止）與 `translate_subtitle_file_with_control`：每批送出前檢查暫停（進行中批次會完成）、停止時中止進行中的請求且不寫輸出檔、回傳 `Error::Cancelled`；6 項行為測試，4 項變異（移除批次前檢查／寫檔前檢查／逐句路徑／structure-text 路徑不可中止）皆被抓到
  - 與 Python 的刻意差異：Python 的 stop 只停止回報，背景仍跑完並寫出檔案；Python 的暫停卡在逐句進度回呼內，Rust 先回報完該批進度再於下一批前暫停
  - 使用者須知（Python 既有行為）：`-o` 目錄不存在時默默輸出到輸入檔旁（已寫入 `packaging/README.txt`）
- [ ] 階段 5b：Tauri v2 GUI（純 HTML/JS，無 npm）

## 6. 開發指令

```bash
cd rust
cargo test                                   # 單元 + golden parity
cargo clippy --all-targets -- -D warnings
cargo fmt
../.venv/bin/python tools/gen_golden.py      # Python 行為改變後重新產生 golden（加 --local 納入 data/*.srt）

# 發佈：更新 Cargo.toml version 後推標籤 rust-vX.Y.Z，CI 建立草稿 Release
# 本機交叉編譯（需 zig：uv 裝 ziglang 後加進 PATH）
cargo zigbuild --release --locked --target x86_64-unknown-linux-gnu.2.28
cargo zigbuild --release --locked --target x86_64-pc-windows-gnu
```
