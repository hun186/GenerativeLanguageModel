# 技術決策（Technical Decisions）

## Current Summary

- 

## Recent Changes

- 

## Archived History

- 


## 2026-06-25 pending running console is short-lived coordination state

- 決策：`pending_running_console.json` 只保存目前 running 與最近完成/釋放的短期觀察資訊；`last_finished` 預設保留 1 小時，不作為長期完成歷史。
- 理由：pending running console 的目的在於多程序派工前避免撞到正在 running 的 row/file；若保存所有 completed 紀錄，幾萬筆長期批次會造成 JSON 無限制膨脹。
- 後果：若中控檔損毀或被刪除，可重建並恢復後續 running 協調；短時間內可能降低避撞效果，但最終是否派工仍由 pending recheck / 目標輸出狀態決定。

## 2026-07-17 Windows legacy LLM round uses thread pool by default

- 決策：legacy single-stage consumer 的 `run_round()` 在 Windows 且未設定 `CZJLLM_LLM_ROUND_EXECUTOR` 時，使用 thread pool 執行同一輪多個 `PromptAPIPipeline.proc()`；非 Windows 預設仍使用 multiprocessing，且 Windows 可用 `CZJLLM_LLM_ROUND_EXECUTOR=processes` 強制回到舊行為。
- 理由：使用者提供的 Windows stack 顯示 crash 發生於 multiprocessing spawn 子程序 DuplicateHandle，而不是 LLM API、JSON merge 或 ES writeback 本身；LLM round 屬網路 I/O-bound，thread pool 足以維持多 endpoint 並行並避開 Windows handle 權限問題。
- 後果：此決策已被 2026-07-17「debug before changing Windows executor default」取代；目前不再預設改變 Windows executor。

## 2026-07-17 debug before changing Windows executor default

- 決策：撤回「Windows legacy LLM round 預設 thread pool」的行為變更，先保留所有平台 multiprocessing 預設；僅新增 `CZJLLM_LLM_ROUND_DEBUG=1` 診斷輸出。
- 理由：使用者指出舊版單階段任務過去同樣使用 multiprocessing 但沒有 WinError 5，因此較可能是近期 pool lifecycle、job payload、child import 或 parent process 狀態變更造成；先收集 multiprocessing context 證據，比直接改 executor 更安全。
- 後果：Windows 問題在未取得新 debug log 前仍可能重現；但行為回到歷史預設，避免 masking root cause。

## 2026-07-17 targeted Windows spawn-overlap fallback

- 決策：不改 Windows 預設 executor，也不全面改 thread pool；僅在 Windows legacy `run_round()` 建立 Pool 前偵測到 `multiprocessing.active_children() > 0` 時，該 round 改序列執行；後續已改為內建安全路徑，不再提供一般操作開關。
- 理由：使用者 debug log 證明 crash 發生在 `before_pool` 與 `after_pool_created` 之間，且當下已有 active child；這比「Windows 一律不用 multiprocessing」更精準，也解釋多階段 scheduler 不受影響。
- 後果：少數 Windows legacy single-stage round 在 active child 未清空時會暫時失去 round-level 並行，但可避免整個任務 crash；非 Windows 與沒有 active child 的 Windows round 仍保留原 multiprocessing 行為。

## 2026-07-17 reap before serial fallback for Windows Pool overlap

- 決策：Windows legacy single-stage round 若在建 Pool 前看到 active child，先短暫 join/reap，再判斷是否需要序列 fallback；不直接把該 round 降級。
- 理由：這保留大多數 multiprocessing 並行效能；若 active child 只是上一輪剛結束但尚未被 Python 回收，短 join 可恢復正常 Pool 路徑。只有仍有 active child 時才避開 Windows spawn overlap。
- 後果：Windows 舊單階段在邊界狀態會多等待預設 0.75 秒；不再要求操作人員調整環境變數。

## 2026-07-17 keep Windows spawn-overlap tuning internal

- 決策：Windows spawn-overlap join/reap timeout 與 fallback 不再提供一般操作環境變數；使用內建 0.75 秒與自動安全路徑，僅保留既有 `CZJLLM_LLM_ROUND_DEBUG=1` 做必要診斷。
- 理由：這是 runtime 保護與程式調優，不是任務語意設定；暴露過多環境變數會增加操作負擔與誤設定風險。
- 後果：操作人員不需要知道或調整 spawn-overlap 參數；若觸發保護，終端會顯示提示。若未來需要調整 timeout，應由程式碼或更集中化的 runtime policy 管理。
