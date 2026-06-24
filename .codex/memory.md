# Project Memory

## Current Summary

- 

## Recent Changes

### 

-

## 2026-06-23 AGENTS.md 專案內容更新

- 任務目的：將從其他專案複製而來的 AGENTS.md 後半段改為符合本專案的工作指南。
- 主要修改內容：更新專案概覽、開發流程、優先工作路徑、搜尋原則、常用驗證指令與修改規範，移除 FastAPI / Elasticsearch RAG dashboard 等不屬於本專案的描述。
- 驗證結果：以 `python -m compileall czjLLM/pipeline czjLLM/row_processors czjLLM/utilities` 做語法層級檢查。
- 重要結論：本專案主要是 Python 多來源資料處理與 LLM 多階段分析框架，後續 Agent 應優先查看 pipeline、mode、YAML 設定與 LLM infrastructure 相關路徑。

## 2026-06-24 pending_central Windows file lock compatibility

- 任務目的：修正 Windows 執行 `python -m czjLLM.czjLLM_TextProcessing --config yaml/sqlserver_json_multistage_langroute_config.yaml` 時，`czjLLM.prompt_pipeline.pending_central` 在 import 階段直接載入 POSIX-only `fcntl` 導致 `ModuleNotFoundError` 的問題。
- 主要修改內容：將 `pending_central.py` 的鎖檔實作改為依 `os.name` 選擇 Windows `msvcrt.locking` 或 POSIX `fcntl.flock`，避免 Windows import 階段載入 `fcntl`，並保留 JSON console 原子更新流程。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pending_central.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py` 通過 3 tests；額外執行 `from czjLLM.prompt_pipeline import pending_central` 與 AST 檢查確認無 top-level `fcntl` import。
- 重要結論：pending running console 現在可在 Windows 與 POSIX 平台共用同一模組 import 路徑；Windows 實際鎖檔行為仍需於 Windows 環境以原始 SQL Server 多階段命令做端到端驗證。

## 2026-06-24 pending running console schedule noop release and local time log

- 任務目的：修正 SQL/Table/ES stream producer 已撈到 pending rows 時，若 `schedule_one_row` 未建立可執行任務或丟出例外，該 pk 可能持續留在 pending running console，造成其他程序一直延後同一列並出現「有撈到應跑任務但未繼續跑」的風險；同時將 `pending_running_console_adjustments.log` 時間格式改為比照 `pending_recheck_skips.log` 的本地時區 ISO 時間。
- 主要修改內容：`record_adjustment` 現在寫入本地時區 `ts` 與 `timezone`；producer 只在 `schedule_one_row` 回傳正數 chunk 時納入 scheduled，回傳 0/None/非數值或例外時會釋放 running console 標記並寫入 `schedule_noop_release` / `schedule_error_release`。
- 驗證結果：`python -m compileall czjLLM/prompt_pipeline/pending_central.py czjLLM/sql_mode/runtime/producer.py` 通過；`python -m pytest tests/sql_mode/runtime/test_pending_central.py tests/sql_mode/runtime/test_producer_pending_recheck.py` 通過可執行測試（部分測試因缺少 optional dependency 仍被既有 `pytest.importorskip` skip）。
- 重要結論：pending running console 不再因切片/排程未產生任務而永久保留 running 狀態；調整記錄 log 可直接以當地時間比對 pending recheck skip log。
