# Cleanup Follow-up Checklist

狀態：已完成

最後更新：2026-05-19（Asia/Taipei）

目的：

- 延續已封存的 `docs/CLEANUP_CHECKLIST.md`
- 記錄 follow-up cleanup 的實際完成狀態
- 只保留仍和目前 `src/` 行為對齊有關的剩餘工作

範圍原則：

- 以 `src/` 內實際行為為準，文件與測試需回補到一致
- 不重新引入已移除的 legacy provider 或舊 key-loading 路徑
- 預設維持離線測試；不引入需要真實 API 金鑰的驗證
- provider 現況以 `ollama` / `openai` / `google` / `llamacpp` 為限

## 已完成項目

已推送到 `origin/main`：

- [x] `642b310` `fix(config): align docs and prevent backup restore collisions`
- [x] `fa4c0fa` `fix(utils): migrate package version inspection away from pkg_resources`
- [x] `15b1249` `fix(post-processor): support curly quote normalization`
- [x] `81cc73e` `test(e2e): remove unawaited async mock warning`
- [x] `6279ebf` `test(config): replace multi-instance skip placeholders`
- [x] `b8f0eec` `test(translation): cover client skipped scenarios`
- [x] `1ade142` `test(file-handling): replace singleton setup skip placeholders`

代表下列舊 follow-up 項目已完成：

- [x] `ConfigManager.restore_backup()` 檔名衝突修正與 regression test
- [x] `check_python_packages()` 從 `pkg_resources` 遷移
- [x] Netflix curly quotes 後處理支援
- [x] `tests/e2e/test_config_integration.py` 的 `AsyncMock` warning 清除
- [x] config / file-handling / translation client 先前 placeholder skips 收斂

已知上一個非 GUI 基線（本輪開始前）：

- [x] `944 passed / 18 skipped / 0 warnings`

本輪完成後最新非 GUI 基線：

- [x] `962 passed / 0 skipped / 0 warnings`

## 本輪完成內容整理

### 1. 清理最後一批 skipped tests

本輪開始前剩餘 18 個 skip，集中在兩個檔案；目前已完成：

- [x] `tests/unit/translation/test_manager.py`
- [x] `tests/unit/services/test_factory.py`

處理原則：

- 優先補回 `TranslationManager` 初始化、checkpoint、pause/resume、encoding 等 public behavior 測試
- 補回 `TranslationTask` / `TranslationTaskManager` 可穩定離線測的控制行為
- 若仍保留 skip，理由必須是目前架構下無法低成本穩定驗證，而不是 placeholder

本輪已補回的重點測試：

- [x] `TranslationManager` 初始化、API key、post-process、checkpoint、pause/resume/stop、encoding、lifecycle helper
- [x] `TranslationTask` 初始化、stop、pause/resume

驗證結果：

```bash
uv run pytest tests/unit/translation/test_manager.py tests/unit/services/test_factory.py -q
uv run pytest -m "not gui" -q
```

- [x] targeted 單元測試通過：`126 passed`
- [x] 非 GUI 全量基線通過：`962 passed`

### 2. 再檢查高流量文件 drift

目前 cleanup 主軸已從 provider/runtime 清理轉向文件與實作同步；本輪已完成：

- [x] `README.md`
- [x] `docs/USER_GUIDE.md`
- [x] `docs/DEVELOPMENT.md`
- [x] `docs/ENGLISH_DRAMA_GUIDE.md`

本輪確認重點：

- [x] CLI 範例符合 `src/srt_translator/cli.py`
- [x] provider 敘述不再誤提 legacy scope
- [x] prompt / glossary / content-type 說明未再與現況衝突

## 本輪收尾檢查

- [x] `uv run pytest tests/unit/translation/test_manager.py tests/unit/services/test_factory.py -q`
- [x] `uv run pytest -m "not gui" -q`
- [x] `uv run ruff check .`
- [x] `uv run ruff check docs/CLEANUP_FOLLOWUP_CHECKLIST.md tests/unit/translation/test_manager.py tests/unit/services/test_factory.py`

完成條件：

- [x] `test_manager.py` 與 `test_factory.py` 的 placeholder skip 被正式測試取代
- [x] 非 GUI 基線不再依賴 skip 掩蓋這兩個模組的行為
- [x] cleanup 清單已移除過時待辦，只保留文件同步與全 repo lint 驗證
