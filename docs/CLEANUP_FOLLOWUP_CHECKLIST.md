# Cleanup Follow-up Checklist

狀態：待執行

建立日期：2026-05-19（Asia/Taipei）

目的：

- 延續前一份已封存的 `docs/CLEANUP_CHECKLIST.md`
- 整理本次 repo 巡檢後仍存在的高訊號未收尾項目
- 優先修正「已確認的不一致、已知缺陷、可穩定補上的測試保護」

範圍原則：

- 以 `src/` 內實際行為為準，文件與測試需回補到一致
- 不重新打開已移除的 legacy provider / key-loading 路徑
- 預設維持離線測試；不引入需要真實 API 金鑰的驗證
- 每個階段都應可獨立提交，避免把文件修正、行為修正、測試重構全部混在同一個 commit

目前已確認的訊號：

- `docs/ENGLISH_DRAMA_GUIDE.md` 仍描述 CLI 沒有 `--content-type`，但 `src/srt_translator/cli.py` 已支援
- `ConfigManager.restore_backup()` 仍有同秒備份檔名衝突風險，對應測試目前跳過
- `check_python_packages()` 仍依賴 `pkg_resources`，對 Python 3.13+ 相容性不完整
- Netflix 後處理對 curly quotes 的支援未完成，對應測試目前跳過
- 尚有一批以「complex setup」或「需要根據實作調整」為理由的 skipped tests
- `tests/e2e/test_config_integration.py` 仍有 `AsyncMock` 未正確 awaited 的 warning

建議基線：

```bash
uv run pytest -m "not gui" -q
uv run ruff check .
```

## 階段 1：先修正文檔漂移與低風險一致性問題

- [ ] 修正 `docs/ENGLISH_DRAMA_GUIDE.md` 中關於 CLI `--content-type` / `--llm-type` 的過時描述
- [ ] 重新檢查 `english_drama` 範例指令是否與 `src/srt_translator/cli.py` 的實際參數一致
- [ ] 修正 `README.md` 內「未來規劃」與現況衝突的術語表/術語庫描述，避免把已存在功能寫成未完成
- [ ] 順手掃描其他高流量文件是否還殘留同類型 drift，至少包含 `README.md`、`docs/USER_GUIDE.md`、`docs/DEVELOPMENT.md`

驗證：

- 文件中的 CLI 範例可對上 `src/srt_translator/cli.py`
- provider / prompt / content-type 說明不再和目前 code reality 衝突
- 不新增任何超出目前實作範圍的承諾文字

建議 commit：

- `docs(repo): align english drama and glossary docs with current cli reality`

## 階段 2：修正 Config 備份還原的已知缺陷

- [ ] 修正 `ConfigManager.create_backup()` 的備份命名策略，避免秒級時間戳造成覆蓋
- [ ] 確認 `restore_backup()` 在「先備份目前狀態，再還原指定備份」流程下不會誤蓋原始備份
- [ ] 補回 `tests/unit/core/test_config_extended.py::test_restore_backup_success`
- [ ] 視實作方式補一個明確 regression test，覆蓋同秒連續備份或 restore 前後檔名唯一性

驗證：

- `uv run pytest tests/unit/core/test_config.py tests/unit/core/test_config_extended.py -q`
- 原本 skip 的 restore backup 測試改為正式通過
- 備份目錄中不再出現 restore 流程覆蓋輸入備份的情況

建議 commit：

- `fix(config): prevent backup filename collisions during restore`

## 階段 3：補齊 Python 3.13+ 相容性缺口

- [ ] 將 `check_python_packages()` 從 `pkg_resources` 遷移到 `importlib.metadata` 為主的實作
- [ ] 保留必要 fallback，但不要再讓 `pkg_resources` 成為主要依賴
- [ ] 取消 `tests/unit/utils/test_helpers_extended.py::test_check_python_packages` 的 skip
- [ ] 檢查相關文件是否仍暗示舊版 setuptools / `pkg_resources` 是既定前提

驗證：

- `uv run pytest tests/unit/utils/test_helpers.py tests/unit/utils/test_helpers_extended.py -q`
- Python 3.11 與 3.13+ 的行為預期一致
- 不再需要以 skip 規避 `pkg_resources` 缺失

建議 commit：

- `fix(utils): migrate package version inspection away from pkg_resources`

## 階段 4：補完 Netflix 後處理的 curly quote 支援

- [ ] 讓 `NetflixStylePostProcessor` 正確處理 `U+201C/U+201D` curly quotes
- [ ] 檢查現有 `QUOTE_MAP` 寫法，移除重複或無效項目，讓意圖更清楚
- [ ] 取消 `tests/unit/utils/test_post_processor.py::test_fix_curly_quotes` 的 skip
- [ ] 確認與既有半形單引號/雙引號轉換邏輯不互相干擾

驗證：

- `uv run pytest tests/unit/utils/test_post_processor.py -q`
- curly quotes、半形 quotes、混合引號案例皆通過

建議 commit：

- `fix(post-processor): support curly quote normalization`

## 階段 5：清理剩餘高訊號 skipped tests

- [ ] 先處理 `tests/integration/test_config_integration.py` 內直接註明「需要根據 ConfigManager 實際實現調整」的兩個案例
- [ ] 評估 `tests/unit/translation/test_client.py` 兩個「Complex async mock setup needed」案例，若可穩定 mock 就補回
- [ ] 盤點 `tests/unit/translation/test_manager.py` 內的大量 placeholder tests，優先挑初始化、checkpoint、pause/resume 這些有明確 public behavior 的案例
- [ ] 盤點 `tests/unit/file_handling/test_handler.py` 中 directory scan / output path 相關 skip，確認是否可透過 fixture 降低 singleton setup 成本
- [ ] 盤點 `tests/unit/services/test_factory.py` 中 `TranslationTask` placeholder tests，確認是否應補測、移除，或降級為較小單元

驗證：

- skipped tests 數量下降，且是以補正式測試取代 skip，而非直接刪測
- 新增測試維持離線、穩定、不依賴真實 provider
- 若有保留 skip，理由需具體到無法在目前架構下低成本解決

建議 commit：

- `test(config): replace multi-instance skip placeholders`
- `test(translation): cover manager and client skipped scenarios`
- `test(file-handling): replace singleton setup skip placeholders`

## 階段 6：清掉目前測試基線 warning

- [ ] 修正 `tests/e2e/test_config_integration.py` 內 `AsyncMock` return value 的寫法，消除 `coroutine was never awaited`
- [ ] 確認 warning 消失後，不會改壞既有 e2e 測試語意

驗證：

- `uv run pytest tests/e2e/test_config_integration.py -q`
- `uv run pytest -m "not gui" -q` 不再出現相同 warning

建議 commit：

- `test(e2e): remove unawaited async mock warning`

## 收尾檢查

- [ ] `uv run pytest -m "not gui" -q`
- [ ] `uv run ruff check .`
- [ ] 視變更範圍補跑最接近的 targeted tests
- [ ] 若有改動使用者可見行為，同步更新 `README.md`、`docs/USER_GUIDE.md`、`docs/API.md` 或 `docs/DEVELOPMENT.md`

完成條件：

- 已知文件 drift 消失
- `restore_backup` 已知缺陷修正並有 regression test
- Python 3.13+ 套件檢查相容性補齊
- curly quotes 支援完成
- skipped tests 與 warning 數量進一步下降，且理由更聚焦
