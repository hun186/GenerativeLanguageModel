# Verified split retry family — bounded journal identity

The existing single-extract JSON-repair fallback uses
`install_split_prompts(parent, original_prompt, children)` to write a
**persisted split intent** in
`<item>/_extract_slice_identity/splits/<parent>.txt.json` **before** it
installs the two replacement child prompts. This change adds an opaque random
`split_family_id` (32 lowercase UUID4 hex characters) to newly written
version-1 split-intent journals. No raw prompt or LLM output is written to
the journal. The existing SHA256 evidence remains unchanged.

## Actual meaning

- `record_split_identity` generates an independent random ID for a **new
  explicit split**. If the same parent and prompt are already matched by an
  existing journal with a valid family ID, it preserves the ID.
- A **nested split** inherits the family ID only when its current prompt
  matches the recorded SHA256 of a direct child in the existing
  parent journal. This survives the existing TODO → RUNNING transition because
  journal references use the item root and child basename.
- `verified_split_family_id(prompt_file, prompt)` returns the ID only
  after checking that the prompt is a queued parent or an explicitly recorded
  `-0`/`-1` child, that its actual SHA256 matches the journal and that
  the journal has the canonical two-child shape and valid opaque ID.
  Filename matching selects the candidate journal **but is never sufficient
  evidence by itself**.
- The reader touches at most one direct-parent and one own bounded intent;
  oversized or symlink intent files are not used as evidence.
- Version-1 journals written before this change contain no ID; the reader
  returns **unknown** (empty string) for them rather than inventing an ID.
  The next explicit split of a verified source can create a new family ID,
  but cannot prove historical parent call identities retroactively.

This is a **persisted split-intent family**, not a unique LLM logical
request, external dispatch, original document, completed two-child
replacement, provider HTTP retry, transport retry or evidence of final
Success/ES sink acknowledgement. A journal is a *locally stored,
unauthenticated* source of evidence: SHA256 checks provide consistency against
the stored prompt text, not cryptographic authenticity. Never treat the ID
as an authorization secret, cross-run global document identity or complete
failure denominator. Stopped/recovered RUNNING→TODO items are *not* classified
as retries just because they share a name.

## Scope and compatibility

The existing version-1 journal keys and producer flow are retained. Added
`split_family_id` is optional to all existing consumers, whose resume,
rollback, Success and nested-split verification still use the authoritative
content hashes. No SQL/ES/LLM request scheduling, worker ID generation,
CSV/XLSX audit schema, v1 failure report, quality JSONL, or automatic
retention/deletion changes. The follow-on work to associate **actual
Worker calls** with verified persisted split families must be separately
designed and tested; no retry success rate is claimed here.

Validation: dedicated filesystem tests cover parent/child/nested inheritance,
exact prompt digest refusal, legacy unknown, invalid/bad journal content and
symlink refusal, and unrelated requeues. Hosted Linux CI explicitly runs
the new suite, alongside its unchanged offline E2E and immutable archive gate.
Physical Windows/Ollama/ES acceptance remains operator-gated. Independent
PR #231 is neither modified nor merged.
