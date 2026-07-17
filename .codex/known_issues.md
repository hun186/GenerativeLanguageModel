# 已知問題（Known Issues）

## <問題名稱>

首次發現：

問題：

影響：

暫時解法：

根本原因：

狀態：
Open

負責人：

---

## 測試期間 datetime.utcnow DeprecationWarning

首次發現：

問題：

- 

影響：

- 

暫時解法：

- 

根本原因：

- 

狀態：


負責人：

-


---

## requirements.txt git dependency installation blocked by network proxy

首次發現：2026-06-24

問題：依專案指示執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt` 時，`requirements.txt` 中的 GitHub dependency `peft @ git+https://github.com/huggingface/peft.git@...` clone 失敗，錯誤為 `CONNECT tunnel failed, response 403`。

影響：本次無法在乾淨環境完整安裝所有 requirements；只能使用目前容器已具備的套件執行目標模組語法檢查與既有單元測試。

暫時解法：先執行不需下載額外 GitHub dependency 的 `compileall`、目標單元測試與 import/AST 檢查；需要完整依賴時，改在可連 GitHub 的環境安裝，或改用可用的內部 mirror / wheelhouse。

根本原因：目前執行環境對 GitHub HTTPS tunnel 回傳 403，屬外部網路／proxy 限制。

狀態：Open

負責人：-

## pytest producer pending recheck skipped without PyYAML

首次發現：2026-06-25

問題：執行 `python -m pytest -rs tests/sql_mode/runtime/test_producer_pending_recheck.py` 時，測試檔透過 `pytest.importorskip("yaml")` 因目前環境缺少 `yaml` / PyYAML 而全部 skip，pytest 回傳 exit code 5。

影響：本次只能以 `test_pending_central.py` 覆蓋 pending console 純函式與檔案行為；producer pending recheck 整合測試需在 PyYAML 可用環境執行。

暫時解法：在可完整安裝 requirements 的環境安裝 PyYAML 後重跑該測試；目前 requirements 安裝仍受 GitHub dependency proxy 403 限制。

根本原因：目前容器依賴不完整，且完整 requirements 安裝受外部網路限制。

狀態：Open

負責人：-

## prompt pipeline DI test collection blocked by missing tqdm after requirements install failure

首次發現：2026-07-15

問題：執行 `python -m pytest tests/prompt_pipeline/test_process_prompt_and_merge_di.py tests/sql_mode/runtime/test_pending_central.py` 時，`tests/prompt_pipeline/test_process_prompt_and_merge_di.py` import `czjLLM.prompt_pipeline.pipeline_controller` 失敗，原因為目前環境缺少 `tqdm`。依專案規範先執行 `python -m pip install --upgrade pip && python -m pip install -r requirements.txt`，但安裝流程仍因 proxy 對 PyPI/GitHub tunnel 回傳 403 而失敗。

影響：本次無法在目前容器收集/執行依賴完整 runtime package 的 prompt pipeline DI 測試；只能以 `compileall`、新拆出 helper 的單元測試、以及不依賴缺失套件的 pending central 測試驗證。

暫時解法：在可安裝完整 requirements 的環境重跑 `python -m pytest tests/prompt_pipeline/test_process_prompt_and_merge_di.py tests/sql_mode/runtime/test_pending_central.py`；目前容器先以 `python -m compileall czjLLM/prompt_pipeline` 與 `python -m pytest tests/prompt_pipeline/test_extracted_helpers.py tests/sql_mode/runtime/test_pending_central.py` 替代。

根本原因：目前容器無法透過 proxy 取得部分 PyPI/GitHub dependency，且環境未預裝 `tqdm`。

狀態：Open

負責人：-

## Windows multiprocessing DuplicateHandle in legacy single-stage LLM round

首次發現：2026-07-17

問題：Windows 執行舊版單階段 YAML（例如 ES mode）時，legacy consumer 的 `run_round()` 使用 `multiprocessing.Pool`；在 spawn 子程序階段可能於 `multiprocessing.connection.rebuild_pipe_connection()` / `_winapi.DuplicateHandle()` 觸發 `PermissionError: [WinError 5] 存取被拒`。

影響：LLM API 已回傳成功後，合併/寫回階段可能因 worker pool crash 而中斷；Linux fork-based 執行路徑未重現。

暫時解法：此方向已被後續「debug-first rollback」取代；目前不再預設改用 thread pool，改以 `CZJLLM_LLM_ROUND_DEBUG=1` 先收集 multiprocessing 診斷。

根本原因：Windows multiprocessing spawn 需要 pickle job 與 duplicate IPC handle；在使用者環境中該 handle duplication 被 OS / 權限 / 安全軟體或父子程序狀態阻擋。LLM API round 為 I/O-bound，無需依賴多程序 CPU 平行。

狀態：Superseded by debug-first investigation

負責人：-

## Windows legacy single-stage WinError 5 root-cause investigation pending

首次發現：2026-07-17

問題：使用者指出 Windows 舊版單階段任務過去也使用 multiprocessing 並未發生 `PermissionError: [WinError 5]`，近期修改後才出現；因此目前不能直接判定 multiprocessing 本身就是根因。

影響：若只改用 thread pool 可能掩蓋真正原因，例如 pool lifecycle、job pickling payload、child import side effect、parent process handle state、watchdog/consumer 重啟流程或安全軟體互動。

暫時解法：已撤回 Windows 預設 thread pool 行為，新增 `CZJLLM_LLM_ROUND_DEBUG=1` 診斷；請在 Windows 以同一 YAML 重跑並保留完整 `[round-debug]` log、crash stack、第一輪/第幾輪發生、`n_process`、Python/conda 版本與是否在同一 cmd 視窗連續重跑。

根本原因：待釐清。

狀態：Open

負責人：-
