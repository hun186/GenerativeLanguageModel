# architecture

## Current Reduction Engine v1 architecture (2026-10-06)

- Reduction Engine v1 A–L implementation plus the L3 release-audit corrective are present at verified main merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; the production data flow is map or collection-member execution → reducer → optional hierarchical rounds → final result → optional persisted aggregate/writeback.
- The source-agnostic core owns strict `ReductionConfig`, deterministic, semantic and structured-relational reducers, atomic hierarchical checkpoints, shared leaf execution budgets, executable stages, explicit partial success, and cooperative cancellation.
- Collection boundaries use immutable ordered `LogicalWorkUnit` / `CollectionManifest` snapshots. SQL/ES adapters construct snapshots and aggregate sinks idempotently upsert `AggregateOutput` by deterministic `aggregate_output_id`; complete mappings support aggregate-of-aggregates lineage.
- Persisted SQL/ES output is cross-run reuse authority. Runtime round workspaces are reconstructable, while committed checkpoints are resume authority.
- Composition is deliberately bounded: one nested reduction level, at most four PipelineRef entries, cycle detection, and no semantic reducer inside a nested ReductionStage. This is not a generic DAG.
- Production hardening supplies safe recheck/reduction events and counters, cooperative producer cancellation/safe drain, and disabled-by-default, ownership/lease-based bounded retention. After deletion-budget exhaustion, retention continues validation/classification/counters but performs no further deletion. Legacy unmarked and stage artifacts stay outside GC ownership.


---

## 

- 
## 2026-07-15 prompt pipeline helper module split

- `czjLLM/prompt_pipeline/pipeline_controller.py` 仍是 prompt pipeline 的相容入口與主要 orchestration 模組，但 load meter、prompt filesystem queue、watchdog helper 已集中到 `runtime_support/` 子 package。
- `czjLLM/prompt_pipeline/runtime_support/load_meter.py` 負責 `ItemsRegistry`、meter 檔案初始化/讀寫/更新、簡易 lock file、safe unlink 與 item directory lookup。
- `czjLLM/prompt_pipeline/runtime_support/prompt_queue.py` 負責 TODO/RUNNING/Success 檔案佇列操作，例如 claim prompt、path conversion 與 RUNNING 回復 TODO。
- `czjLLM/prompt_pipeline/runtime_support/watchdogs.py` 負責 progress stall watchdog 與 Elasticsearch heartbeat watchdog；透過 `runtime_support.load_meter.meter_read` 讀取 queue 狀態，透過 `round_runner.CONSUMER_STATE` 判斷 dispatch 活動。
- 為降低風險，`pipeline_controller.py` 仍 re-export 這些 helper 名稱，使既有 `from czjLLM.prompt_pipeline.pipeline_controller import ...` 呼叫可繼續運作。

## 2026-07-16 bounded row-level multistage stream dispatch

- SQL / Table / ES stream multistage still executes each row/doc through `schedule_one_row()` and `process_prompt_and_merge()` so the existing stage merge and row_merger writeback contracts remain unchanged.
- The producer can now keep multiple row/doc scheduling jobs in flight via a bounded thread pool when explicit stage flow is enabled. The default bound reuses `ctx.n_process`, the endpoint-pool-derived budget already used by legacy single-stage LLM rounds; when `ctx.n_process` is unavailable it falls back to the available `model_spec.base_url` pool size. The dispatcher intentionally does not infer GPU count from the local host because Ollama/OpenAI-compatible model APIs may run on remote machines.
- Operators may override the bound with `multistage_row_parallelism`, `sql_multistage_row_parallelism`, or `stream_multistage_row_parallelism`; the explicit value should be set conservatively according to the model service capacity to avoid model-side queueing.

## 2026-08-21 independent slice-level dispatch budget

- `czjLLM/prompt_pipeline/dispatch_parallelism.py` 獨立解析 prompt slice worker budget，不與 SQL/Table/ES producer 的 row/doc worker budget 混為同一個設定。
- `call_llm_api()` 在建立一批 TODO slice jobs 後，使用 `multistage_slice_parallelism`（相容 alias: `llm_slice_parallelism`, `slice_parallelism`）限制 worker；未設定時回退既有 `ctx.n_process`。
- 因此 ES/SQL/Table 多階段可在批次尾端只剩長 doc 時繼續將該 doc 的多個 slice 分散到 endpoint pool；後續 stage 若只生成單一 prompt，仍是不可再拆的單 job barrier。
- Parallelism 政策的預設資料來源是 model profile：`initialize_config()` 優先將 `n_process` / 相容 `nProcess` 投影成 `ctx.n_process`，未配置才自動推導；slice 可另用 model-level `slice_parallelism` 覆寫。任務/YAML 參數只作為更高優先序的單次 override。

## 2026-07-20 per-run LLM call audit

- `czjLLM.czjLLM_TextProcessing` 啟動後會建立一次性的 LLM call audit run metadata，掛在 `ctx.llm_call_audit_run_id` 與 `ctx.llm_call_audit_path`。
- `czjLLM/utilities/llm_call_audit.py` 是 append-only CSV audit helper，負責建立 `logs/llm_call_audit/llm_call_audit_<timestamp-pid>.csv`、維護 `latest_llm_call_audit.csv` 指標、解析 usage tokens 與 context limit。
- `PromptAPIPipeline` 在每次實際 `CallLLMAPI()` 成功後記錄 task、prompt file、model、endpoint、input/output/total tokens、context limit、context usage ratio、context exhausted flag、max_tokens 與 cost；呼叫例外時也記錄失敗 row（token 欄位為 0），方便追查中斷前最後一次呼叫。

## 2026-07-20 LLM context metadata resolution

- LLM call audit 的 context limit 不再由 model display name 推估；`llm_call_audit.resolve_context_limit()` 依序使用 response extension、Ollama `/api/show` model metadata、明確 `model_spec` 欄位，最後才回傳 unknown。
- `CallLLMAPI()` 在既有 token usage log 旁新增 context limit log line；token counts 仍取自 chat completion response `usage`，context limit 則來自模型 metadata 查詢或明確設定，兩者來源分開標示。
- Audit CSV 新增 `context_limit_source`，用於區分 `response`、`ollama_api_show`、`model_spec` 或 `unknown`，避免操作人員誤以為 context 是從模型名稱猜出。

## 2026-07-20 LLM audit Excel artifact

- LLM call audit now writes paired artifacts per run: append-only CSV plus a same-stem `.xlsx` workbook under `logs/llm_call_audit/`.
- The workbook is regenerated from the CSV after each audit append and `latest_llm_call_audit.xlsx` points at the newest run, matching the existing CSV pointer behavior.
- The `.xlsx` writer uses Python standard-library ZIP/XML generation to avoid requiring optional Excel dependencies during runtime logging.

## 2026-07-28 combine utility module split

- `czjLLM/utilities/combine_utils.py` 保留完成檔案 orchestration、輸出路徑與 legacy 相容入口，並 re-export 原有 JSON 與 slice merge 公開函式，避免既有 import 路徑中斷。
- `czjLLM/utilities/json_combining.py` 集中 JSON array 分段、repair 與 LLM JSON 回傳正規化；不再為單層 list flatten 載入廣泛的 legacy `utils.utilities` 相依樹。
- `czjLLM/utilities/slice_merge.py` 集中 slice merge 開關、遞迴 dict merge 與 audited merge strategy，供 SQL row merger 與 combine orchestration 共用。
- 原 `combine_utils.py` 內 1,300 多行的手動 `__main__` 範例資料已移除；行為驗證由 `tests/test_combine_json_slice_merge.py` 負責。

## 2026-07-28 Elasticsearch adapter policy boundary

- `es_mode/adapters/elasticsearch_adapter.py` 負責連線、mapping、pending scan 與 adapter 對外介面。
- `es_mode/adapters/pending_policy.py` 以 mixin 集中 output completeness、required checks、freshness/rerun 與 bulk presence policy。
- `es_mode/adapters/value_helpers.py` 提供不依賴 ES client 的文件 dotted-path traversal、nested list flatten、日期驗證及 identifier 正規化。
- `ElasticsearchAdapter` 繼承 policy mixin，因此既有呼叫端仍由原 class/path 使用所有方法，不需改 API contract。

## 2026-08-20 ES model metadata security boundary

- `czjLLM/es_mode/model_metadata.py` 是 runtime model spec 與 ES metadata 之間的 allowlist/redaction boundary。
- `handlers.handle_data_mode._es_sink()` 只從 `ctx.model_spec` 投影安全欄位；兩個 ES sink 在 `_build_meta()` 最終寫回邊界再次遞迴移除 credential/model_spec/實際 endpoint URL，形成 defense in depth。
- pending/rerun policy 使用同一 `safe_model_tag()`，避免 rerun ES query 再帶入字串化 credential。

## 2026-08-26 ES bulk failure classification boundary

- `ESSink._flush()` 現在以單次 materialized actions 對照 bulk errors：成功 action 立即離開 buffer、可重試錯誤保留、ES mapping/parsing 400 永久錯誤移除。
- 永久 mapping rejection 轉為既有 `OutputProfileValidationError` 契約，讓 Row Merger 使用現有 terminal schema failure 流程釋放 row 狀態，避免相同 completed artifact 在 watchdog 中無限重送。

## 2026-08-26 multidim scalar type validation

- `multidim_event` output profile 在 ES sink 前強制 `Event[].consequence` 為 string 或 null，與 prompt 及 ES text mapping 對齊；結構化跨事件影響仍應放入 `Impact[]`。

## 2026-09-19 planned Reduction Engine v1 architecture

- 狀態：此為歷史規劃摘要；PR A-E 現已實作，PR F 與後續 collection/reducer/stage 元件仍未實作。
- 新核心預計集中於 `czjLLM/reduction/`，包含 contracts/config/registry/engine/controllers/policies/execution budget/artifacts/executables/work units/manifests/reducers 與 source/sink adapters。
- Reduction Core 僅接觸 logical items、provenance、contracts 與 execution context；SQL/ES/TXT collection discovery 與 writeback 透過 adapters 隔離。
- `combine_utils.py`、`slice_merge.py`、live prompt-pipeline controller、Row Merger 保留 compatibility facade；`pipeline/merge/` 不納入 live Reduction Engine foundation。
- Worker 執行採 `Executable` 抽象，至少涵蓋 Task adapter 與 bounded PipelineRef adapter；Reduction Round 不等於 business Stage。
- Shared `ExecutionBudget` 必須先於 collection fan-out、semantic reducer fan-out 與 nested ReductionStage，且 child worker 不可另開不受控 pool。
- Collection Manifest 為 immutable/versioned contract，包含 stable member identity、ordering/window/watermark、lineage、contract version；aggregate output 使用 stable derived identity 與 idempotent sink upsert。
- SQL/Elasticsearch 為 multi-document collection 第一批 production targets；TXT/file 保留完整 single-document hierarchical reduction，collection 僅做 constrained manifest/adaptor。

## 2026-09-19 Reduction Engine PR B inactive foundation

- `czjLLM/reduction/contracts.py` 定義 source-agnostic `Reducer` protocol 與 structured `ReducerResult`；不依賴 SQL、ES、filesystem、business Stage、Output Profile、LLM 或 config parser。
- `czjLLM/reduction/registry.py` 是獨立 reducer profile registry，提供 canonical names、aliases、lookup 與 builtins；它不依賴 ES Output Profile registry。
- `czjLLM/reduction/reducers/legacy.py` 提供已準備文字的 concat、單層 dict-only JSON list concat，以及委派既有 `utilities.slice_merge` 的 audited deep merge。
- 此 package 尚未被 production runtime import；combine/Row Merger/YAML routing 維持原路徑，PR C 才擁有 explicit opt-in integration。

## 2026-09-19 Reduction Engine PR C routing boundary

- Root task config 的 `reduction` 由 `czjLLM.reduction.config` 單一邊界正規化為 immutable `ReductionConfig`，並投影到所有 TXT/Table/SQL/ES 共用的 `LLMJobConfig.reduction`。
- `combine_api_finished_item()` 保留 Success discovery、lexical ordering、filtering、JSON preparation、filesystem output 與 cleanup 所有權；僅在 `reduction.enabled=true` 時把 prepared logical items 交給 `reduce_single_pass()`，且只執行一個 reducer call。
- 未設定 reduction 或 `enabled=false` 時不呼叫 reduction execution facade，繼續使用原 legacy combine/merge path。Row Merger 仍只消費 combined artifact，未新增 Registry invocation；Output Profile 仍是 writeback 後段的 final strict boundary。

## 2026-09-19 Reduction Engine PR D1 controller core

- `czjLLM/reduction/controllers.py` 定義 source-agnostic `fixed_rounds` 與 `adaptive_hierarchical` 決策；adaptive 僅以相鄰兩輪 aggregate Unicode character count 計算收斂，決策優先序為 target、max-round guard、stall。
- `czjLLM/reduction/hierarchical.py` 是 text-only execution facade。它接受 already-prepared initial items 與狹窄的 `next_round_items(previous_payload, next_round_index)` callback，不擁有 source discovery、business Stage、worker pool 或 LLM runtime。
- `czjLLM/reduction/artifacts.py` 以 deterministic input/policy fingerprints 建立 stable run key。每輪先 atomic write payload、後 atomic write checkpoint JSON commit marker；resume 僅接受 contiguous、contract-compatible、payload hash 與 parent chain 均有效的 completed rounds。
- PR D1 未接入 `combine_api_finished_item()`，也未擴充 production YAML；PR C `single_pass` routing/config 保持唯一 production contract。Production text-round adapter 與 hierarchical routing 留待 PR D2。

## 2026-09-19 Reduction Engine PR D1 hosted-review identity corrective

- Checkpointed `reduce_hierarchical_text()` now requires a caller-owned non-blank `execution_fingerprint`. Stable run identity and compatibility metadata include it alongside input, controller/policy, profile, reducer contract, and checkpoint contract identities.
- D1 does not inspect callbacks, model names, prompts, tokenizer/runtime settings, context, source type, or Python object identity. The caller must deterministically fingerprint every external execution semantic that can affect future round construction/output; PR D2 will own derivation from its normalized adapter/runtime contract.

## 2026-09-20 Reduction Engine PR D2 production text routing

- `combine_api_finished_item()` retains Success discovery/filtering, lexical ordering, JSON repair preparation, final atomic write, and cleanup. At the existing explicit reduction branch, `single_pass` remains on the PR C facade while `fixed_rounds` and `adaptive_hierarchical` route prepared text into D1 `reduce_hierarchical_text()`.
- Round 1 is the concat reduction of the already-produced top-level `Success/` map outputs. Only round 2 and later call `TextRoundRuntimeAdapter.next_round_items()`; consequently `fixed_rounds: 1` performs no new LLM call and `fixed_rounds: 2` performs exactly one reslice/map/reduce cycle.
- `czjLLM/reduction/runtime_text.py` is the narrow production adapter: a D2-local non-mutating context view overlays the configured `round_task` without copying or changing the production context, including row-scoped slot-based overlays. The adapter token-slices with `TokenizerWrapper`, renders with `PromptGenerator`, and dispatches the isolated round workspace through `call_llm_api()`. It never calls `process_prompt_and_merge()` or combine, so reduction rounds cannot recurse into business-stage/combine orchestration.
- Every post-initial Success text is returned as a prepared concat item ending in one newline when needed; existing trailing newlines and all other valid content are preserved. This mirrors round-1 combine preparation and prevents adjacent map outputs from collapsing together.
- Runtime work is isolated under `<item>/.reduction/runtime/round-NNNN/{TODO,Success}` and deterministically rebuilt when its round is uncommitted. Completed-round authority stays with D1 checkpoints under `<item>/.reduction/checkpoints/<run-key>`; normal combine cleanup and `debug=True` preservation semantics remain unchanged.
- The adapter owns D1's execution fingerprint. Its versioned, secret-free semantics include round task/template and relevant prompt variables, tokenizer identity/input cut/max tokens, model identity and allowlisted generation settings, think mode, and mock/real mode. Credentials and raw endpoint URLs are excluded.
- Each post-initial map round preserves the established LLM retry contract by dispatching TODO work first with `allow_to_retry=true`, then dispatching only remaining TODO work with `allow_to_retry=false`; both passes remain one D1 reduction round. Adapter contract `reduction-text-round-v2` identifies the corrected context, newline, and retry execution semantics so v1 checkpoints cannot share the same execution fingerprint/run identity.

## 2026-09-20 Reduction Engine PR E shared execution budget

- `czjLLM/reduction/execution_budget.py` provides the source-agnostic, thread-safe `ExecutionBudget`; it is process-local runtime coordination, owns no pool/scheduler, and grants partial widths through a blocking `Condition` lease.
- The root CLI runtime projects existing row/slice settings, resolves capacity, and attaches exactly one private `ctx._execution_budget`. `CtxOverlay` and D2 `_RuntimeContextView` inherit that same object through attribute fallback; external contexts without it retain legacy behavior.
- Local row/doc and slice desired maxima remain separate policies. Row orchestration only caps `ThreadPoolExecutor.max_workers` by budget capacity and holds no permits. Leaf leases wrap `multicoreJob` or legacy `run_round` creation through completion, preventing parent-waits-for-child deadlocks and bounding combined leaf execution.
- D2 requires no separate integration because its adapter dispatches through `call_llm_api()`. Budget state/capacity remain outside `reduction-text-round-v2` execution fingerprints and checkpoint identity.
- Scope is one application process/run. Cross-process, cross-machine, Redis, filesystem, GPU, and service-side scheduling remain outside this architecture.

## 2026-09-20 Offline production E2E gate

- Offline production regressions live under `tests/e2e/`. External boundaries are a standard-library localhost OpenAI-compatible server and an in-memory Elasticsearch scan/bulk store; SQLite and CSV use production adapters/sinks.
- Canonical selection is `python -m pytest -q -m e2e`; `live_llm` is reserved for externally configured model/GPU tests.

## 2026-09-20 PR #185 corrective test layers

- Test layers are now explicit: ordinary focused tests; offline `e2e`; individually opted-in `live_llm`, `live_sql`, and `live_es`; and explicitly opted-in composite `live_e2e`.
- Live mutation requires `CZJLLM_RUN_LIVE_E2E=1`, dedicated SQL names prefixed `czjllm_e2e_`, dedicated ES indexes prefixed `czjllm-e2e-`, unique run-owned IDs, and record/document-only cleanup.
- CI separates focused and offline-E2E selections. Live selections are non-PR-only and require both explicit opt-in and service-specific configuration.

## 2026-09-20 PR #185 final production-gate corrective

- The authoritative offline gate has an isolated `offline-e2e` Linux CI job which installs only `requirements-e2e.txt`, proves collection in that clean environment, then executes `pytest -m e2e`; it does not first install the training/GPU requirements surface.
- Offline acceptance now includes the TXT handler lifecycle, SQL and ES `handle_data_mode` backend orchestration, production `call_llm_api` leaf-budget dispatch, and D2 hierarchical combine/checkpoint resume over localhost HTTP.
- The localhost 500→200 case validates OpenAI transport retry only. Focused D2 tests remain authoritative for the application two-pass `allow_to_retry=True` then `False` contract.

## 2026-09-21 Hierarchical checkpoint workspace ownership

- Successful `fixed_rounds` and `adaptive_hierarchical` combines retain the complete item workspace under `<item>/`, including initial `Success` inputs, `.reduction/runtime`, and `.reduction/checkpoints`, because all three participate in deterministic terminal resume.
- Historical cleanup remains unchanged for inactive and `single_pass` reduction when `debug=False`; retention/GC remains deferred to PR L.

## 2026-09-24 Reduction Engine PR F collection identity layer

- `czjLLM/reduction/collection.py` owns the source-independent collection envelope. `LogicalWorkUnit` carries an explicit stable logical ID, reducer-facing JSON payload, and safe provenance. `CollectionManifest` carries contract version `1`, a distinct collection ID, the caller-ordered unit tuple, collection provenance, and its normalized-JSON SHA-256 fingerprint.
- Construction recursively validates and freezes JSON values as mapping proxies/tuples, breaking caller aliases. Canonical serialization returns detached ordinary dict/list/scalar values; reconstruction requires the exact schema and validates the persisted fingerprint.
- Collection Manifest is immutable identity/provenance and is intentionally separate from the existing business-stage manifest, which remains execution artifact/state. Manifest construction neither imports nor invokes SQL, Elasticsearch, Row Merger, LLM runtime, reducers, stages, or sinks.
- Fingerprint semantics include version, collection ID, ordered complete unit mappings (unit ID, payload, provenance), and manifest provenance. Timestamps, host/process/thread/session identity, temporary paths, credentials, raw endpoint URLs, transport objects, and random/runtime-generated identifiers are not accepted as provenance inputs.
- PR G remains responsible for SQL/ES adapters, collection queries, aggregate upsert/writeback, config, and production routing; none are active in PR F.

## 2026-09-24 Reduction Engine PR F identity validation corrective

- Logical and collection identities remain caller-owned stable semantic strings; reduction core never generates them from object identity, random UUIDs, PID, or time. Core validation rejects obvious credential text, JWT-like values, raw URLs, temporary paths, control characters, and blank/untrimmed values without guessing whether ordinary dates, numbers, or words such as `host`/`session` are runtime-derived.
- Provenance has the stronger structural policy: known runtime/nondeterministic keys and secret-bearing keys or values are rejected recursively. Identity values intentionally do not use provenance's key-name substring policy, so benign IDs such as `secretariat-analysis-v2` remain valid.
- This pre-merge tightening retains collection manifest contract version `1` and does not change serialization fields, normalized-JSON SHA-256 inputs/algorithm, ordering, duplicate handling, or nested immutability.

## 2026-09-24 PR G collection source/sink boundaries

- `reduction/aggregate.py` is source-independent: atomic strict manifest persistence, semantic half-open window normalization, deterministic aggregate identity, and immutable aggregate lineage record.
- `sql_mode/collection.py` owns parameterized query materialization, SQL key conversion, ordering/group formation, and dedicated SQLite aggregate-table upsert. It does not call or alter `select_pending_rows()`.
- `es_mode/collection.py` composes an already configured/connected `ElasticsearchAdapter`, resolves a query exactly once, forms canonical manifests, and persists aggregate documents through a dedicated ES update/upsert boundary.
- Data flow is source query → immutable `CollectionManifest` → future source-independent reduction → already Output-Profile-validated `AggregateOutput` → source-specific aggregate sink. Row Merger remains the ordinary one-row/one-result coordinator.

## 2026-09-29 PR G corrective boundaries

- Both source adapters share source-independent typed scalar ordering rather than serialized/repr ordering. Caller-supplied group-field order is semantic, and group fields are encoded as field/value records so source schema names never become provenance-control keys.
- ES aggregate persistence is a single Elasticsearch 7 scripted-upsert operation: an empty source is populated, identical lineage is updated idempotently, and incompatible lineage throws at the atomic update boundary. It does not perform GET-then-update.
- Two marker-scoped offline E2E cases now exercise real PR G adapters/contracts/sinks; SQLite is file-backed and ES substitutes only scan/update transport behavior.

## 2026-09-29 ES aggregate create/update authority

- Elasticsearch update context is authoritative: `ctx.op == 'create'` writes the canonical aggregate document. Any other operation is an existing document and must pass complete five-field lineage validation inside the same Painless scripted update before replacement.

## 2026-09-30 Reduction Engine PR H deterministic composite reducers

- `reduction/reducers/deterministic.py` owns source-independent exact `dedup`, `group`, `entity_union`, numeric `rank`, `top_k`, and sequential `composite` reducers. They consume supplied JSON values only and do not alter collection membership or aggregate identity.
- Dotted paths traverse mapping keys only. Composite steps hand list/tuple members forward, but wrap every other payload (including mappings and strings) as one item. Nested composites are rejected, and PR H profiles route through `single_pass` only; hierarchical controllers remain `concat_text` only.
- `reduction/factory.py` is the single configured-reducer construction boundary. Composite ordering metadata derives from its configured steps.
- PR #188 corrective keeps registry discovery prototypes separate from executable validity: required-option prototypes expose metadata only and fail on execution until configured. Public parameterized reducers validate configuration at construction, while zero-step composite execution and direct composite nesting fail in the reducer core.
- PR #188 immutable-payload corrective places validation and JSON-native detachment in one reducer-local normalization boundary. Reducers retain original first-occurrence payload references; only equality/fingerprint material is detached, so PR F/PR G contracts and versions remain unchanged.

## 2026-09-30 PR I semantic reducer boundary

- `reducers/semantic.py` owns only the source/model-stack-independent `SemanticRuntime` protocol, deterministic item envelope, and fail-closed `SemanticLLMReducer` v1.
- `runtime_semantic.py` is the production adapter: a task overlay feeds existing `PromptGenerator`, the final prompt is checked by `TokenizerWrapper`, and one `PromptAPIPipeline.proc()` call runs under `lease_execution_workers(ctx, 1)` with root audit identifiers.
- Production combine constructs that adapter only for enabled single-pass `semantic_llm`, directly or as the final `composite` step. Hierarchical reduction and checkpoint identity remain unchanged.

## 2026-09-30 PR #189 think-output corrective

- Semantic task overlays continue to expose root `think_mode` to `PromptGenerator`, while `PromptAPIPipeline.include_think` remains independently `False` so normal response cleanup strips `<think>` blocks. Empty semantic collections fail before runtime execution.

## 2026-10-01 PR J structured relational reducer boundary

- `reduction/reducers/structured_relational.py` owns strict configuration validation, one-level record flattening, two-pass local-ID canonicalization/reference rewriting, detached JSON output, complete remap provenance, and post-remap reducer-wide integrity checks.
- Pass one assigns every ID using `(record_index, entity_set, local_id)` namespaces; pass two rewrites only configured entity/reference fields. Duplicate IDs inside one local namespace and dangling same-record references fail; duplicate local IDs across records deliberately become distinct canonical entities without semantic consolidation.
- Registry/config/factory integration is generic and single-pass. Composite rejects this profile because child provenance is not propagated; hierarchical/checkpoint runtime remains `concat_text`-only and unchanged. The existing multidimensional Output Profile remains the downstream validation boundary and contains no global canonicalization logic.

## 2026-10-01 Reduction Engine PR K1 executable foundation

- Reduction worker execution now depends on a small source-independent contract. Production task leaves reuse the authoritative stage prompt renderer, `TokenizerWrapper`, `PromptAPIPipeline`, and the root `ExecutionBudget`; exactly one permit surrounds only `proc()`.
- Ordinary multi-stage workers adapt the existing in-memory `stage_orchestrator` and do not create business-stage snapshots, manifests, or writeback. `ReductionStage` owns parallel ordered mapping and reducer/controller calls without holding leaf permits.
- Hierarchical round 1 reduces initial worker outputs; round 2+ deterministically tokenize the prior aggregate, run the same worker, and delegate stop/checkpoint behavior to D1. D1/D2 checkpoint formats and historical identities are unchanged.

## 2026-10-01 PR #191 K1 semantic-identity corrective

- One StagePipeline invocation now binds one effective task pool to stage resolution, leaf rendering/tokenization, and fingerprinting. The default is root `taskSetting`; an explicit detached override is bound through a production TaskRuntime context view.
- Executable configuration is detached at construction. Callable references remain supported, while fingerprint input uses stable source text when inspectable and module/qualified name as the source-unavailable fallback.

## 2026-10-01 PR #191 final K1 task-pool consistency

- K1 binds explicit, root, or established global task settings into one effective pool before stage execution. Route task keys, leaf rendering, token preflight, and checkpoint identity observe that same pool.

## 2026-10-02 PR #192 K2 corrective architecture

- K2 retains a hard maximum of one nested ReductionStage boundary and four active PipelineRef names, with immutable execution/fingerprint traversal state and explicit cycle failure.
- Production initial and round preparation delegate to one prompt-aware `ProductionTaskRuntime` source-content splitter. It renders and tokenizes with the same authoritative preflight used by leaf execution; templates are never split or truncated.
- A checkpointed `ReductionStageExecutable` serializes its complete child-stage call with a per-instance operational lock. Preparation occurs before the lock, no leaf permit is held while waiting, and non-checkpointed nested stages remain concurrent.
- No workflow/DAG, partial-success, cache, retention, cancellation, TTL, GC, or member-lineage aggregation is introduced.

## 2026-10-02 Reduction Engine PR L1 architecture

- SQL target rows and Elasticsearch target documents remain the sole persisted member-result reuse authorities. Stage snapshots, manifests and merged files are run artifacts; D1 checkpoints are round-resume state; pending-running is current-work coordination.
- Initial discovery and dispatch/completion recheck share destination-specific semantic freshness. SQL uses one condition builder plus one row decision contract; ES extends `ElasticsearchPendingPolicyMixin` rather than adding a parallel policy.
- Collection adapters remain snapshot-only and may explicitly copy persisted derived payload fields plus an explicitly selected processing fingerprint into provenance. `source_version` and `execution_fingerprint` remain distinct identities.

## 2026-10-02 PR #193 L1 corrective architecture

- Automatic persisted freshness binds once in `handle_data_mode` after effective columns/configuration and before schema/pending discovery. It uses K1/K2 Executable fingerprint metadata and supplies one exact full value to context, adapter, and sink.
- SQL explicitly owns and validates its configured processing identity column; ES query and in-Python freshness share missing/mismatch semantics for configured semantic metadata.
- Producer candidate progress is not dispatch count. The producer thread captures `produce_rows()`' actual return separately for the final summary.

## 2026-10-03 PR #193 final L1 corrective

- Single-index ES uses broad input/filter discovery plus authoritative Python postfilter only when active required-output semantics cannot be represented exactly in the optimized query. Ordinary jobs retain query-side narrowing; dual-index retains target bulk Python freshness checks.
- Recheck event identity is diagnostics-only and comes from bounded explicit config basenames or a simple pipeline name, never `ctx.task`/prompt content.

## 2026-10-04 PR L2a core architecture (pending hosted acceptance)

- Reduction worker orchestration now uses an indexed bounded future window no wider than effective orchestration width. New work is submitted only after completion frees a slot; successful outputs are restored to original input order. No orchestration wait owns an `ExecutionBudget` leaf lease.
- The default remains fail-fast `require_all`. Opt-in `allow_partial` absorbs only `ExecutionError`; `ExecutionCancelled` always aborts and unexpected programmer/system exceptions fail hard. Policy is evaluated independently for every worker batch, including later hierarchical rounds, and reducers consume successful outputs only.
- Cancellation is inherited through immutable nested contexts and pipeline refs. Checks surround task calls, pipeline traversal, nested ReductionStage execution, worker submissions, reducers, round preparation/checkpoint commits, and final return. Completed prior checkpoints remain reusable; a cancelled incomplete round is not committed as terminal cancellation state.
- Failure policy is semantic and participates in `reduction-stage-v3` fingerprints. Cancellation signal and current state are operational and excluded from fingerprints, processing identity, cache identity, and checkpoint keys.
- Accepted partial collection output keeps the original immutable Collection Manifest and aggregate identity. Missing membership is represented in bounded ReductionStage provenance; no reduced-member manifest is synthesized. L2a adds no production GUI, JSONL event log, scheduler binding, or SQL/ES stop-event replacement.
- D1 checkpoint schema is deliberately unchanged. A completed partial round is checkpointed under the policy-aware execution fingerprint, while detailed member-failure lineage remains in the outer result; a later process that resumes past that round cannot reconstruct its prior per-member details from the checkpoint alone.

## 2026-10-04 PR #194 fatal exception boundary corrective

- Fatal programmer/system exceptions remain outside the recoverable member channel at both TaskExecutable and StagePipeline boundaries. StagePipeline wraps only a genuine task `TypeError` to distinguish it from the orchestrator's legacy runner-signature fallback; assertions and memory exhaustion propagate directly.
- Normal production runtime/transport failures retain the established `ExecutionError` conversion and stage retry behavior before the outer ReductionStage may count one recoverable member failure. Cancellation remains its distinct `ExecutionCancelled` path.

## 2026-10-04 PR L2b production cancellation and observability bridge

- A run-scoped production control object owns a cooperative cancellation event distinct from the worker teardown event. Producer scheduling observes the former; consumer, merger, progress drain, and shutdown retain the latter.
- SQL/Table/ES scheduling, legacy single/multistage calls, legacy combine reduction, TextRoundRuntimeAdapter, SemanticLLMRuntimeAdapter, and ReductionStage share the root cancellation intent. In-flight external calls reach their next safe boundary.
- `ExecutionContext` carries inherited operational observer/tags. The canonical production context factory binds task runtime, registry, cancellation, observer, and detached tags without adding operational data to semantic fingerprints.
- The production observer writes allowlisted bounded JSONL under `PGMSubDir/logs/reduction_execution_events.jsonl`, maintains lock-protected cumulative statistics, and sends snapshots to a separate GUI Reduction Status surface.

## 2026-10-04 PR #196 corrective safe-drain ownership

- Synchronous multistage cancellation removes only the current registry/meter coordination entry, propagates `ExecutionCancelled` to the producer, and retains TODO/Success/checkpoint artifacts for resume. Row Merger owns deterministic completion/writeback; semantic combine cancellation releases the row once without retry spinning.
- Worker shutdown may retain the GUI until post-writeback completion recheck and the forced terminal observer snapshot finish; the existing `shutdown()` lifecycle remains authoritative for consumer/merger/drain/refresher teardown.

## 2026-10-04 Reduction Engine PR L3 retention architecture

- `reduction/retention.py` is the opt-in operational lifecycle boundary for newly marked checkpoint runs and runtime rounds only. Checkpoints remain authoritative resumable state; runtime rounds are reconstructable transient state.
- Cross-process execution leases and GC claims use exclusive filesystem directories, bounded secret-free metadata, stale-expiry rechecks, and claim-before-delete. A verified same-parent tombstone rename removes the semantic live name before recursive deletion.
- Discovery is bounded to explicitly supplied item roots and recognized `.reduction/{checkpoints,runtime}` direct children. Resolved containment and non-following symlink traversal are mandatory.
- Production maintenance runs synchronously after writeback classification and worker shutdown. Successful hierarchical combine may clean owned runtime rounds only after atomic final-output write; checkpoints survive until their applicable TTL.
- SQL/ES persisted results, AggregateOutput, Collection Manifest, final/source/backup files, logs, and legacy `_stage_outputs`/`_stage_merges` remain structurally outside L3 ownership.

## 2026-10-04 PR #198 L3 corrective architecture

- The canonical root CLI validates `reduction_retention` once into frozen `ctx.reduction_retention` before TXT/Table/SQL/ES scheduling; compatibility fallbacks are not the primary path and retention remains outside semantic identity.
- Explicit prompt-container discovery covers exactly immediate non-symlink item children, so unscheduled historical items remain eligible without adding recursive WorkPool traversal. Container and artifact entries share the scan bound.
- Crash tombstones require exact token/name/marker/kind/containment agreement and retained ownership metadata. Recovery shares ordinary entry/byte budgets and bounded reporting.
