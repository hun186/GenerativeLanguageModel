# LLM Worker call identity (after audit-row UUID)

The production `PromptAPIPipeline.proc()` now generates one opaque
`worker_call_id` immediately before the explicit `CallLLMAPI(...)`
invocation and passes it into `log_llm_call` after the Worker has settled its
local response processing/persistence. Newly created CSV/XLSX runs expose
`worker_call_id` as a **trailing** column after `audit_record_id`.

## What this ID means

- It identifies **one explicit Worker-side invocation boundary** within the
  current process execution; a new invocation gets a new random UUID4 hex.
- If the local `CallLLMAPI` invocation raises, the caught exception path
  still carries the original ID to the existing best-effort CSV logger.
- Pre-call failures and synthetic/mock runs do not fabricate Worker call IDs
  because no `CallLLMAPI` invocation was attempted.
- `audit_record_id` continues to identify the **written CSV row** and is
  separately generated when logging; it can differ from `worker_call_id`.
- Direct `log_llm_call` users without a genuine Worker call boundary leave
  this optional column empty, rather than guessing from prompts, timestamps
  or errors. Invalid nonempty IDs fail before touching audit files.

**This is not provider HTTP-request identification.** The downstream SDK or
`CallLLMAPI` implementation may perform lower-level retries, reconnects or
other actions not individually observable at this boundary. A crash before
the audit append may leave no CSV row. Returning success from this audit is
not proof of provider acceptance or ES/SQL sink readback. Repeated calls for
the same prompt or task do **not** have an established logical retry-family ID.
The CSV `ok` flag is still a local postprocessing result, not a provider
root-cause classification.

## Backward compatibility

The append writer accepts only three **exact** historical header generations:

1. New run: `...error,audit_record_id,worker_call_id`.
2. Prior #245 run: `...error,audit_record_id`.
3. Before #245: `...error`.

For both older generations the original header and row width remain unchanged;
no retroactive IDs or audit source rewriting is performed. Other mismatched
headers fail closed to avoid silent column shifting. The XLSX exporter reads
the actual on-disk CSV header. All `llm_failure_report` report-v1 metrics,
optional time-window filtering, history budgets, and payload-redaction rules
remain unchanged. The read-only report does **not** expose either ID.

## Validation scope

Regression tests check the Worker call-site code boundary, CSV/XLSX actual
values for explicit versus absent Worker call IDs, independent audit-row UUIDs,
both legacy header generations, invalid input rejection, and existing failure
report observed-row denominators. Hosted Linux CI and exact-head official
Codex Review are required before merge. Physical Windows runners, real
Ollama/ES readback, logical retry accounting and authenticated checkpointing
remain separate operator-gated/future tasks. Independent PR #231 is untouched.
