# Queue recovery and Worker Success preservation (phase 2c)

## RUNNING → TODO recovery

The production `recover_running_to_todo(item_dirs)` API keeps its integer return value (completed real moves only). For each normal or nested RUNNING file it now uses the same exclusive, inode-verified hardlink + source unlink helper as accepted PR #253's TODO→RUNNING claims. If a destination TODO file/symlink already exists, the source is aliased, the filesystem cannot hardlink, the unlink fails, or a competing recovery wins, **do not overwrite** the prior TODO. Leave the RUNNING file intact where possible; a crash between hardlink and unlink may leave both paths and is **not** counted as recovered. Only successful moves emit the existing best-effort `requeued` event, never a logical retry-family or HTTP request.

The existing public two-tuple `pick_and_claim_next_prompts` result and optional exact claim receipt mapping are unchanged. Additionally, a preexisting `Success/<basename>` now prevents a new flattened TODO→RUNNING claim for that basename. This avoids adopting an old output as proof that a new Worker already completed. Disambiguate or explicitly reset prior Success before retrying; this policy does not remove either conflicting source or result.

## Worker Success publication

Direct `PromptAPIPipeline.proc` Success writes (real LLM and explicitly configured mock mode) use `publish_success_text_no_clobber`, which writes a unique same-directory UTF-8 temp file and fsyncs it, then publishes its inode with atomic exclusive `os.link`. Prior Success files, including symlinks, cannot be replaced. An existing Success raises a file-exists persistence error to the existing Worker exception path, and RUNNING is not unlinked. Successfully published Success is followed by existing `record_success_identity` and optional RUNNING cleanup semantics. A competing writer can win only once; no unsafe `os.replace` fallback for filesystems lacking hardlinks. Unique staging files are unlinked on conflict, not counted as published output. The explicit oldest alternative legacy Worker code path is updated too.

## Limits

Exclusive hardlink publication does **not** provide a cross-process transaction for the subsequent unlink, nor prove a persistent source generation, trusted Retry Family, end-to-end exactly-once processing, or acknowledged ES/SQL sink. A successful Success publication can precede a crash in identity bookkeeping or cleanup and requires existing recovery logic; the result and source may coexist, but neither is silently overwritten. Uncooperative writers, filesystem TOCTOU, manually staged symlinks, nested stage orchestration, intentionally forced overwrite workflows, Windows/SMB hardlink support and other Success writers outside `PromptAPIPipeline.proc` are separate acceptance/safety surfaces. Preserve input and operator evidence rather than auto-fixing conflicting files.

Hosted Linux offline E2E runs actual file-based recovery, nested and conflicting TODO, staged output collisions and competing writers, plus isolated real Worker calls and all established queue/quality/archive regressions. Windows/Ollama/ES/SQL real host operator acceptance remains deferred.
