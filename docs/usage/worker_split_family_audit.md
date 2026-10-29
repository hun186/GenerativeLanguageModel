# Worker call ⇄ verified JSON split intent

A real Worker verifies the current TODO/RUNNING file against the *exact* sent prompt using a bounded-memory 64-KiB streaming text digest **before** `CallLLMAPI`. Following local JSON repair, it reads the existing SHA256/UUID4 version-1 split-intent journal and writes optional `split_family_id` with `worker_call_id` and explicit `call_llm_api_returned` in the same CSV/XLSX audit row. This includes the first failed parent whose journal is only created **after** that model call, plus source-matched child/nested splits.

No file, mismatch, symlink alias, missing/legacy/corrupt journal, or non-Worker invocation => unknown/blank. Four historical complete audit header widths remain unchanged when appending; read-only `llm_failure_report` v1 counts observed rows as before, not logical retries/documents. The new ID is an unauthenticated local **split-intent** consistency link: not proof children committed, an SDK/HTTP attempt, general restart/requeue, unique document, ES/SQL acknowledgement, or a race-free crash checkpoint. Do not log raw prompt content into new correlation fields.

`tests/prompt_pipeline/test_worker_split_family_audit.py` uses real filesystem journals, real Worker processing and CSV/XLSX, with an isolated provider. Hosted Linux `offline-e2e` also runs pre-existing split/resume/report/immutable archive tests. Windows/Ollama/ES integration remains deferred.

Additional hardening after first formal Codex review: the in-memory sent prompt is also SHA256-hashed in 64-KiB chunks with cross-boundary CRLF correctness; the entire absolute/relative path ancestor chain is checked for symlinks for both the queued-source proof and later journal lookup. No claim of protection against an active malicious TOCTOU attacker.
