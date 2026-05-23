# Cleanup Status

狀態：已完成

最後更新：2026-05-23（Asia/Taipei）

本文件是 cleanup 工作的唯一 current status。

原則：

- 以 `src/` 內實際行為為準
- 不重新引入已移除的 legacy provider 或舊 key-loading 路徑
- 預設維持離線測試

## 目前結論

- provider/runtime cleanup 已完成
- 文件、測試與目前 shipped behavior 已對齊到 `llamacpp` / `openai` / `google`
- 非 GUI 基線目前為 `955 passed / 0 skipped / 0 warnings`

## 本輪完成重點

- 清除最後一批高訊號 skipped tests
  - `tests/unit/translation/test_manager.py`
  - `tests/unit/services/test_factory.py`
- 更新高流量文件與 API 文件，使其符合目前 CLI / provider / key-loading reality
- 更新 `.env.example`、`docs/TESTING.md`、`CONTRIBUTING.md`、llama.cpp 相關指南

## 驗證基線

```bash
uv run pytest tests/unit/translation/test_manager.py tests/unit/services/test_factory.py -q
uv run pytest -m "not gui" -q
uv run ruff check .
```

最近確認結果：

- targeted 單元測試：`126 passed`
- 非 GUI 全量基線：`955 passed / 0 skipped / 0 warnings`
- `ruff check .`：通過

## 封存文件

舊 checklist 已移到封存目錄，不再作為 current status 維護：

- `docs/archive/cleanup/2026-05-cleanup-checklist.md`
- `docs/archive/cleanup/2026-05-cleanup-followup.md`

## 後續規則

- 若未來還有 cleanup 工作，直接更新本文件
- 只有在需要保留完整歷史脈絡時，才另外新增封存文件到 `docs/archive/cleanup/`
