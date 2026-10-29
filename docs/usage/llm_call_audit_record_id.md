# LLM call audit: per-record UUID (independent change)

Newly created `llm_call_audit_<run_id>.csv` and its generated XLSX export now
include a trailing `audit_record_id` column. Each invocation that emits an
audit row creates an opaque random UUID4 (32 lowercase hex characters). The ID
is an **audit-row identity**, not a provider-side request identifier, source
document identifier, retry-family key, semantic correlation key or confirmed
sink write acknowledgement. Re-running the **same** LLM request may produce a
new ID; a request that fails before audit logging may have **no** row. Neither
a successful audit write nor the ID proves an actual provider response.

## Backward compatibility

- A newly created CSV gets the UUID column as the **last** column, keeping
  existing columns and their order intact.
- When appending to a pre-upgrade CSV whose header is exactly the immediately
  preceding known schema (all fields except the trailing ID), the audit writer
  continues using that header and does **not** retroactively populate IDs.
  No existing rows or their bytes are rewritten.
- Unsupported or malformed pre-existing CSV headers are rejected rather than
  appending misaligned columns; the original CSV is left unchanged.
- Existing historical CSV snapshots with no ID remain valid input for the
  read-only `llm_failure_report` CLI. Its v1 JSON output and observed-call
  attempt denominators are unchanged. It does **not** export these IDs.
- New XLSX exports naturally inherit the CSV's actual header, so old running
  audits remain in their original column layout. The XLSX file is an audit
  convenience export, **not** an identity ledger for deduplicating provider
  requests.

## Validation and limits

Focused tests create real files: two calls with same task/time obtain distinct
UUIDs in CSV and XLSX; old-header continuation preserves exact column count;
incompatible headers fail closed; and the existing read-only failure summary
still counts both observed call rows. Hosted Linux CI is the approval gate;
Windows/PSAPI/Tk and real Ollama/ES writeback/readback remain operator-deferred.

Privacy: IDs are generated independently from prompts, paths, model endpoints,
request/response contents and error messages; they are not hashes of private
inputs. Do not treat a UUID as an authorization token or expose raw audit files
to untrusted users. Joining audit rows to **true** attempts and retries still
requires a future source-authoritative lifecycle/dispatch design and tests.
