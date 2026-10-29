# Bounded queue transition observations (phase 1)

This phase records an actual filesystem state transition, not an inferred retry.

- After pick_and_claim_next_prompts successfully renames TODO to RUNNING, a 'claimed' event may be recorded.
- After recover_running_to_todo or the streaming consumer timeout branch successfully renames RUNNING to TODO, a 'requeued' event may be recorded.
- Other worker-managed queue changes are not exhaustively instrumented. A crash after rename and before audit can leave a missing event; event-write failures never stop a queue move.

Events are kept under each item in _extract_slice_identity/queue_events/<random UUID4>.json. Each record has version, event, event_id, source_sha256, source_bytes, queue_name_sha256 and observed_at_utc. File content is streamed from the actual moved regular file. No plaintext prompt, filename, local path, endpoint, model name, response, error or credential is persisted. SHA256 digests are NOT guaranteed anonymous when values are guessable.

The read-only function summarize_queue_observations(item_dir) in czjLLM.prompt_pipeline.runtime_support.queue_observation validates complete bounded records and returns observed_claims / observed_requeues. Missing event files and telemetry write failures result in incomplete observation, not queue failure; malformed/symlinked/oversized records fail closed. Counts are NOT logical retry groups or accurate queue depth and must never be divided into a retry rate.

An event UUID identifies only one observed rename. It is not a worker_call_id, audit_record_id, split_family_id, source-document identity, provider/SDK HTTP request, successful ES/SQL writeback, or durable exactly-once dispatch checkpoint. Same pathname or source hash does not prove two attempts belong to the same logical retry family. Verified source generation/lease, checkpointing and Worker attribution are separate future tasks.

Hosted Linux CI runs actual file move and append/read regressions. This does not establish Windows hardlink availability or real Ollama/ES/SQL integration.
