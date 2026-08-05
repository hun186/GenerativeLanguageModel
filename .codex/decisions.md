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

## 2026-07-17 Windows spawn-overlap fallback uses threads instead of serial

- 決策：Windows legacy single-stage `run_round()` 在建立新 multiprocessing Pool 前若偵測到 active child，仍先做內建 short join/reap；若 child 仍未清空，不再序列化整個 round，而是僅該 round 使用 thread pool fallback。
- 理由：使用者最新 Windows vs Linux log 顯示，Linux 可快速排入多個任務並用 multiprocessing worker 並行；Windows 在 active child 安全路徑若改序列，會使任務吞吐接近停滯。LLM API 呼叫為 I/O-bound，thread pool 可避開 Windows spawn handle 問題並保留多 endpoint/多 prompt 併發。
- 後果：此行為仍是窄範圍 fallback：非 Windows、單程序、或 Windows join/reap 後 active child 清空時不受影響；只有已命中 spawn overlap 風險時才使用 threads。

## 2026-07-20 audit LLM context usage as per-run CSV

- 決策：以每次 `czjLLM_TextProcessing` 啟動建立一個 append-only CSV 檔，記錄所有 `PromptAPIPipeline` 實際 LLM 呼叫的 token usage 與 context 使用率；不把欄位寫回業務輸出表格/SQL/ES。
- 理由：使用者需要的是執行層面的總表與截斷風險診斷，而不是改變任務結果 schema。CSV 可跨 txt/table/sql/es 共用，且在 multiprocessing / thread fallback 中易於追加。
- 後果：每次啟動會多產生 `logs/llm_call_audit/` 下的一個 CSV；若外部 LLM 相容端點未回傳 usage，token 欄位會記為 0，需由端點補回 usage 才能計算比例。

## 2026-07-20 do not infer context from model names

- 決策：LLM audit 不再解析模型名稱中的 `ctx-<N>k` 作為 context window；只接受端點 response extension、Ollama `/api/show` metadata 或明確 model config 欄位。
- 理由：模型顯示名稱可能與實際 runtime `num_ctx` 不一致，用名稱推估會造成截斷風險判斷不穩定。OpenAI-compatible chat completion `usage` 可提供 token usage，但通常不提供 context window，因此需把 token usage 與 context metadata 視為不同來源。
- 後果：若模型端點無法提供 metadata、且本地 model config 也未明確設定 context，CSV 會將 context limit 標記為 unknown，不計算比例與耗盡 flag；這比猜測名稱更安全。

## 2026-07-20 use Ollama ps active context for usage ratio

- 決策：Context usage ratio 的 Ollama 分母改用 `/api/ps` active model context，而不是 `/api/show` model capability context。
- 理由：`ollama ps` 的 `CONTEXT` 欄代表目前載入模型實際使用的 context；`/api/show` 可能回傳模型最大能力（例如 131072），會低估使用率並掩蓋截斷風險。
- 後果：若模型尚未載入或 `/api/ps` 無 context 欄位，audit/terminal log 會 fallback 到明確 `model_spec` 或 unknown，不再用 model capability 假裝 runtime context。

## 2026-07-23 ES prefetch disabled by default for LLM-heavy workloads

- 決策：ES mode 的 `es_prefetch_buffer` 預設改為 `0`（關閉預取）；需要時由 YAML 或 `config_es` 明確設定小 buffer。
- 理由：使用者在同一台機器開兩個 CMD 跑同一 ES LLM 任務時，`es_prefetch_buffer: 0` 可消除大量 `TODO 未產生或為空` 訊息。此類 LLM-heavy pipeline 的主要瓶頸通常是模型推論/遠端 LLM API，而非 ES 取件；大型 prefetch buffer 會讓多程序各自持有舊 pending snapshot，放大重複派工與共享 Prompt cache 壓力。
- 後果：預設 ES stream 較重視跨程序穩定性與 pending recheck 收斂；若 ES 查詢/scroll 明顯慢到讓 LLM endpoint 閒置，操作者可明確設定 `es_prefetch_buffer: 5`、`20` 或 `50` 做吞吐測試。

## 2026-07-28 keep combine_utils as a compatibility facade

- 決策：拆分肥大的 `combine_utils.py` 時保留原模組作相容 facade，以 re-export 維持 `combine_json_return`、JSON parsing helpers 與 slice merge helpers 的既有 import contract。
- 理由：prompt pipeline、result handler、SQL row merger 與外部使用者可能直接從舊路徑 import；一次更改所有呼叫端會放大低價值風險。
- 後果：新功能應直接放入 focused module；舊路徑仍可使用，但 `combine_utils.py` 不再承擔 JSON parsing 與 merge strategy 的實作。

## 2026-07-28 split Elasticsearch policy behind existing adapter

- 決策：保留 `ElasticsearchAdapter` 與所有既有方法名稱，透過 focused mixin 抽離 freshness/rerun policy，另將純 value helpers 獨立成無 ES client 依賴的模組。
- 理由：adapter 原檔超過 1100 行且混合連線、mapping、掃描、文件值處理與 rerun policy；以繼承組合保留外部介面，可降低跨 ES entry/runtime 呼叫端改動風險。
- 後果：新增 policy 時應放入 `pending_policy.py`，通用文件值處理放入 `value_helpers.py`；adapter 主檔專注 ES I/O 與 orchestration。
