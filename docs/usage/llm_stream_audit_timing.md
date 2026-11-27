# Persisted SSE timing (WEB-05B1)

New runs append five fields to Audit CSV and its XLSX projection:
stream_timing_source, stream_ttft_seconds, stream_first_thinking_seconds,
stream_first_content_seconds, stream_chunks. Only the completed production
OpenAI-compatible SSE assembler supplies the fixed client-monotonic source.
TTFT is the first nonempty thinking or answer text, not first HTTP byte,
provider prefill or GPU phase. Absent text has blank timing; an explicit
zero is valid. Invalid/unsupported metadata is blank, not estimated.
Nonstream and incomplete/error responses without a completed observation
have no phase timing; downstream postprocessing may fail after a valid
completed response, so audit ok and timing availability are independent.

All seven previously accepted complete header generations are retained.
Existing audit CSV files are appended using their existing header and
cannot gain these columns mid-run. Partial new suffixes fail closed.
No extra API call, no prompt/thinking/answer payload stored by this suffix,
no changed retry/timeout or model config. Native Ollama timing remains
in the separate probe; do not equate TTFT to prefill or import unrelated
probe measurements into the production audit. Shared UI distributions
and verified native production transport remain subsequent work.
