# 技術決策（Technical Decisions）

## Current Summary

- 

## Recent Changes

- 2026-09-19：PR B 僅凍結 Reducer boundary；registry 與 legacy adapters 保持 source-agnostic 且 inactive。Deep merge 委派既有 audited utility，dedup/conflict policy 為 reducer instance 的明確選項，不統一或改寫現有 caller defaults；production opt-in routing 留待 PR C。
- 2026-08-21：併行調校以 model profile 為預設操作面，避免每份 ES YAML 重複設定；支援 `n_process` 與舊 `nProcess`，slice 特別需求用 `slice_parallelism`。YAML 只保留高優先序 task override。
- 2026-08-21：doc/row 併行度與 prompt slice 併行度分開設定；新設定未出現時回退 `ctx.n_process` 以保持相容，實際 worker 數不超過本批 job 數。
- 2026-08-20：`merge_slices` 的 audited merge 結果必須成為相同 source 的權威主欄位 writeback payload，不可只供 flatten 使用；multidim profile 用 `[merged article record]` 保持 ES array contract，generic profile 寫 merged object。
- 2026-08-20：多切片 merge audit 的觀測單位是 completed item，而不是 writeback attempt；同一 item 因暫時性 sink failure 重試時仍重新計算 merge，但終端只輸出第一次 conflict audit。
- 2026-08-20：output profile transformer 的資料格式／schema 拒絕以 `OutputProfileValidationError` 跨 sink 傳遞；Row Merger 依型別終止本輪，不再靠列舉錯誤字串。網路、ES 與其他 writeback errors 不包裝，仍可重試。

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

## 2026-08-20 narrowly normalize observed multidim field aliases

- 決策：multidim event profile 僅針對已觀察且無歧義的 `Event.constance` 拼字錯誤，於嚴格 schema 驗證前正規化為 `Event.consequence`；不開放任意未知欄位，也不在 alias/canonical 值衝突時自行選值。
- 理由：LLM 即使 prompt 明確仍可能偶發偏離輸出 schema；此別名語意與目標欄位唯一且可無損修復，而放寬 ES dynamic/schema 驗證會污染 mapping。
- 後果：此類單一拼字錯誤可正常寫回；其他未知欄位或衝突資料仍會被拒絕，Row Merger 相同錯誤改為週期性提示而非高速洗版。

## 2026-08-20 do not normalize LLM schema-adherence failures

- 決策：撤回同日 `constance -> consequence` 的欄位別名正規化；LLM 產生 unknown field 時保留為可觀測的 schema failure。Row Merger 對這類確定性錯誤跳過本輪寫入、釋放本輪 registry/running 狀態，讓缺少輸出的文件在下次執行重新分析。
- 理由：即使拼字修復語意明確，下游自動修復仍會提高表面寫回成功率，進而掩蓋模型的 schema adherence 問題，造成 LLM 效能與品質評估偏樂觀。
- 後果：錯誤資料不會污染 ES mapping，也不會在同一 watchdog 內無限重試洗版；該筆不會被視為成功寫回，最終 pending recheck 仍可反映失敗，下一次批次再嘗試。

## 2026-08-20 schema failure evidence uses the bounded adjustment JSONL

- 決策：Row Merger schema failure 使用既有 pending-running adjustment JSONL 保存結構化事件，並由 `record_adjustment()` 回傳路徑供終端提示；不另建第二套無上限 error log。
- 理由：既有 adjustment log 已包含時間、pid、mode、task、target 且具大小上限裁切；追加 error、output profile/column 與 combined artifact path 即足以改善模型與 prompt，同時避免重複日誌系統與敏感原文落盤。
- 後果：使用者能從終端直接定位稽核檔；即使 running 狀態釋放失敗，稽核寫入仍會獨立嘗試。若 pending console logging 被明確停用，終端會提示未保存紀錄。

## 2026-08-20 allowlist ES model metadata and redact at sink boundary

- 決策：ES model metadata 採 allowlist，而不是只 blacklist `api_key`。允許 model name、endpoint alias、context、temperature、version；禁止完整 model spec、實際 base URL 與所有 credential-like values。sink writeback boundary 再執行遞迴防禦性清理。
- 理由：credential 可能從 ctx、rerun config、plugin meta_base 或字串化 dict 進入；只修正單一 `model_tag` 建構點不足以保證後續 plugin 不再洩漏。
- 後果：需要識別 endpoint 時必須配置非敏感 `base_url_alias`；實際 URL 不再保存於分析 metadata。歷史資料需另行清理，不能由一般分析批次靜默修改。

## 2026-08-26 ES mapping 400 is a terminal writeback attempt

- 決策：`document_parsing_exception` / `mapper_parsing_exception` 類 HTTP 400 視為「對未變更 payload 不可重試」；不在 ESSink 內自動 stringify object，也不修改 index mapping。
- 理由：範例中 `multidim_event_json.Event.consequence` 已 mapping 為 `text`，payload 卻是 object；重送同一 action 不可能成功，且保留 buffer 會在每輪再累積相同 action並洗版。
- 後果：該輪釋放 running 並保持文件 pending，後續應修正 LLM schema（若 consequence 應為字串）或以新 index/reindex 修正 mapping（若 consequence 應為 object）。暫時性 ES 錯誤仍保留於 buffer 重試。

## 2026-08-26 reject structured Event.consequence before ES I/O

- 決策：不 stringify、flatten 或搬移 LLM 誤放到 `Event.consequence` 的 object；在 output profile boundary 直接拒絕非 string/null 值。
- 理由：object 的 `impact_description` / `event_ids` shape 表示模型混淆 `Event.consequence` 與 `Impact[]`，自動轉換會掩蓋 schema adherence 品質且可能錯誤改變事件歸屬。

## 2026-09-19 Reduction Engine v1 planning decisions

- 決策：`czjLLM/pipeline/merge/` 不作為 Reduction Engine foundation；live combine/writeback 路徑以 source inspection 結果為準。
- 決策：Reduction Worker 不直接採整個 business-stage abstraction，改用小型 `Executable` contract，透過 Task/PipelineRef adapters 重用既有 runtime。
- 決策：Shared `ExecutionBudget` 是 collection/semantic/nested reduction 的前置條件，不延後到 hardening。
- 決策：Collection Manifest 與既有 stage manifest 分離；前者是 immutable identity/provenance contract，後者維持 execution artifact。
- 決策：Row Merger 保持 SQL/table/ES writeback coordinator，不進入 generic Reduction Core；Output Profile 維持 final strict validation boundary。
- 決策：collection aggregate creation 必須有 stable logical aggregate identity（例如 `aggregate_output_id`）與 idempotent sink upsert；既有 row/document update key 不視為足夠。
- 決策：PR A Characterization / Golden Tests 為第一個 implementation PR，且不得改變 production behavior。

## 2026-09-19 Reduction Engine PR C decisions

- reduction 必須明確 `enabled: true` 才啟用；mapping 缺少 enabled 視為 inactive，但所有 supplied keys/types 仍嚴格驗證。PR C 只接受 `single_pass` 與三個 PR B profiles，且與 legacy `merge_slices=true` 互斥。
- explicit `legacy_json_deep_merge` 在 combine boundary 使用 caller compatibility defaults（`prefer_left`、`dedup_lists=true`、audit enabled、10 samples），不改寫 reducer/low-level utility 各自既有的 `dedup_lists=false` default。
