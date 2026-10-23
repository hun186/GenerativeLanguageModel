# 已知問題（Known Issues）

## Current Summary

### Requirements installation is blocked by the network proxy

- `python -m pip install -r requirements.txt` can fail while cloning the pinned GitHub `peft` dependency because the configured HTTPS proxy returns HTTP 403.
- Incomplete local environments may then lack PyYAML, OpenCC, tqdm or other runtime dependencies, causing broader SQL/ES/prompt suites to fail during collection rather than from application behavior.
- Use dependency-light targeted tests, `compileall`, and `git diff --check` locally, then use hosted `offline-e2e` as the authoritative full production gate.
- **Status:** Open; external network/proxy limitation.

### Historical ES documents may contain model credentials

- Older model-tag behavior could persist stringified model specs containing API keys or actual endpoint URLs.
- Current allowlist/redaction protects future writes but does not scrub historical documents, snapshots or external logs.
- Operators must rotate exposed credentials and perform controlled cleanup/reindex while access is restricted.
- **Status:** Open; requires ES operator action.

### Windows legacy single-stage multiprocessing overlap

- A legacy single-stage LLM round can encounter `EOFError` or `PermissionError: [WinError 5] DuplicateHandle` when creating a multiprocessing pool while another child is active.
- Runtime uses a short reap attempt and targeted thread-pool fallback without broadly changing non-Windows or multistage execution.
- **Status:** Mitigated; retain diagnostic coverage.

### Windows spawn-overlap smoke-test expectation mismatch

- `tests/prompt_pipeline/test_round_runner_smoke.py::test_windows_spawn_overlap_join_clear_allows_pool` expects multiprocessing after reap clears children, while current safety policy selects ThreadPool whenever the round observed an active child.
- Decide whether to update the test or policy after Windows evidence.
- **Status:** Open.

### datetime.utcnow deprecation warnings

- Some paths may still emit `datetime.utcnow` deprecation warnings.
- Migrate those paths to timezone-aware UTC values when next maintained.
- **Status:** Open; non-functional warning.

## Recent Changes

### 2026-10-06 Reduction retention bounded-reporting issue resolved

- Historical issue: a malformed tombstone encountered after deletion-budget exhaustion could be counted in `scanned` without incrementing `skipped_invalid`.
- PR #201 added a run-local `deletion_budget_exhausted` latch so later candidates still undergo validation/classification/counters while no further deletion occurs.
- Accepted head `62deba6a35d5d5f1d5c82f586d65bc8827e212ef`; CI #459 / `37399753801`; offline job `112064086574`; collect 24; full gate PASS / 100%; merge `91e39503c8e84d17752f9d26a23ff6b34db75b9e`; signature verified / valid.

### 2026-10-04 to 2026-10-06 local verification environment

- Required dependency installation continued to be proxy-limited; dependency-light Reduction/retention/prompt checks remained available while hosted offline E2E supplied authoritative acceptance for L2/L3 and closure heads.

## Archived History

- `.codex/archive/known_issues.md-20261006-134200.md` — complete pre-compaction issue/environment history through PR #200 head `39177737486a372f38e9b6d81563d6f14327459a`.
- `.codex/archive/known_issues-20260918-000000.md` — earlier pre-compaction history retained.

### 2026-10-13 Issue #211 physical-backend follow-up (PR #213, pending)

- A newly added full SQLite/Excel offline E2E revealed that the first extract-stage SQL/Table path may rerender a complete primary-input row into every already-tokenized slice, losing original slice membership. A narrowly scoped correction is proposed in PR #213; acceptance depends on its exact-head CI and review. The initial E2E fixture also disabled normal Success TODO cleanup and was corrected; do not interpret that fixture mistake as a separate production failure.
- Windows self-hosted CI jobs have historically remained queued. The new tests run under the Linux `offline-e2e` job, including simulated CRLF coverage elsewhere; genuine Windows hardware/live model/database acceptance is not established.

### 2026-10-14 PR #213 corrective review and CI pending

- Codex P1 found at prior `1ae2c8e`: partial extract resume with a distinct task_key could reject valid durable raw snapshots when only a subset of TODO remained. Current PR branch proposes durable source/provenance verification and full Success membership recovery. Exact-head CI plus fresh Codex review are mandatory before declaring fixed.
- Existing legacy resumed workspaces without durable raw-source provenance may conservatively fail closed for task-key-overridden extract rather than guessing which raw source segment a lone child/remaining prompt represents. Full restart or explicit recreation is the safe fallback.

### 2026-10-14 new smart_reset Codex finding addressed but not yet accepted (PR #213)

- Finding: storing source provenance under `_stage_outputs/original` loses it on `smart_reset`, causing incomplete Success coverage and potentially partial SQL/Excel writes. Fix moved hash-only manifest outside resettable snapshots, with source-verified regeneration and fail-closed handling of legacy missing provenance.
- Correctness proof still pending on latest exact branch head. Previous green CI for `a42c5ff` did NOT cover the fix. Windows self-hosted runners may remain queued.

### 2026-10-14 latest Codex P1s awaiting verification (PR #213)

- P1: Callable task mapping string representations depend on memory address, causing invalid `stage_task_sha256` across Python process restarts. Proposed deterministic semantic task fingerprint with callable source and stable task fields; test stable recreated function objects and config edits.
- P1: Issue #211 raw-source manifest accidentally affected ordinary multistage restarts after source changes. Proposed bypass of the guarded manifest path and refreshed original snapshot/fallback for non-single-extract stages, with resume/reset E2E.
- Neither has exact-head CI SUCCESS or Clean Review yet; do not merge.

### 2026-10-14 two latest P1s awaiting independent validation (PR #213)
- P1 task fingerprint omission: different same-line lambdas had same inspect.getsource/module/qualname and no included bytecode when source existed. Corrective always hashes code and consts.
- P1 dispatch provenance overwrite: resumed B could replace its already persisted prompt hash, silently mixing distinct prompts/results. Corrective validates all existing SHA-256s before any mutation and fails closed on drift (except deliberate full_restart).
- Both are fixed on the PR branch but NOT YET verified by exact-head CI/Codex; main remains unchanged.

### 2026-10-16 ES multidimensional Event writeback collision (fix pending review)
- Reported production log: after two independently generated JSON slices and successful LLM repair, the audited generic list merge concatenated Event entries with the SAME local event_id='E1'. ESSink's strict multidim_event profile correctly rejected "multidim_event_json[0].Event contains duplicate event_id 'E1'"; Row Merger released the running state and kept the ES source row pending without writing. This is a semantic merge problem, not evidence of ES connectivity failure.
- The reported output also had Impact as a redundant nested array ([[{...}]]), which violates the strict list[dict] profile and would cause a second schema failure after merely renumbering Event IDs.
- Work on fix/es-multidim-event-slice-ids-20261016: reconcile event IDs BEFORE generic list concatenation, update matching per-slice Person/Involved_Parties/Impact/Event_Timeline/evidence_snippets references, preserve first/later original IDs and strict within-slice duplicate rejection; format-only flatten one redundant Impact array level in the ES profile. Scope limited to output_profile=multidim_event or auto-inferred multidim_event_json, leaving unrelated/no-eventids JSON untouched.
- A real ES server, real Ollama endpoint, and user's production records cannot be accessed from hosted CI. Verify focused offline Row Merger + ES output-profile test and repository CI first. Do not claim production writeback is fixed until the new PR passes exact-head checks/review and a small real dry run; do not merge without user authorization.

### 2026-10-19 malformed LLM chunk-local event references (mitigation pending review)
- Some real LLM chunks contain event_ids naming an Event ID not declared in the same slice (e.g. E3 or T1). The strict contract currently fails closed to prevent assigning a reference to an unrelated event from a different slice. This is a real model-output inconsistency; runtime cannot safely infer the intended event.
- On main after PR #214, failing merge emits [COMBINE-FATAL] and row watchdog retries the same unchanged Success on every scan, flooding the console. Mitigation on fix/es-multidim-terminal-merge-error-20261019: terminal schema release once per row, concise log, preserve pending ES row and local source/Success for operator diagnosis, no invented FK repair, and leave transport failures retryable.
- Remaining operational question: whether to add explicit opt-in LLM/semantic corrective processing for dangling IDs. Do not auto-map T1 or foreign E3 to arbitrary events; first inspect source and prompt expectations. All validation claims require Hosted CI and (for production) tiny ES acceptance sample.

### 2026-10-19 ES article_date / importance schema drift (PR #216 open)
- Production batch (37,286 scheduled candidates) revealed mixed-slice article_date_iso and article_date_precision mismatch after independent scalar conflict preference (null/unknown vs concrete day), and top-level flattened importance score fields (coverage, novelty, impact, credibility, importance_score). These are separate from PR #214 Event-ID collision and PR #215 E3/T1 terminal retry-storm fixes.
- Proposal: select internally consistent article_date_iso+precision pair from one slice using existing prefer_left/right precedence; retain null/unknown if source is unsure (treaty signing date 1982-12-10 need not be article date), never invent a publication date. If no valid source pair, strict ES still rejects. Unambiguous exact score keys can be nested into importance without changing numbers; duplicates with conflicting values, unexpected fields, wrong types remain errors.
- Open concerns: Semantic document publication date cannot be verified by shape alone; score values may differ between independent chunks; do not overwrite conflicting scores automatically. No live ES/Ollama verification, Windows self-hosted jobs not necessarily available. Await Hosted exact-head Linux CI, new Codex review, and explicit user merge authorization.


### 2026-10-19 buffered ES writeback completion race (proposed mitigation)
- Code inspection after merged PR #216 found that ESSink may defer bulk until row-count/byte/time thresholds; Row Merger presently releases running state, counts completion and moves source/removes Success before that bulk acknowledgment. A later bulk mapping/transport error may not be attributed to the already-finalized record.
- Branch `fix/es-writeback-ack-before-row-cleanup-20261019` proposes an explicit `confirm_writeback()` handshake before final row cleanup with targeted regression and Hosted CI coverage. Risk is inferred from source code, not an observed production data-loss report.
- Remaining limits: a bulk acknowledgement is not the same as search visibility (refresh), Windows/internal ES+Ollama tests are not yet performed, and transport errors can keep a row pending for rerun. Before 37,286-row restart, verify 1–3 real rows by independent ES readback and compare to tracking and artifact state.
- **Status:** Fix proposed in new PR; production acceptance open. Earlier text saying PR #214/#215/#216 are pending is historic and superseded by the merged commits recorded in memory.md.


### 2026-10-20 Processing Quality PR #218 remaining gaps
- Current quality panel covers JSON syntax/recovery and terminal Row Merger schema/confirmed writeback; it does NOT yet include all LLM transport failures, stage exceptions, worker crash classes or raw error timeline. Existing LLM call audit retains request-level failures. Do not present the first-stage view as whole-pipeline failure rate.
- A writeback success event follows the Row Merger sink contract (ESSink bulk acknowledgment), not ES search refresh/readback. Actual Windows GUI visual validation and ES/Ollama production acceptance remain outstanding. Windows self-hosted CI may remain queued.
- The JSONL append log is run-scoped and unbounded; incrementally processed by the GUI. Across-run comparison/export, retention, threshold alerting and integrated process error taxonomy remain backlog.

### 2026-10-20 PR #218 confirmed-writeback attribution (Codex P2)
- An unexceptional Excel/CSV `write_main()` return does not prove data reached durable storage: these sinks may skip PKs, swallow I/O errors or defer buffered flush. Quality `document_writeback_confirmed` is therefore emitted ONLY after an explicitly exposed sink `confirm_writeback()` succeeds (currently ES). Non-confirming sinks must remain unmeasured, not mislabeled as successful.
- Historical document-level schema pending rate is a **coverage-limited observed-decision rate**, not an all-backend write success rate; it needs per-sink contracts to become cross-backend. Current full GUI/ES live acceptance still outstanding.

### 2026-10-20 offline quality report caveats
- No real model/Windows ES acceptance today: continue development in an unmerged PR, pin tomorrow's smoke test to merged #218 `bfe49413071a80a67d1a0d8208ef3706d5411b7f`.
- The offline report is an observational read of a possibly active stream, not a transactionally consistent snapshot. Incomplete trailing JSONL records are excluded; corrupt complete lines are skipped by the existing reader. Read-only report is not proof of bulk durable ES search visibility. Windows self-hosted CI may remain queued.

- New offline quality report flags truncated/in-flight tail and complete corrupt JSONL lines separately. It does not reconstruct discarded payloads or validate syntactically correct unknown-schema events; audited denominators may be incomplete when the corruption flag is nonzero.

- Codex review after first corruption fix identified two P2 in PR #219: JSON-valid but event-schema-invalid rows remained silent; rapid truncate+rewrite could regrow beyond old offset and retain stale counters. This revision counts invalid-schema lines, keeps true duplicate-ID suppression, resets on inode or consumed-head/tail mismatches, with offline regression for both same-inode rewrite and atomic replacement. Bounded edge fingerprints are not tamper-proof against adversarial interior rewrites.

- Codex round on head `79a4af64...` found 3 P2: conflicting duplicate IDs, mismatched event/code combinations (already addressed on `0cdf...`), and GUI stats not clearing when replacement has no valid records. Current correction hashes canonical accepted event records for exact-replay verification and signals `changed=True` on reader generation resets. Memory usage increases to store one compact fingerprint per accepted event ID; no original prompt/output stored.

- 2026-10-21 latest Codex P2 follow-up: Python permissive JSON parser accepted NaN/Infinity/-Infinity as valid complete events; whitespace-only event_id entered denominators. Fixed with rejecting parse_constant, stripped ID validation, strict direct-mapping allow_nan=False and focused regressions. This does not certify upstream CSV/XLSX sink persistence or live LLM acceptance.

- 2026-10-21 PR #219: explicitly null `scope` is not equivalent to absent (legacy) `scope`; repaired the distinction. Full Linux CI is still blocked by jobs failing before runner allocation; this does not establish a successful pytest execution.

- 2026-10-21 PR #219: deeply nested JSONL input could raise RecursionError and abort offline report or strand Tk reader. This is now classified as a complete corrupt line with a regression demonstrating later good events still count. No evidence that upstream 37k-row run or Windows deployed GUI has been validated with a real LLM after this change.

### 2026-10-22 LLM call failure taxonomy observational limitations

- Existing per-request CSV `llm_call_audit_*.csv` contains `ok` and an **unredacted** exception `error` field. New read-only report categorizes those error texts internally but never emits them; raw CSV itself must remain access-controlled. Classification is conservative heuristic, not a proof of provider root cause or worker/stage failure coverage. The statistics denominator covers valid `ok=YES/NO` call attempts only and must not be treated as document failure rate.
- Old audit records have no stable request UUID. The report intentionally counts observed rows, not deduplicated logical retries. Concurrent append, malformed/truncated CSV and bounded file sizes can prevent a complete report; fail closed rather than invent counts.


### 2026-10-23 Consumer-quality observation limitation

- New run-scoped Consumer orchestration incident counts cannot identify failed documents or provider root causes; stage-managed workers and Producer/Row Merger general exceptions are outside this narrow instrumentation. Multiple retries may refer to the same unfinished batch. Linux main offline E2E success is not real Windows/LLM/ES acceptance. **Status:** partial observation; live acceptance open.
