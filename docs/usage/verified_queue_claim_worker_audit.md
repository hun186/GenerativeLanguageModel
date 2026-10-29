# Verified queue-claim → Worker call correlation (phase 2a)

This change extends the accepted phase-1 best-effort filesystem queue observations. It **does not** create a retry family or claim to count all attempts.

## Trusted in-process handoff

- The existing TODO→RUNNING `os.replace` is still the authoritative act of claiming one file. `pick_and_claim_next_prompts(..., claim_ids_out=...)` preserves its **existing two-tuple return shape** while optionally returning event IDs from that exact successful rename in an out-parameter mapping keyed by returned running paths. If the event write fails, no ID is handed off and work continues.
- Only `llm_stream_consumer` uses this optional evidence map, directly passing `queue_claim_event_id` into each `PromptAPIPipeline`. Other call paths get no claimed queue ID; the prior behavior remains unchanged.
- Immediately before the real `CallLLMAPI` invocation, the Worker already checks that its sent prompt matches the real queued source file; then `verified_claim_observation` checks the **explicitly supplied** canonical UUIDv4 receipt against the bounded actual JSON event file and the current actual `RUNNING/*.txt` byte SHA256, size and filename hash. It rejects a missing, requeued, corrupt, symlinked or mismatched receipt. It never guesses an ID by searching the directory for a matching filename or SHA256.
- On a real attempted wrapper invocation (normal return or caught error), the existing best-effort single audit CSV/XLSX row may contain the new final `queue_claim_event_id`. Its UUIDv4 shape and Worker boundary are validated before append. Newly created audits use this additional column; exactly five full predecessor CSV headers are retained at their original width. The existing `audit_record_id`, `worker_call_id`, `split_family_id`, `call_llm_api_returned` and failure-report v1 denominators retain their previous meaning.

## Limits and safe interpretation

An observed nonempty `queue_claim_event_id` supports one **trusted local dispatcher → one observed Worker call** correlation, not provider acknowledgement, SDK internal retries, unique document identity, a durable completion checkpoint, or a cross-dispatch logical retry group. The same source may be requeued and claimed with a **new** event ID without a verifiable generation or a proved prior claim chain. Empty IDs mean **unknown**, not 'never claimed'. The filesystem hashes are local consistency evidence, not authenticated tamper protection; a hostile local editor/race, crash between rename and record, failed audit row write and non-streaming/stage-managed queue routes are outside the proof.

## Verification

Hosted Linux `offline-e2e` includes tests/prompt_pipeline/test_worker_queue_claim_audit.py and test_worker_split_family_audit.py, covering actual file rename → queue receipt → isolated real Worker invocation → persisted CSV, subsequent requeue and new claim, stale/mismatched prompt, malformed receipt, and legacy header compatibility. Physical Windows/Ollama/ES/SQL acceptance is operator deferred.
