# 使用者指南

> SRT Subtitle Translator 完整使用指南

## 目錄

- [快速開始](#快速開始)
- [詳細安裝指南](#詳細安裝指南)
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

1. **Python 環境**：Python 3.8 或更高版本
2. **網路連接**：使用 API 模式時必須
3. **AI 服務**（擇一）：
   - Ollama（本地）
   - OpenAI API 金鑰
   - Anthropic API 金鑰

### 5 分鐘快速上手

```bash
# 1. 安裝
git clone https://github.com/charles1018/srt-subtitle-translator.git
cd srt-subtitle-translator
uv sync --all-extras --dev

# 2. 設定 API 金鑰（OpenAI 為例，擇一方式）
# 方式 A：環境變數（推薦）
export OPENAI_API_KEY="your-api-key"
# 方式 B：金鑰檔案
echo "your-api-key" > openapi_api_key.txt

# 3. 啟動
uv run srt-translator

# 4. 在介面中選擇檔案、設定參數、開始翻譯！
```

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

#### OpenAI

1. 前往 [OpenAI Platform](https://platform.openai.com/api-keys)
2. 建立新的 API 金鑰
3. 設定金鑰（擇一方式）：

**方法 1：環境變數（推薦）**
```bash
# Linux/macOS
export OPENAI_API_KEY="sk-your-openai-api-key"

# Windows PowerShell
$env:OPENAI_API_KEY="sk-your-openai-api-key"

# Windows CMD
set OPENAI_API_KEY=sk-your-openai-api-key
```

**方法 2：金鑰檔案**
```bash
echo "sk-your-openai-api-key" > openapi_api_key.txt
```

#### Anthropic

1. 前往 [Anthropic Console](https://console.anthropic.com/settings/keys)
2. 建立新的 API 金鑰
3. 設定金鑰（擇一方式）：

**方法 1：環境變數（推薦）**
```bash
# Linux/macOS
export ANTHROPIC_API_KEY="sk-ant-your-anthropic-api-key"

# Windows PowerShell
$env:ANTHROPIC_API_KEY="sk-ant-your-anthropic-api-key"

# Windows CMD
set ANTHROPIC_API_KEY=sk-ant-your-anthropic-api-key
```

**方法 2：金鑰檔案**
```bash
echo "sk-ant-your-anthropic-api-key" > anthropic_api_key.txt
```

> **安全提示**：環境變數優先於金鑰檔案。建議使用環境變數，避免將金鑰意外提交到版本控制。

#### Ollama

1. 前往 [Ollama 官網](https://ollama.ai) 下載並安裝
2. 啟動 Ollama 服務：

```bash
ollama serve
```

3. 拉取模型（例如 llama2）：

```bash
ollama pull llama2
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
│  模型: [llama2 ▼]                           │
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
| **LLM 類型** | 選擇 AI 引擎（ollama/openai/anthropic）|
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
- 輸出檔案：`episode_01_zh-TW.srt`

### 範例 2：批量翻譯多個檔案

1. **選擇多個檔案**：
   - 方法 A：按住 Ctrl（Windows）或 Cmd（macOS）選擇多個檔案
   - 方法 B：直接拖放資料夾到視窗（自動載入所有 SRT 檔案）

2. **設定參數**：
   - 源語言：英文
   - 目標語言：繁體中文
   - LLM 類型：ollama
   - 模型：llama2
   - 並發數：3（本地模型建議較低）
   - 顯示模式：僅顯示翻譯

3. **開始翻譯**：程式會依序處理每個檔案

4. **查看結果**：
   ```
   episode_01.srt → episode_01_zh-TW.srt
   episode_02.srt → episode_02_zh-TW.srt
   episode_03.srt → episode_03_zh-TW.srt
   ```

### 範例 3：使用 Anthropic Claude

1. **設定 API 金鑰**（擇一方式）：
   ```bash
   # 方式 A：環境變數（推薦）
   export ANTHROPIC_API_KEY="sk-ant-your-key"

   # 方式 B：金鑰檔案
   echo "sk-ant-your-key" > anthropic_api_key.txt
   ```

2. **在介面中設定**：
   - LLM 類型：anthropic
   - 模型：claude-3-opus-20240229
   - 並發數：10（Anthropic 支援較高並發）

3. **開始翻譯**：Claude 模型通常提供更自然的翻譯結果

### 範例 4：自訂提示詞

1. **點擊「編輯 Prompt」按鈕**（需要在介面中實作）
2. **選擇內容類型**：
   - general：一般內容
   - anime：動畫內容
   - movie：電影內容
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
| **Anthropic** | 5-15 | 速率限制較寬鬆 |

#### 自動調整

程式會根據檔案大小自動調整批次處理策略：

- **小檔案**（< 50 字幕）：單批次處理
- **中檔案**（50-200 字幕）：分批處理
- **大檔案**（> 200 字幕）：分多批次 + 進度儲存

### 檔案衝突處理

當輸出檔案已存在時，程式會詢問：

1. **覆蓋**：直接覆蓋現有檔案
2. **重新命名**：自動在檔名後加上時間戳記
   - 範例：`episode_01_zh-TW_20250128_143022.srt`
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
  "logs_dir": "logs",
  "cache_expiry": 30,
  "max_retries": 3
}
```

#### user_settings.json

```json
{
  "source_lang": "日文",
  "target_lang": "繁體中文",
  "llm_type": "openai",
  "model_name": "gpt-3.5-turbo",
  "parallel_requests": 5,
  "display_mode": "雙語對照",
  "auto_save": true,
  "play_sound": true,
  "theme": "default"
}
```

#### cache_config.json

```json
{
  "cache_enabled": true,
  "cache_expiry_days": 30,
  "max_cache_size_mb": 500,
  "auto_cleanup": true
}
```

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
python --version  # 應為 3.8+

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
# 檢查 API 金鑰
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

**參考數據**（100 條字幕）：
- Ollama（本地）：2-5 分鐘
- OpenAI API：3-8 分鐘（並發 5）
- Anthropic API：2-6 分鐘（並發 10）

### Q4：翻譯品質如何？

**A**：品質取決於選擇的模型：

| 模型 | 品質評級 | 適用場景 |
|------|---------|---------|
| **GPT-4** | ⭐⭐⭐⭐⭐ | 最佳品質，成本較高 |
| **Claude-3-Opus** | ⭐⭐⭐⭐⭐ | 優秀品質，自然流暢 |
| **GPT-3.5-Turbo** | ⭐⭐⭐⭐ | 良好品質，成本適中 |
| **Llama2（本地）** | ⭐⭐⭐ | 可接受，完全免費 |

### Q5：費用如何計算？

**A**：
- **Ollama（本地）**：完全免費，但需要本地運算資源
- **OpenAI**：按 token 計費，約 $0.002-0.02 / 1K tokens
- **Anthropic**：按 token 計費，約 $0.003-0.015 / 1K tokens

**估算**：1 小時動畫（約 400 條字幕）：
- GPT-3.5：約 $0.10-0.30
- GPT-4：約 $1.00-3.00
- Claude-3-Opus：約 $0.50-1.50

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
1. 選擇更好的模型（GPT-4 或 Claude-3-Opus）
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
| **動畫** | Claude-3-Opus / GPT-4 | 3-5 | 雙語對照 |
| **電影** | GPT-4 / Claude-3-Opus | 3-5 | 僅顯示翻譯 |
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

**最後更新**：2025-12-29
**版本**：1.0.0
