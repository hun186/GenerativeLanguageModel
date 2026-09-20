# Project Memory

## Current Summary

- 本專案是 Python 多來源文件／表格處理與 LLM 多階段分析框架；TXT/Table/SQL/ES 共用 prompt、LLM、combine 與 writeback 基礎設施。
- `combine_api_finished_item()` 是 production 單一文件 Success slice 合併邊界；Row Merger 只負責下游協調，Output Profile 維持最終嚴格驗證。
- Reduction Engine PR A-D 已完成：characterization、reducer contracts/registry、explicit single-pass routing，以及 production hierarchical text routing/checkpoints。PR E Shared ExecutionBudget 仍未實作。
- Hierarchical round 1 直接 reduce 原始 Success map outputs；round 2+ 才經 tokenizer、configured round task prompt、LLM map 與 concat reducer。
- Requirements 安裝在目前環境仍受 pinned GitHub `peft` proxy 403 限制；dependency-light pytest、compileall 與 diff checks 是可用替代驗證。

## Recent Changes

### 2026-09-20 Reduction Engine PR D2 production hierarchical routing

- 任務目的：把 D1 controller/checkpoint core 接入 production text combine path，完成 PR D，但不提前實作 PR E 或 collection/Stage 架構。
- 主要修改：嚴格 `ReductionConfig` 新增 text-only `fixed_rounds` / `adaptive_hierarchical`、controller options 與必要 `runtime.round_task`；新增 versioned `TextRoundRuntimeAdapter`，以 copied context 執行 tokenizer → prompt → existing LLM dispatch，workspace 隔離在 `<item>/.reduction/runtime/`。Checkpoint root 為 `<item>/.reduction/checkpoints`。
- 契約結論：既有 Success outputs 完成 round 1，round 2 才第一次執行新 map；adapter 禁止呼叫 `process_prompt_and_merge()`/combine。Execution fingerprint 涵蓋 template/task context/tokenizer/model/generation/think/mock 語意，排除 credentials 與 raw endpoint URL。
- 驗證結果：D2 focused tests 44 passed；全 `tests/reduction` 110 passed；PR A compatibility guards 29 passed；prompt dispatch/audit tests 11 passed；compileall 與 diff check 通過。Requirements 安裝因 pinned GitHub `peft` proxy 403 失敗；包含 `test_prompt_pipeline.py` 的選取因缺少 `opencc` 無法 collection。
- 範圍結論：PR D1 + D2 完成；PR C single-pass、D1 decision/changed contracts、Row Merger、Output Profile、pipeline merge、SQL/ES collection formation、business stages 與 scheduler 未重新設計。PR E 保持 open。

### 2026-09-19 Reduction Engine PR D1 controller/checkpoint core

- 建立 fixed/adaptive controllers、text-only facade、Unicode-character convergence、atomic completed-round checkpoints，以及 strict resume validation。
- Hosted corrective 強制 checkpoint caller 提供 deterministic execution fingerprint，並將 checkpoint contract 升至 v2。
- D1 本身不接 production config/combine；該責任已由 D2 完成。

### 2026-09-19 Reduction Engine PR C single-pass routing

- 新增 immutable strict `ReductionConfig`、三個 explicit single-pass profiles 與 combine-boundary opt-in routing；inactive behavior 不變。
- Hosted corrective 確保 JSON repair 在 reducer 前執行，explicit reducer output 不再進 legacy JSON post-processing。

### 2026-09-19 Reduction Engine PR A/B foundation

- PR A 凍結 Success lexical ordering、text/JSON combine、slice merge、Row Merger 與 Output Profile behavior。
- PR B 建立 source-agnostic reducer contracts、registry、concat text/list 與 legacy deep-merge adapters，並維持 lightweight import boundary。

### 2026-09-18 authoritative premerged multidim writeback

- Row Merger 保留 resolved structured source；authoritative combined dict 可正確套用 generic/multidim serialization，而 stage-specific invalid dict 仍由 profile 拒絕。

### 2026-09-01 LLM call audit propagation

- Legacy consumer 與 stage-managed workers 共用 audit metadata propagation；JSON repair/split retry 子呼叫也保留同一 run/path。

### 2026-08-20 to 2026-08-26 merge and ES validation

- Audited merge 結果成為 authoritative writeback payload，retry 不重複輸出同一 item 的 merge audit。
- Output-profile validation errors 結束本輪確定性重試；ES mapping 400 不再無限重送。`Event.consequence` object 在 ES I/O 前被拒絕。

### 2026-07-17 to 2026-08-21 runtime stability

- Windows legacy pool overlap 以 short reap/thread fallback 緩解；LLM audit、active context metadata、independent slice parallelism、model-profile defaults 與 ES prefetch-off policy 已落地。

### 2026-09-20 Memory Compaction

- `.codex/memory.md` 與 `.codex/decisions.md` 因超過 20 個日期／工作區塊而依規範濃縮。
- 濃縮前全文分別保存於 `.codex/archive/memory.md-20260920-013654.md` 與 `.codex/archive/decisions.md-20260920-013654.md`；以 heading count、檔案存在與 diff check 驗證。

## Archived History

- `memory.md-20260920-013654.md` — complete project-memory history through PR D2 before this compaction.
- `memory.md-20260826-041906.md` — earlier full project-memory snapshot.
- `decisions.md-20260920-013654.md` — complete decision history through PR D2 before this compaction.
