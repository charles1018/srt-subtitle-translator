# Cleanup Checklist

本文件整理目前 repo 中已確認的未收尾工作，依建議執行順序拆成可獨立提交的 cleanup 階段。

## 執行原則

- 以 `src/` 內實際行為為準，文件與治理檔案需回補到一致。
- 每完成一個有意義的階段，就建立一個本地 commit 保存工作階段。
- 預設測試維持離線，不引入需要真實 API 金鑰或對外網路的驗證。

## 階段 1：修正 repo 治理指令與當前 reality 不一致

- [x] 更新 `AGENTS.md` 的 Current Phase Focus
- [x] 移除已刪除的 OpenRouter plan 路徑與過時 provider 現況描述
- [x] 將 provider reality 改成與目前 `src/`、`README.md`、`CHANGELOG.md` 一致
- [x] 檢查 `docs/` 清單是否仍引用不存在的檔案

驗證：

- `AGENTS.md` 不再把 OpenRouter 視為進行中主軸
- 檔內 provider 描述需與目前 runtime/CLI/GUI/config reality 一致

## 階段 2：收斂 API 金鑰載入入口，拔除舊 OpenAI-only 路徑

- [x] 移除 `App._load_api_keys()` 對 `FileService.load_api_key()` 的舊依賴
- [x] 移除 `FileService` 與 `FileHandler` 中僅支援 OpenAI 的舊 key loading / saving 介面
- [x] 確保 GUI / runtime 僅透過 `ModelService` / `ModelManager` 的 provider-aware 路徑處理金鑰
- [x] 更新或新增對應單元測試

驗證：

- `src/` 中不再有 GUI 啟動流程直接讀 `openapi_api_key.txt`
- 既有 provider-aware key loading 測試通過

## 階段 3：補齊 GUI 翻譯前置驗證的一致性

- [x] 讓 `openai` / `google` / `llamacpp` 也有 provider-specific preflight
- [x] 遠端 provider 應同時檢查網路、API 金鑰與模型連線結果
- [x] `llamacpp` 應回報 `llama-server` 連線失敗，而不是只走一般網路檢查
- [x] 補齊 `tests/unit/test_main.py` 覆蓋

驗證：

- GUI 對不同 provider 的錯誤訊息可明確指出問題來源
- `tests/unit/test_main.py` 新增案例通過

## 階段 4：清理高訊號的 skipped tests，補回目前行為的測試保護

- [ ] 優先處理 `tests/unit/services/test_factory.py` 中與 `ModelService` / `FileService` 直接相關的 skipped tests
- [ ] 補上 async `ModelService.get_available_models()` 的正式測試
- [ ] 移除已可穩定測試的 skip 佔位
- [ ] 保留仍需大型初始化的測試，但將原因收斂到真正無法解決者

驗證：

- 測試檔中與本次 cleanup 直接相關的 `skip` 數量下降
- 新測試在離線環境下可穩定通過

## 階段 5：移除過時的檔尾手動測試與殘留過渡碼

- [ ] 移除 `translation/client.py` 檔尾只支援 `openai` / `ollama` 的手動測試程式碼
- [ ] 確認不再殘留與目前 provider reality 衝突的過渡入口
- [ ] 視需要補充對應測試或文件註記

驗證：

- `src/` 中不再保留讀取 `openapi_api_key.txt` 的手動 demo/testing 區塊
- `ruff check` 與相關單元測試通過
