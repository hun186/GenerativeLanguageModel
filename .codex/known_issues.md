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
