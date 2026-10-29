# Source-observed CallLLMAPI wrapper return (after #246 Worker call ID)

The production `PromptAPIPipeline.proc()` records a nullable
`call_llm_api_returned` observation for the actual invocation boundary.
It initializes the observation to `False` **before invoking** `CallLLMAPI`,
then changes it to `True` **only after** the Python wrapper returns normally.
The same observation is forwarded to the existing once-per-Worker-call audit
after local JSON processing and output persistence have settled.

Newly created per-run CSV/XLSX audit files add a final field:

- `worker_call_id`: the source-minted UUID of the Worker invocation.
- `call_llm_api_returned`: `YES` if the wrapper returned without raising;
  `NO` if that invocation raised; blank when no trusted Worker boundary
  observation exists (e.g. standalone logger callers).
- `ok`: the **unchanged** final local pipeline result after response parsing,
  JSON repair and output persistence. A `YES` return may coexist with
  `ok=NO` when any downstream local step fails. Conversely `NO` means
  `CallLLMAPI` raised, but says nothing conclusive about whether a remote
  service processed the request before a timeout.

**Neither `call_llm_api_returned=YES` nor `ok=YES` proves provider HTTP
acknowledgement, actual useful model content, a successful logical retry,
document success, or persisted ES/SQL sink acknowledgement.** Internal SDK
retries may occur inside one `CallLLMAPI` invocation. This column cannot
separate retries within the SDK, and it is not evidence of any retry family.
It does not attribute failures at earlier pre-call steps, mocked calls or
calls lost before audit append. It does not expand the read-only report v1
denominators; `llm_failure_report` will still count observed `ok` rows and
never export the IDs, raw exception text or this per-row outcome.

## Compatibility and privacy

The append writer accepts only complete known headers: current schema plus
three exact prior generations (with Worker ID, with audit-row ID, without
either). Existing CSV files keep their exact column count and never acquire
new fields by appending. Invalid/untrusted `call_llm_api_returned` values,
or an asserted observation without a valid `worker_call_id`, fail **before**
writing any CSV or XLSX file. Unknown old headers still fail closed. The XLSX
convenience export derives its column list from the actual CSV.

The field contains only YES/NO/blank, not prompts, model responses, endpoint
URLs, credentials, or exception payloads. Formal Hosted Linux regression CI,
immutable archive checks, and latest-head Codex Review are required before
Merge. Windows self-hosted, real Ollama/ES, source-authoritative logical retry
families, actual SDK HTTP-attempt evidence and production readback remain
independent tasks. PR #231 is untouched.
