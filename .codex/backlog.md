# 待辦事項（Backlog）

## 高優先度

- 

## 中優先度

- 

## 低優先度

- 

## 技術債

- 

## 未來構想

- 

## 

- 
## 2026-07-14 large file split backlog

- [x] 初步拆分 `czjLLM/prompt_pipeline/pipeline_controller.py`：已抽出 registry/load meter、prompt queue、watchdogs，並集中到 `prompt_pipeline/runtime_support/`，保留相容匯入；LLM dispatch 與多階段 orchestration 可留待後續第二階段。
- [x] 第一階段拆分 `czjLLM/utilities/combine_utils.py`：JSON parsing/repair 與 audited slice merge strategy 已移至 focused modules，舊路徑保留 re-export；prompt result filesystem orchestration 可於後續第二階段再拆。
- [ ] 評估 `utils/utilities.py` 是否仍為活躍依賴；若是，逐步改為 focused utility modules 並保留 re-export 過渡層。
- [x] 已拆分 `czjLLM/es_mode/adapters/elasticsearch_adapter.py` 的 freshness/rerun policy 與 value helpers；`czjLLM/es_mode/entry/steps_es.py` 仍可後續獨立評估。

## 2026-09-19 Reduction Engine v1 implementation sequence

- [x] PR A — Characterization / Golden Tests（production behavior change: NO）
- [x] PR B — Contracts, Reducer Registry, legacy adapters（inactive foundation；production routing 留待 PR C）
- [x] PR C — Strict config + opt-in single-pass routing
  - [x] Hosted-review corrective: repair fallback precedes explicit JSON reduction, explicit reducer output bypasses legacy post-processing, and root schema usage is documented.
- [x] PR D — Hierarchical reduction milestone
  - [x] PR D1 — source-agnostic text controller core + completed-round atomic checkpoints
  - [x] PR D2 — production text-round runtime adapter + hierarchical routing/config
- [x] PR E — Shared Execution Budget（process-local root ownership、leaf-only leases、row executor cap）
- [x] PR F — Logical Work Unit + immutable Collection Manifest
- [ ] PR G — SQL/ES Collection Adapters + idempotent aggregate upsert（implementation and local focused tests complete; hosted offline E2E acceptance pending）
- [ ] PR H — Deterministic composite reducers
- [ ] PR I — Semantic reducer
- [ ] PR J — Structured relational reducer
- [ ] PR K — ReductionStage + bounded PipelineRef nesting
- [ ] PR L — Retention/GC/cache integration points/production hardening

## 2026-09-29 PR G hosted acceptance

- [ ] Confirm corrected PR #187 hosted head collects 15 E2E cases (original 13 plus two PR G cases) and passes the full offline E2E workflow; only then mark PR G complete.
- [ ] PR H remains deliberately unstarted.
