# Queue claim no-clobber behavior (phase 2b)

## Why this exists

Previously, the streaming queue flattened two nested sources such as `TODO/a/root.txt` and `TODO/b/root.txt` into `RUNNING/root.txt`, then used `os.replace` to rename each source. The second successful rename **overwrote** the first source's bytes. A pre-existing `RUNNING/root.txt` could likewise be replaced while a Worker was still processing it. The phase-2a claim evidence suppressed mistaken lineage, but did not preserve source bytes.

## Narrow behavior change

- Before claiming from each item, enumerate actual TODO file candidates and count basenames. If multiple TODO entries have the same basename, **none of that basename is claimed**, both stay in TODO for an operator to rename/disambiguate. Other unique basenames may still run. The queue API returns the same `(RUNNING path, item directory)` pairs; only completed moves are returned.
- For an unambiguous candidate, require a regular, unaliased source file (`st_nlink == 1`) and non-symlink path ancestry. Publish its existing inode under `RUNNING/<basename>` with `os.link(src,dst,follow_symlinks=False)`; **hardlink creation atomically fails if `dst` already exists**. Confirm both paths refer to the same inode, then unlink TODO. Only after that successful unlink is the claim eligible for dispatch and queue-event recording. Never fall back to unsafe `os.replace` when hardlinks are unsupported, target exists, source changed, or unlink fails. The original remains in TODO where possible. Claim telemetry remains best-effort and cannot prevent a successful move.
- The existing observation handoff and `queue_claim_event_id` stay attached only to successful claims. Fail-closed conflicts are not completed dispatches, LLM requests, retry groups or successes.

## Operational limits

- This policy **intentionally blocks** ambiguous nested same-basename sources. Rename or otherwise disambiguate the TODO files before resuming; inspect pending queue items rather than trying to force-replace RUNNING. Even a single candidate with a basename already in RUNNING must wait until that conflict is resolved.
- Hardlinks require the source and RUNNING directories to be on a hardlink-capable filesystem and share a volume. Unsupported FS, protected files, symlinks or existing hardlinks are not dispatched; no unsafe copy/rename fallback is provided.
- Link creation + source unlink are **not one crash-atomic transaction**: if a process dies in that window, it can leave both `TODO/name` and `RUNNING/name` referencing the same inode. This should be treated as ambiguous recovery evidence, not two successful claims. Do not automatically delete either copy without independent evidence.
- This change does **not** make the later `RUNNING→TODO` recovery and `RUNNING→Success` writes no-clobber; those other transitions need independent safety reviews. It also does not fix competing noncooperating writers, logical Retry Family, provider HTTP retries, sink acknowledgements or full source-generation identity.

## Verification

Hosted Linux CI runs actual filesystem tests of preexisting RUNNING collision, nested duplicate name preservation, ordinary exclusive claim/receipt, unsupported hardlink, interrupted source unlink, two-thread competition, and symlink handling; previously accepted queue/Worker provenance tests are rerun. The project still requires formal Codex Review and latest exact-head Hosted CI prior to merge; Windows real-hardware behavior and Ollama/ES/SQL remain operator-deferred.

**Consumer shutdown:** if the producer has stopped and two consecutive claim attempts find no claimable sources, the streaming consumer checks all item TODO directories. Any remaining file (including a deferred same-basename conflict or unsupported hardlink source) raises a payload-free orchestration failure and keeps the files pending, rather than silently declaring the queue drained. It does not automatically rename/de-duplicate those files.

**Actual SQL/Table/ES completion coordination:** the producer's `_producer_done_flag` (not teardown-only `stop_event`) is shared with the real streaming consumer before threads start. With producer done, no claimable TODO, and no metered or filesystem RUNNING work, any pending TODO signals `_queue_claim_blocked_event`; the consumer emits its existing orchestration incident and exits. The coordinator checks that event before its pending==0 completion gate, proceeds through normal teardown and marks the run `failed` with reason `unclaimable_queue_sources` even if later writeback classification differs. This avoids an indefinitely polling run and prevents false `completed` status; no source is deleted. Operator must fix conflicts or filesystem support before retrying. It is not a source-generation/Retry Family proof.

**Terminal Row Merger shutdown:** an unclaimable queue leaves its registry entries intentionally present. After the blocked-queue event and teardown stop_event are both set, the actual Row Merger performs at most one final normal scan for already-ready writebacks and exits, even with registry entries left. It does **not** clear those blocked rows, fabricate Success, or delete TODO/source files. The coordinator can complete shutdown and label the run failed. Retryable sink failures during this final scan leave replay artifacts intact; no unbounded retries during terminal blocked shutdown.
