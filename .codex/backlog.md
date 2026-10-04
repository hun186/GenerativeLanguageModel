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
- [x] PR J — Structured relational reducer
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

## 2026-10-01 Reduction Engine PR K split and hosted baseline

- [x] PR I — Semantic reducer
- [x] PR J — Structured relational reducer (PR #190 merged; hosted offline E2E 18/18 PASS; merge `673f14945a9348d462fe1152f7d53c7aba47497a`)
- [ ] PR K — ReductionStage + bounded PipelineRef nesting
  - [ ] PR K1 — Executable + non-nested ReductionStage/PipelineRef (implemented on feature branch; remains unchecked pending hosted review/19-case gate)
  - [ ] PR K2 — bounded nested reduction + depth/cycle guards
- [ ] PR L — Retention/GC/cache integration points/production hardening

## 2026-10-01 PR #191 corrective acceptance

- [x] Previous hosted head `87428da5ec3316e08916c9bc6ca37f3579f2cc50`: run #434 / `36830720933` collected and passed 19/19 offline E2E cases.
- [ ] PR K1 remains pending: review found effective-task/checkpoint identity, InputCutLen, metadata-preservation, and detachment gaps; the corrected head requires a fresh 19-case hosted gate.
- [ ] PR K remains pending K2; K2 is not started by this corrective.
- [ ] PR L remains unimplemented.

## 2026-10-01 PR #191 head 1e12ba review

- [x] Hosted head `1e12ba005faceaf67169a55e6e77bf794a2d90f6`, CI #435 / `36891694196`: collect-only 19 and offline E2E 19/19 PASS.
- [ ] K1 remains pending fresh corrected-head acceptance after MappingProxy routing, implicit-global identity, and nested InputCutLen review gaps.
- [ ] PR K remains pending K2; PR L remains unimplemented.

## 2026-10-02 PR K2 implementation state

- [x] PR K1 — PR #191; hosted feature head `5632d16b4eb18eaad830f0b81c1a8356bbb8cbe2`; CI #436 / `36895400626`; offline E2E 19/19 PASS; merged as `b74907c2b235bbace9afad4a5b9f676cb85e1748`.
- [ ] PR K2 — bounded nested reduction and depth/cycle guards are implemented locally; remains unchecked until a fresh hosted 20/20 offline-E2E gate succeeds.
- [ ] PR K overall — remains open until K2 hosted acceptance.
- [ ] PR L — retention/GC/cache integration and production hardening remain unimplemented.
- PR L retains member-result caching, full member lineage aggregation, partial-success policies, cancellation, TTL, cleanup, and GC.

## 2026-10-02 PR #192 rejected hosted head and corrective

- [x] K1 — PR #191; CI #436 / `36895400626`; 19/19 PASS; merge `b74907c2b235bbace9afad4a5b9f676cb85e1748`.
- [ ] K2 — PR #192 head `16487e4769e7d7fa4b1c7763c5efc25049460854`, CI #438 / `36964059859`, collected 20 but full gate FAILED in nested E2E: final task prompt exceeded one configured token chunk. Prompt-aware/checkpoint/audit-assertion corrective is pending fresh hosted acceptance.
- [ ] PR K overall remains unchecked.
- [ ] PR L remains unimplemented; finer per-run checkpoint coordination, caches, retention, GC, cancellation, partial success, and lineage aggregation remain out of K2 scope.

## 2026-10-02 Reduction Engine K acceptance and L roadmap (historical; superseded below)

- [x] PR K1 — PR #191; CI #436 / `36895400626`; 19/19 PASS; merge `b74907c2b235bbace9afad4a5b9f676cb85e1748`.
- [x] PR K2 — PR #192; accepted head `e2d61d88c74d4b6e46c59c1ad5e9797c5a8b1bb8`; CI #439 / `36969522652`; 20/20 PASS; merge `721f596001201562d833810fe568f696fd15d112`.
- [x] PR K overall complete.
- [x] PR L1 — persisted destination reuse, semantic freshness and pending-recheck observability implemented; hosted 21-case acceptance remains required.
- [ ] PR L overall remains open.
  - [ ] PR L2 — partial success, cancellation and collection/member observability.
  - [ ] PR L3 — retention/TTL/GC and optional transient-cache hardening, only with production evidence.

## 2026-10-02 PR #193 pre-corrective hosted review (historical; superseded below)

- [ ] PR L1 remains pending fresh corrective acceptance. Head `cb12323d0a98ed6bf3eae28182758db24e72f0df`, CI #441 / `36973654548`, job `110732742876` passed 21/21 but is pre-corrective evidence only.
- [ ] Corrective gate must cover automatic Executable identity binding, SQL identity collision/schema ownership, persistent GUI status, actual producer dispatch reporting, and ES discovery/recheck policy consistency.
- [ ] PR L overall remains pending; L2/L3 are not started.

## 2026-10-03 PR #193 final corrective pending (historical; superseded below)

- [ ] PR L1 remains pending fresh final-corrective hosted acceptance. Pre-corrective head `874dbc865c46a02b5ba76caebbac05b213f94c70`, CI #442 / `37080278738`, offline job `111079056066`, collect 21, full gate PASS.
- Review gaps corrected locally: ES required-output invalid documents could be excluded by the single-index initial query; canonical recheck identity could fall back to raw `ctx.task` prompt text.
- [ ] PR L overall remains pending; L2/L3 remain unstarted.

## 2026-10-04 revised Reduction Engine roadmap

- [x] PR K
- [x] PR L1 — persisted result reuse + semantic freshness + recheck observability
  - PR #193 accepted head `874ef7f8790d38c9c958dfdba0e5d020662da7eb`; CI #443 / `37120493902`; offline job `111195487211`; collect 21; 21/21 PASS; merged as `21038d2678290cd32730009f552809730722aab4` with verified/valid signature.
- [ ] PR L2
  - [ ] PR L2a — partial-success + cooperative cancellation core (canonical PR #195; PR #194 is closed/superseded. PR #195 head `482b683f58a956b5b6dfc50600127bbc82be0e66` passed CI #446 / `37179523777`, offline job `111369063184`, collect 22 and full PASS; remains pending final documentation-cleanup hosted acceptance and explicit merge approval)
  - [ ] PR L2b — production cancellation + run/member observability bridge
- [ ] PR L3 — retention / TTL / GC + optional transient-cache hardening

L2a intentionally does not add production Cancel controls, GUI dashboards, production reduction JSONL logs, SQL/ES stop-event rebinding, retry/caches, retention/TTL/GC, distributed cancellation, hard HTTP termination, aggregate identity redesign, or manifest mutation.

## 2026-10-04 Reduction roadmap after merged L2a

- [x] PR L1 — persisted result reuse + semantic freshness + recheck observability
- [x] PR L2a — partial-success + cooperative cancellation core
  - Canonical PR #195; accepted head `f4ad4001f4498287799df3c89e90ff4a733dc572`; CI #448 / `37179982321`; offline job `111370415206`; collect 22; full PASS; merged as `c1f2f6974e88028eb3eb5b9b747fefeb8d6d5cf0` with verified/valid signature.
  - PR #194 is historical, closed, unmerged, and superseded by PR #195.
- [ ] PR L2b — production cancellation + run/member observability bridge (implemented locally; do not mark complete before fresh hosted acceptance and merge)
- [ ] PR L3 — retention / TTL / GC + optional transient-cache hardening

## 2026-10-04 PR #196 corrective acceptance

- [ ] PR L2b remains open and unmerged. Hosted head `841f784ae38b34ccf28099bf7f630ff2c2d98b49`, CI #450 / `37182363233`, collected/passed 23 but is pre-corrective evidence because its L2b E2E did not exercise production `run_pipeline()` safe drain.
- [ ] Require a new hosted head and fresh collect-only 23/full 23 PASS after the scheduler, Row Merger, GUI lifecycle, counters, privacy, and strengthened single production E2E corrective.

## 2026-10-04 canonical L2b acceptance and L3 roadmap

- [x] PR L1 — persisted result reuse + semantic freshness + recheck observability
- [x] PR L2a — partial-success + cooperative cancellation core
- [x] PR L2b — production cancellation + run/member observability bridge
  - Canonical PR #197; accepted head `b0a14e2c855a28d7d44efe9edcfd587fd689e9c8`; CI #451 / `37186996174`; offline job `111390932764`; collect 23; full offline production gate PASS; merged as `47488c807924fafe71c4d53d1c2999bc4675464f` with verified/valid signature.
  - PR #196 is historical, closed, unmerged, and superseded by PR #197.
- [ ] PR L3 — retention / TTL / safe GC + transient-artifact hardening (implemented locally; remains incomplete pending fresh hosted 24-case acceptance and explicit merge approval)
- [ ] PR L overall — remains incomplete until L3 receives fresh hosted acceptance and explicit merge approval.
