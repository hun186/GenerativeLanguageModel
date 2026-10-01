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
- [x] PR G — SQL/ES Collection Adapters + idempotent aggregate upsert
- [x] PR H — Deterministic composite reducers
- [x] PR I — Semantic reducer
- [ ] PR J — Structured relational reducer
- [ ] PR K — ReductionStage + bounded PipelineRef nesting
- [ ] PR L — Retention/GC/cache integration points/production hardening

## 2026-09-29 PR G hosted acceptance

- [x] PR #187 hosted head collected and passed all 15 E2E cases.
- [x] PR #188 hosted head collected and passed all 16 E2E cases.
  - [x] PR #188 public reducer fail-closed corrective implemented and locally verified.
  - [x] PR #188 immutable `LogicalWorkUnit.payload` canonicalization corrective accepted; PR #188 merged after all 16 hosted E2E cases passed.

## 2026-09-30 Reduction Engine PR I

- [x] PR I — Semantic reducer (PR #189 merged; hosted offline E2E 17/17 PASS; merge `ea3f8b4436000cbc201cd63da2a2db3259b4ab5b`)
- [ ] PR J — Structured relational reducer
- [ ] PR K — ReductionStage + bounded PipelineRef nesting
- [ ] PR L — Retention/GC/cache integration points/production hardening

## 2026-09-30 PR #189 review corrective

- [x] PR #189 corrected head passed all 17 hosted E2E cases and merged as `ea3f8b4436000cbc201cd63da2a2db3259b4ab5b`.

## 2026-10-01 PR #189 hosted corrective

- [x] The corrected semantic user-message assertion passed the hosted 17/17 offline E2E gate before PR #189 merged.

## 2026-10-01 Reduction Engine PR J

- [ ] PR J — Structured relational reducer (implementation is local; remains unchecked until its hosted 18-case `offline-e2e` gate succeeds).
- [ ] PR K — ReductionStage + bounded PipelineRef nesting (not implemented).
- [ ] PR L — Retention/GC/cache integration points/production hardening (not implemented).
