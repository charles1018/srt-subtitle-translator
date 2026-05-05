# 依賴維護指引

> 本文件說明本專案在升級依賴時的風險分級、驗證順序與已知限制。

## 原則

- 以 [pyproject.toml](/home/chares/dev/tools/claude/srt-subtitle-translator/pyproject.toml) 為依賴宣告真相來源。
- 以 [uv.lock](/home/chares/dev/tools/claude/srt-subtitle-translator/uv.lock) 為實際鎖定版本。
- [requirements.txt](/home/chares/dev/tools/claude/srt-subtitle-translator/requirements.txt) 只維護 runtime 依賴，不承載開發工具鏈。
- provider 行為若與文件衝突，優先以 `src/` 實作為準。

## 風險分級

### 高風險 runtime 依賴

這些套件直接影響翻譯執行路徑，升級後必須優先驗證：

- `openai`
  - 影響 `openai` runtime
  - 也影響 `llamacpp` 的 OpenAI 相容 API 路徑
- `google-genai`
  - 影響 `google` runtime
- `aiohttp`
  - 影響本地 provider 健康檢查、模型探測、部分網路連線與 session 行為

對應重點模組：

- [src/srt_translator/translation/client.py](/home/chares/dev/tools/claude/srt-subtitle-translator/src/srt_translator/translation/client.py)
- [src/srt_translator/core/models.py](/home/chares/dev/tools/claude/srt-subtitle-translator/src/srt_translator/core/models.py)
- [src/srt_translator/services/factory.py](/home/chares/dev/tools/claude/srt-subtitle-translator/src/srt_translator/services/factory.py)

### 中風險 runtime 依賴

- `pysrt`
- `webvtt-py`
- `tkinterdnd2`
- `psutil`
- `tiktoken`
- `python-dotenv`

這些依賴多半影響字幕解析、GUI 邊界功能、token 計算或環境配置載入，通常不需要全量 provider 驗證，但要跑相對應測試。

### 低風險開發依賴

- `pytest`
- `pytest-cov`
- `pytest-asyncio`
- `pytest-mock`
- `ruff`
- `mypy`

這些主要影響開發體驗與 CI 穩定性，通常先升這批最安全。

## 驗證順序

### 1. 工具鏈升級

先跑：

```bash
uv sync --all-extras --dev
uv run ruff check .
uv run pytest -m "not gui"
```

### 2. provider 核心升級

若升級 `openai`、`google-genai`、`aiohttp`，至少跑：

```bash
uv run pytest tests/unit/translation/test_client.py tests/unit/core/test_models.py tests/unit/core/test_models_extended.py tests/unit/services/test_factory.py tests/unit/test_cli.py -q
uv run pytest -m "not gui" tests/unit/core/test_config.py tests/unit/core/test_prompt.py tests/integration/test_config_integration.py -q
```

### 3. 字幕與編碼相關升級

若升級 `pysrt`、`webvtt-py`、`chardet`，至少補跑：

```bash
uv run pytest tests/unit/file_handling tests/unit/tools/test_srt_tools.py tests/e2e/test_translation_workflow.py -q
```

## `chardet` 限制

目前 `chardet` 維持在 `<6`：

- 現行實測中，較新的 `chardet` 版本會與 `requests` 的支援範圍產生相容性警告。
- 這個專案主要把 `chardet` 用在字幕編碼偵測，沒有必要為了追最新版本去承擔額外噪音。
- 若未來要重新放寬版本，請先驗證：
  - `uv run pytest -m "not gui"`
  - `uv run pytest tests/unit/file_handling tests/unit/tools/test_srt_tools.py -q`
  - 確認測試過程沒有 `RequestsDependencyWarning`

## 升級流程建議

1. 先更新 [pyproject.toml](/home/chares/dev/tools/claude/srt-subtitle-translator/pyproject.toml)
2. 再同步 [requirements.txt](/home/chares/dev/tools/claude/srt-subtitle-translator/requirements.txt) 的 runtime 依賴
3. 執行 `uv lock`
4. 執行 `uv sync --all-extras --dev`
5. 依上方風險分級跑對應測試
6. 補齊必要文件與 `CHANGELOG`

## 不建議的做法

- 不要只改 `requirements.txt` 而不改 `pyproject.toml`
- 不要在未更新 lock 的情況下宣稱已完成升級
- 不要把 provider 文件敘述當成 runtime 真相來源
- 不要把高風險 provider 升級和大範圍功能改動混在同一個 commit
