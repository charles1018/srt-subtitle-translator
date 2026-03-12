# 使用者指南

> SRT Subtitle Translator 完整使用指南

## 目錄

- [快速開始](#快速開始)
- [詳細安裝指南](#詳細安裝指南)
- [CLI 命令列模式](#cli-命令列模式) *(1.1.0 新增)*
- [SRT 工具箱](#srt-工具箱) *(NEW)*
- [術語表管理](#術語表管理) *(1.1.0 新增)*
- [介面說明](#介面說明)
- [使用範例](#使用範例)
- [進階功能](#進階功能)
- [配置說明](#配置說明)
- [故障排除](#故障排除)
- [FAQ](#faq)
- [最佳實踐](#最佳實踐)

---

## 快速開始

### 前置需求

1. **Python 環境**：Python 3.10 或更高版本
2. **網路連接**：使用 API 模式時必須
3. **AI 服務**（擇一）：
   - Ollama（本地）
   - OpenAI API 金鑰
   - Google Gemini API 金鑰（GUI）
   - Anthropic API 金鑰（目前僅模型資訊 / 金鑰層）

### 5 分鐘快速上手

```bash
# 1. 安裝
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator
uv sync --all-extras --dev

# 2. 設定 API 金鑰（擇一方式）
# 方式 A：.env 檔案（推薦）
cp .env.example .env
# 編輯 .env 填入 API 金鑰

# 方式 B：環境變數
export OPENAI_API_KEY="your-api-key"
export ANTHROPIC_API_KEY="your-api-key"
export GOOGLE_API_KEY="your-api-key"

# 3. 啟動
uv run srt-translator

# 4. 在介面中選擇檔案、設定參數、開始翻譯

# 或使用 CLI 模式
srt-translator translate video.srt -s 日文 -t 繁體中文
```

### Provider 現況（請先看）

目前專案不同層級對 provider 的支援範圍仍在整理中，使用前請先區分：

| 層級 | 目前狀態 |
|------|----------|
| 實際翻譯 runtime | `ollama`、`openai`、`google` |
| CLI `translate` / `models` 參數 | `ollama`、`openai`、`anthropic` |
| GUI provider 下拉 | `ollama`、`openai`、`anthropic`、`google` |
| 模型 metadata / 金鑰載入 | `ollama`、`openai`、`anthropic`、`google` |
| `ConfigManager` 驗證 `user.llm_type` | `ollama`、`openai` |
| OpenRouter | 規劃中，尚未實作 |

> 實務上：
> - CLI `translate` 目前建議只使用 `ollama` 或 `openai`
> - GUI provider 下拉目前會顯示 `google`，但一般使用者工作流仍以 `ollama`、`openai` 最穩定
> - `anthropic` 目前已接到金鑰與模型資訊層，但尚無第一級翻譯 runtime

---

## 詳細安裝指南

### Windows

#### 方法 1：使用 uv（推薦）

```powershell
# 安裝 uv（如果尚未安裝）
pip install uv

# 克隆專案
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator

# 安裝依賴
uv sync --all-extras --dev

# 執行
uv run srt-translator
```

#### 方法 2：使用 pip

```powershell
# 克隆專案
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator

# 建立虛擬環境
python -m venv .venv
.venv\Scripts\activate

# 安裝依賴
pip install -r requirements.txt

# 執行
python -m srt_translator
```

### macOS / Linux

#### 使用 uv（推薦）

```bash
# 安裝 uv
pip install uv

# 克隆專案
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator

# 安裝依賴
uv sync --all-extras --dev

# 執行
uv run srt-translator
```

#### 使用 pip

```bash
# 克隆專案
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator

# 建立虛擬環境
python3 -m venv .venv
source .venv/bin/activate

# 安裝依賴
pip install -r requirements.txt

# 執行
python -m srt_translator
```

### API 金鑰設定

#### 方法 1：.env 檔案（推薦）

複製範本並填入您的 API 金鑰：

```bash
cp .env.example .env
```

編輯 `.env` 檔案：
```env
# OpenAI API
OPENAI_API_KEY=sk-your-openai-api-key

# Anthropic API
ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key

# Google Gemini API（二擇一）
GOOGLE_API_KEY=your-google-api-key
# 或
GEMINI_API_KEY=your-google-api-key
```

> **安全提示**：`.env` 檔案已加入 `.gitignore`，不會被提交到版本控制。

#### 方法 2：環境變數

```bash
# Linux/macOS
export OPENAI_API_KEY="sk-your-openai-api-key"
export ANTHROPIC_API_KEY="sk-ant-your-anthropic-api-key"
export GOOGLE_API_KEY="your-google-api-key"

# Windows PowerShell
$env:OPENAI_API_KEY="sk-your-openai-api-key"
$env:ANTHROPIC_API_KEY="sk-ant-your-anthropic-api-key"
$env:GOOGLE_API_KEY="your-google-api-key"
```

#### 方法 3：金鑰檔案（向下相容）

```bash
echo "sk-your-openai-api-key" > openapi_api_key.txt
echo "sk-ant-your-anthropic-api-key" > anthropic_api_key.txt
echo "your-google-api-key" > google_api_key.txt
```

> **優先順序**：環境變數 > .env 檔案 > 金鑰檔案
>
> **補充**：程式碼目前可讀取 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`、`GOOGLE_API_KEY`、`GEMINI_API_KEY`，但是否能在特定介面直接用於翻譯，仍以上方 provider 現況表為準。

#### 取得 API 金鑰

| 服務 | 取得位置 |
|------|----------|
| **OpenAI** | [OpenAI Platform](https://platform.openai.com/api-keys) |
| **Anthropic** | [Anthropic Console](https://console.anthropic.com/settings/keys) |
| **Google Gemini** | [Google AI Studio](https://aistudio.google.com/apikey) |

---

## CLI 命令列模式

> *1.1.0 版本新增功能*

除了 GUI 圖形介面外，本工具也提供完整的命令列介面（CLI），適合自動化工作流程和批次處理。

> **目前狀態說明**
> - CLI parser 目前接受 `ollama`、`openai`、`anthropic`
> - CLI 實際翻譯目前建議只使用 `ollama`、`openai`
> - `anthropic` 目前較適合用於 `models -p anthropic` 檢視模型資訊，尚無第一級翻譯 runtime
> - `google` 執行路徑已存在，但尚未暴露在 CLI `--provider`

### 基本指令

```bash
# 顯示說明
srt-translator --help

# 顯示版本
srt-translator version

# 翻譯單一檔案
srt-translator translate video.srt -s 日文 -t 繁體中文

# 批次翻譯整個資料夾
srt-translator translate ./subtitles/ -s 英文 -t 繁體中文

# 使用特定模型
srt-translator translate video.srt -s 日文 -t 繁體中文 -p openai -m gpt-4

# 套用術語表
srt-translator translate video.srt -s 日文 -t 繁體中文 -g anime
```

### 翻譯指令參數

| 參數 | 簡寫 | 說明 | 預設值 |
|------|------|------|--------|
| `--source` | `-s` | 來源語言 | 英文 |
| `--target` | `-t` | 目標語言 | 繁體中文 |
| `--provider` | `-p` | CLI 參數可選值：`ollama` / `openai` / `anthropic`。其中實際翻譯目前建議使用 `ollama` / `openai` | ollama |
| `--model` | `-m` | 模型名稱 | 各引擎推薦模型 |
| `--display-mode` | `-d` | 顯示模式（僅譯文/雙語對照/僅原文）| 僅譯文 |
| `--glossary` | `-g` | 套用的術語表名稱（可多次指定）| - |
| `--output-dir` | `-o` | 輸出目錄 | 原檔案目錄 |
| `--concurrency` | `-c` | 並發數 | 3 |
| `--no-cache` | - | 不使用翻譯快取 | 關閉 |
| `--structure-text` | - | 使用結構-文本分離翻譯模式（實驗性）| 關閉 |

### 結構-文本分離翻譯模式

使用 `--structure-text` 旗標啟用實驗性的結構-文本分離翻譯模式。此模式將多個字幕合併為單一批次字串以單一 API 呼叫翻譯，可以：

- 減少 API 呼叫次數，降低 token 消耗
- 消除 LLM 損壞字幕結構（timestamp、index）的風險
- 嚴格驗證翻譯行數 1:1 對應

```bash
# 使用結構-文本分離模式翻譯
srt-translator translate video.srt -s 英文 -t 繁體中文 --structure-text

# 搭配指定模型使用
srt-translator translate video.srt -s 英文 -t 繁體中文 -p openai -m gpt-4o --structure-text
```

> **注意**：此為實驗性功能。若批次翻譯的行數不匹配，系統會自動重試，最終退回標準逐條翻譯模式。

### 模型管理

```bash
# 列出所有可用模型
srt-translator models

# 列出特定提供者的模型
srt-translator models -p ollama
srt-translator models -p openai
srt-translator models -p anthropic
```

### 快取管理

```bash
# 查看快取統計
srt-translator cache --stats

# 清除所有快取
srt-translator cache --clear
```

### 配置管理

```bash
# 顯示當前配置
srt-translator config --show

# 設定預設值
srt-translator config --set source_lang 日文
srt-translator config --set target_lang 繁體中文
```

---

## SRT 工具箱

SRT 工具箱提供字幕檔案的結構-文本分離、品質檢驗等獨立工具，可在不翻譯的情況下使用。

> **目前狀態說明**：`extract` / `assemble` / `qa` / `cps-audit` 已在 `src/srt_translator/cli.py` 定義，但目前建議直接以 `uv run python -m srt_translator.cli ...` 呼叫，避免入口點 dispatch 差異。

### Extract（拆分）

將 SRT 檔案拆分為結構檔（`_structure.json`）和純文字檔（`_text.txt`）：

```bash
uv run python -m srt_translator.cli extract video.srt
# 輸出：video_structure.json + video_text.txt

# 自訂輸出前綴
uv run python -m srt_translator.cli extract video.srt -o my_prefix
# 輸出：my_prefix_structure.json + my_prefix_text.txt
```

### Assemble（重組）

將翻譯後的文字檔與結構檔重組為完整 SRT：

```bash
# 預設尋找 video_translated_text.txt
uv run python -m srt_translator.cli assemble video

# 指定翻譯文字檔
uv run python -m srt_translator.cli assemble video -t custom_translated.txt

# 指定輸出檔名
uv run python -m srt_translator.cli assemble video -o output.srt
```

### QA（品質檢驗）

比對源檔與翻譯檔的結構完整性：

```bash
uv run python -m srt_translator.cli qa source.srt translated.srt

# 嚴格模式（任何不匹配即失敗）
uv run python -m srt_translator.cli qa source.srt translated.srt --strict
```

檢查項目：字幕數量、timestamp 一致性、index 連續性。

### CPS Audit（可讀性審計）

分析字幕的 CPS（Characters Per Second）可讀性：

```bash
uv run python -m srt_translator.cli cps-audit translated.srt

# 自訂閾值
uv run python -m srt_translator.cli cps-audit translated.srt --max-cps 15 --max-line-length 20 --min-duration 1200
```

預設閾值：
| 指標 | 預設值 | 說明 |
|------|--------|------|
| `--max-cps` | 17.0 | 最大 CPS（每秒字元數） |
| `--max-line-length` | 22 | 最大行長（字元數） |
| `--max-lines` | 2 | 最大行數 |
| `--min-duration` | 1000 | 最短持續時間（毫秒） |

### 完整工作流範例

```bash
# 1. 拆分字幕
uv run python -m srt_translator.cli extract episode_01.srt

# 2. 手動翻譯或用外部工具翻譯 episode_01_text.txt
#    儲存為 episode_01_translated_text.txt

# 3. 重組 SRT
uv run python -m srt_translator.cli assemble episode_01

# 4. 品質檢驗
uv run python -m srt_translator.cli qa episode_01.srt episode_01_translated.srt

# 5. 可讀性審計
uv run python -m srt_translator.cli cps-audit episode_01_translated.srt
```

---

## 術語表管理

> *1.1.0 版本新增功能*

術語表功能可確保專有名詞的翻譯一致性，特別適用於動畫、電影或專業領域的字幕翻譯。

### 為什麼需要術語表？

- **一致性**：確保同一名詞在整部影片中翻譯一致
- **準確性**：專有名詞使用正確的官方翻譯
- **效率**：避免每次翻譯都需要人工校對相同名詞

### 建立術語表

```bash
# 建立新術語表（指定來源和目標語言）
srt-translator glossary create anime -s 日文 -t 繁體中文
srt-translator glossary create marvel -s 英文 -t 繁體中文
```

### 新增術語

```bash
# 新增單一術語
srt-translator glossary add anime "進撃の巨人" "進擊的巨人"
srt-translator glossary add anime "エレン" "艾連"
srt-translator glossary add anime "ミカサ" "米卡莎"

# 新增英文術語
srt-translator glossary add marvel "Avengers" "復仇者聯盟"
srt-translator glossary add marvel "Thanos" "薩諾斯"
```

### 查看術語表

```bash
# 列出所有術語表
srt-translator glossary list

# 查看特定術語表內容
srt-translator glossary show anime
```

### 匯入匯出

支援三種格式：JSON、CSV、TXT

```bash
# 匯出為 JSON（推薦，保留所有資訊）
srt-translator glossary export anime anime_terms.json -f json

# 匯出為 CSV（方便用 Excel 編輯）
srt-translator glossary export anime anime_terms.csv -f csv

# 匯出為 TXT（簡單格式）
srt-translator glossary export anime anime_terms.txt -f txt

# 匯入術語
srt-translator glossary import terms.json -n anime
srt-translator glossary import terms.csv -n anime
```

### JSON 格式範例

```json
{
  "name": "anime",
  "source_lang": "日文",
  "target_lang": "繁體中文",
  "terms": [
    {"source": "進撃の巨人", "target": "進擊的巨人"},
    {"source": "エレン", "target": "艾連"},
    {"source": "ミカサ", "target": "米卡莎"}
  ]
}
```

### CSV 格式範例

```csv
source,target
進撃の巨人,進擊的巨人
エレン,艾連
ミカサ,米卡莎
```

### 在翻譯時使用術語表

```bash
# CLI 模式
srt-translator translate episode_01.srt -s 日文 -t 繁體中文 -g anime

# 批次翻譯
srt-translator translate ./subtitles/ -s 日文 -t 繁體中文 -g anime
```

### GUI 中使用術語表

GUI 目前沒有獨立的術語表下拉選單。若要在 GUI 翻譯時套用術語表，請先用 CLI 啟用：

```bash
srt-translator glossary activate anime
```

翻譯服務會自動套用目前已啟用的術語表；完成後可再用 `srt-translator glossary deactivate anime` 停用。

---

#### Ollama

1. 前往 [Ollama 官網](https://ollama.ai) 下載並安裝
2. 啟動 Ollama 服務：

```bash
ollama serve
```

3. 拉取模型（例如 llama3.2）：

```bash
ollama pull llama3.2
```

---

## 介面說明

### 主視窗

```
┌─────────────────────────────────────────────┐
│  SRT 字幕翻譯器                              │
├─────────────────────────────────────────────┤
│  檔案清單                                    │
│  ┌───────────────────────────────────────┐  │
│  │ [選擇的檔案列表]                      │  │
│  │                                       │  │
│  └───────────────────────────────────────┘  │
│  [選擇檔案] [移除選取] [清除全部]           │
│                                             │
│  源語言: [日文 ▼]   目標語言: [繁體中文 ▼] │
│  LLM 類型: [ollama ▼]                       │
│  模型: [llama3.2 ▼]                          │
│  並發數: [3 ▼]                              │
│  顯示模式: [雙語對照 ▼]                     │
│                                             │
│  [開始翻譯] [暫停] [停止]                   │
│                                             │
│  進度條: ████░░░░░░ 40%                     │
│  狀態: 正在翻譯第 20/50 句字幕...            │
└─────────────────────────────────────────────┘
```

### 控制項說明

| 控制項 | 說明 |
|--------|------|
| **選擇檔案** | 開啟檔案選擇對話框，選擇要翻譯的字幕檔案 |
| **移除選取** | 從清單中移除選取的檔案 |
| **清除全部** | 清空檔案清單 |
| **源語言** | 選擇字幕原始語言 |
| **目標語言** | 選擇翻譯目標語言 |
| **LLM 類型** | GUI 下拉目前顯示 `ollama` / `openai` / `anthropic` / `google`；其中實際翻譯 runtime 目前為 `ollama` / `openai` / `google` |
| **模型** | 選擇要使用的 AI 模型 |
| **並發數** | 設定同時翻譯的字幕數量 |
| **顯示模式** | 選擇輸出字幕的顯示方式 |
| **開始翻譯** | 開始翻譯處理 |
| **暫停** | 暫停/繼續翻譯 |
| **停止** | 停止翻譯並清理資源 |

---

## 使用範例

### 範例 1：基本翻譯（日文 → 繁體中文）

1. **準備檔案**：確保有 SRT 格式的日文字幕檔案
2. **啟動程式**：`uv run srt-translator`
3. **選擇檔案**：點擊「選擇檔案」或直接拖放檔案到視窗
4. **設定參數**：
   - 源語言：日文
   - 目標語言：繁體中文
   - LLM 類型：openai
   - 模型：gpt-3.5-turbo
   - 並發數：5
   - 顯示模式：雙語對照
5. **開始翻譯**：點擊「開始翻譯」
6. **等待完成**：進度條會顯示翻譯進度
7. **查看結果**：翻譯後的檔案會儲存在原檔案目錄，檔名加上語言後綴

**範例輸出檔名**：
- 原檔案：`episode_01.srt`
- 輸出檔案：依 `config/file_handler_config.json` 的 `batch_settings.name_pattern` 產生（預設為 `episode_01_繁體中文.srt`）

### 範例 2：批量翻譯多個檔案

1. **選擇多個檔案**：
   - 方法 A：按住 Ctrl（Windows）或 Cmd（macOS）選擇多個檔案
   - 方法 B：直接拖放資料夾到視窗（自動載入所有 SRT 檔案）

2. **設定參數**：
   - 源語言：英文
   - 目標語言：繁體中文
   - LLM 類型：ollama
   - 模型：llama3.2
   - 並發數：3（本地模型建議較低）
   - 顯示模式：僅顯示翻譯

3. **開始翻譯**：程式會依序處理每個檔案

4. **查看結果**：
   ```
   episode_01.srt → episode_01_繁體中文.srt
   episode_02.srt → episode_02_繁體中文.srt
   episode_03.srt → episode_03_繁體中文.srt
   ```

### 範例 3：使用結構-文本分離模式（CLI）

1. **準備命令**：
   ```bash
   srt-translator translate episode_01.srt \
     -s 英文 \
     -t 繁體中文 \
     -p openai \
     -m gpt-4o \
     --structure-text
   ```

2. **適用情境**：
   - 想減少 API 呼叫次數
   - 想降低 LLM 改壞 timestamp / index 的風險
   - 想在大批次字幕上維持 1:1 行數驗證

3. **注意事項**：
   - 這是實驗性功能
   - 若行數不匹配，系統會自動重試，必要時退回逐條翻譯模式

### 範例 4：自訂提示詞

1. **開啟提示詞編輯器**
   - GUI 選單：`設定` → `提示詞編輯`
2. **選擇內容類型**：
   - general：一般內容
   - anime：動畫內容
   - movie：電影內容
   - english_drama：英語劇集
   - adult：成人內容
3. **選擇翻譯風格**：
   - standard：標準翻譯
   - literal：直譯
   - localized：本地化
   - specialized：專業術語保留
4. **編輯提示詞**：根據需求調整提示詞內容
5. **儲存並使用**：提示詞會立即生效

---

## 進階功能

### 顯示模式詳解

> **介面差異**：
> - GUI 提供四種模式：`雙語對照`、`僅顯示翻譯`、`翻譯在上`、`原文在上`
> - CLI 目前提供三種模式：`雙語對照`、`僅譯文`、`僅原文`
> - CLI 與 GUI 的顯示模式命名目前尚未完全對齊；若你需要四種模式的精確控制，請優先使用 GUI

#### 1. 僅顯示翻譯

**適用場景**：只需要翻譯結果，不需要原文

**輸出範例**：
```srt
1
00:00:01,000 --> 00:00:03,000
你好，世界！
```

#### 2. 雙語對照

**適用場景**：學習語言、對照翻譯品質

**輸出範例**：
```srt
1
00:00:01,000 --> 00:00:03,000
Hello, world!
你好，世界！
```

#### 3. 翻譯在上

**適用場景**：優先閱讀翻譯

**輸出範例**：
```srt
1
00:00:01,000 --> 00:00:03,000
你好，世界！
Hello, world!
```

#### 4. 原文在上

**適用場景**：優先閱讀原文

**輸出範例**：
```srt
1
00:00:01,000 --> 00:00:03,000
Hello, world!
你好，世界！
```

### 快取系統

#### 快取行為

- **自動快取**：翻譯結果會自動儲存到快取
- **快取命中**：相同文本和上下文會直接從快取讀取
- **模型區分**：不同模型的翻譯結果分別快取
- **有效期限**：預設 30 天（可在配置中調整）

#### 快取位置

```
data/
└── translation_cache.db  # SQLite 資料庫
```

#### 清理快取

```bash
# 刪除快取檔案
rm data/translation_cache.db

# 或在配置中設定自動清理
```

### 並發處理優化

#### 並發數建議

| AI 引擎 | 建議並發數 | 理由 |
|---------|-----------|------|
| **Ollama** | 1-3 | 受限於本地 GPU/CPU 資源 |
| **OpenAI** | 3-6 | 速率限制較嚴格，建議保守 |
| **Google（GUI）** | 3-8 | 速率限制適中 |

> `anthropic` 目前尚無第一級翻譯 runtime，因此不列入並發建議。

#### 自動調整

程式會根據檔案大小自動調整批次處理策略：

- **小檔案**（< 50 字幕）：單批次處理
- **中檔案**（50-200 字幕）：分批處理
- **大檔案**（> 200 字幕）：分多批次 + 進度儲存

### 檔案衝突處理

當輸出檔案已存在時，程式會詢問：

1. **覆蓋**：直接覆蓋現有檔案
2. **重新命名**：自動在檔名後加上時間戳記
   - 範例：`episode_01.zh_tw_1.srt`（實際格式取決於 `name_pattern` 與衝突處理設定）
3. **跳過**：跳過此檔案，繼續處理下一個

---

## 配置說明

### 配置檔案位置

所有配置檔案位於 `config/` 目錄：

```
config/
├── app_config.json           # 應用程式配置
├── user_settings.json        # 使用者設定
├── prompt_config.json        # 提示詞配置
├── model_config.json         # 模型配置
├── file_handler_config.json  # 檔案處理配置
└── cache_config.json         # 快取配置
```

### 常用配置項

#### app_config.json

```json
{
  "version": "1.0.0",
  "debug_mode": false,
  "data_dir": "data",
  "checkpoints_dir": "data/checkpoints",
  "logs_dir": "logs",
  "cache_expiry": 30,
  "last_update": "2026-03-13T00:00:00"
}
```

#### user_settings.json

```json
{
  "source_lang": "英文",
  "target_lang": "繁體中文",
  "llm_type": "openai",
  "model_name": "",
  "parallel_requests": 3,
  "display_mode": "僅顯示翻譯",
  "auto_save": true,
  "play_sound": true,
  "theme": "default"
}
```

> 若手動編輯 `user_settings.json`，請注意 `ConfigManager` 目前只接受 `llm_type = "ollama"` 或 `"openai"`；GUI 雖然會顯示 `anthropic` / `google`，但設定驗證層尚未完全對齊。

#### cache_config.json

```json
{
  "cache_enabled": true,
  "cache_expiry_days": 30,
  "max_cache_size_mb": 500,
  "auto_cleanup": true
}
```

#### theme_settings.json

GUI 主題配色設定（Arctic Night 深色主題）：

```json
{
  "colors": {
    "primary": "#7DCFFF",
    "secondary": "#89DDFF",
    "background": "#1A1B26",
    "surface": "#24283B",
    "text": "#C0CAF5",
    "accent": "#BB9AF7",
    "success": "#9ECE6A",
    "danger": "#F7768E",
    "warning": "#E0AF68"
  },
  "theme": "arctic_night"
}
```

> 可自訂顏色值來調整介面配色，修改後重新啟動程式生效。

### 修改配置

配置會在使用者操作時自動儲存，也可以手動編輯 JSON 檔案：

```bash
# 編輯使用者設定
nano config/user_settings.json

# 或使用文字編輯器
code config/user_settings.json
```

---

## 故障排除

### 常見問題

#### 1. 程式無法啟動

**問題**：執行 `uv run srt-translator` 沒有反應

**可能原因**：
- Python 版本不符
- 依賴未正確安裝
- 環境變數問題

**解決方案**：
```bash
# 檢查 Python 版本
python --version  # 應為 3.10+

# 重新安裝依賴
uv sync --all-extras --dev

# 嘗試直接執行
python -m srt_translator
```

#### 2. API 錯誤

**問題**：顯示「API 呼叫失敗」錯誤

**可能原因**：
- API 金鑰無效
- 網路連接問題
- API 配額用盡

**解決方案**：
```bash
# 檢查環境變數
printenv OPENAI_API_KEY

# 若你仍使用舊式金鑰檔案，再檢查檔案內容
cat openapi_api_key.txt

# 測試網路連接
ping api.openai.com

# 檢查 API 配額（OpenAI 為例）
# 前往 https://platform.openai.com/usage
```

#### 3. Ollama 連接失敗

**問題**：「無法連接到 Ollama 服務」

**解決方案**：
```bash
# 確認 Ollama 正在運行
ps aux | grep ollama

# 啟動 Ollama
ollama serve

# 測試連接
curl http://localhost:11434/api/tags
```

#### 4. 翻譯結果異常

**問題**：翻譯結果不完整或格式錯誤

**可能原因**：
- 提示詞設定不當
- 模型選擇不適合
- 並發數過高導致 API 限制

**解決方案**：
1. 降低並發數（改為 1-2）
2. 嘗試不同模型
3. 檢查並調整提示詞
4. 清除快取後重試：`rm data/translation_cache.db`

#### 5. 檔案編碼問題

**問題**：字幕顯示為亂碼

**解決方案**：
```bash
# 檢查檔案編碼
file -bi input.srt

# 轉換編碼為 UTF-8
iconv -f GBK -t UTF-8 input.srt > input_utf8.srt
```

### 日誌檢查

查看日誌以獲得更多診斷資訊：

```bash
# 應用程式主日誌
cat logs/app.log

# 配置管理器日誌
cat logs/config_manager.log

# 服務日誌
cat logs/services.log

# 翻譯日誌
cat logs/translation.log
```

---

## FAQ

### Q1：支援哪些字幕格式？

**A**：目前支援：
- SRT（主要支援）
- VTT（實驗性支援）
- ASS/SSA（實驗性支援）

### Q2：可以離線使用嗎？

**A**：使用 Ollama 本地模型可以完全離線使用，但首次需要連網下載模型。

### Q3：翻譯速度有多快？

**A**：速度取決於多個因素：

| 因素 | 影響 |
|------|------|
| **AI 引擎** | Ollama（本地）最快，API 需網路往返 |
| **字幕數量** | 越多越慢，但可透過並發優化 |
| **並發數** | 適當提高並發可顯著加速 |
| **快取命中** | 命中快取可立即回傳結果 |

**建議做法**：
- 先用 10-20 條字幕的小樣本測試
- Ollama 的速度主要取決於本機硬體與模型大小
- 雲端 provider 的速度則受網路、速率限制與模型負載影響

### Q4：翻譯品質如何？

**A**：品質主要取決於三件事：

- 模型本身是否擅長字幕翻譯
- 內容類型與提示詞是否選對
- 並發數是否過高而導致輸出不穩定

若你要先求穩定，建議從 `openai` 或 `ollama` 的小樣本測試開始，再依內容類型調整 prompt。

### Q5：費用如何計算？

**A**：
- **Ollama（本地）**：不收 API 費，但需要自備本機運算資源
- **雲端 provider**：通常依 token 計費，且價格與模型名稱常變動

> 建議直接查看各 provider 官方價格頁。這部分變動頻繁，不建議把文件中的估算值當成最新報價。

### Q6：可以翻譯多種語言嗎？

**A**：是的，支援以下語言對：

**源語言**：日文、英文、韓文、法文、德文、西班牙文、俄文、繁體中文

**目標語言**：繁體中文、英文、日文、韓文

**最佳支援**：日文 → 繁體中文、英文 → 繁體中文

> **注意**：如需繁體中文與簡體中文互轉，建議使用專業的 [OpenCC](https://github.com/BYVoid/OpenCC) 工具，轉換效果更佳且免費。

### Q7：翻譯結果可以編輯嗎？

**A**：翻譯後的 SRT 檔案是純文字格式，可以使用任何文字編輯器或專業字幕編輯器（如 Aegisub）編輯。

### Q8：如何提升翻譯品質？

**A**：建議：
1. 選擇更好的模型（GPT-4o / GPT-4，或 GUI 的 Gemini 2.x）
2. 調整提示詞以符合內容類型
3. 選擇適合的翻譯風格
4. 提供更多上下文（使用較低的並發數）
5. 人工後期校對

---

## 最佳實踐

### 1. 翻譯前準備

- ✅ 確認源字幕檔案編碼為 UTF-8
- ✅ 檢查字幕時間軸是否正確
- ✅ 移除不必要的標記或特殊字符
- ✅ 備份原始檔案

### 2. 參數選擇建議

| 內容類型 | 推薦模型 | 並發數 | 顯示模式 |
|---------|---------|--------|---------|
| **動畫** | GPT-4o / GPT-4 / Qwen3.5 | 3-5 | 雙語對照 |
| **電影** | GPT-4o / Gemini 2.x（GUI） | 3-5 | 僅顯示翻譯 |
| **紀錄片** | GPT-3.5-Turbo | 5-8 | 雙語對照 |
| **教學影片** | GPT-3.5-Turbo | 5-10 | 僅顯示翻譯 |

### 3. 品質保證流程

1. **首次翻譯**：使用較好的模型（GPT-4）
2. **快速檢查**：瀏覽翻譯結果，檢查明顯錯誤
3. **局部重譯**：發現問題時，調整提示詞後重新翻譯
4. **人工校對**：專業內容建議人工最終校對
5. **版本控制**：保留多個版本以便比較

### 4. 效能優化

```bash
# 1. 啟用快取
# 在 config/cache_config.json 中：
{
  "cache_enabled": true,
  "cache_expiry_days": 30
}

# 2. 調整並發數
# 根據網路速度和 API 限制動態調整

# 3. 批量處理
# 一次處理多個檔案可以提高整體效率

# 4. 使用快速模型做初稿
# 使用 GPT-3.5 快速生成，再用 GPT-4 精修關鍵部分
```

### 5. 資料管理

```bash
# 定期備份配置
cp -r config config_backup_$(date +%Y%m%d)

# 定期清理日誌
find logs/ -name "*.log" -mtime +30 -delete

# 定期清理快取（可選）
find data/ -name "*.db" -mtime +90 -delete
```

---

## 支援與社群

- **GitHub Issues**：[回報問題](https://github.com/charles1018/srt-subtitle-translator/issues)
- **文檔**：[完整文檔](https://github.com/charles1018/srt-subtitle-translator/docs)
- **Email**：chmadux8@gmail.com

---

**最後更新**：2026-03-12
**版本**：1.1.0+
