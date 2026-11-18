# GLM #337 — General-news Evidence source-sentence preference

## Scope and entrypoint

Active prompt: `czjLLM/task_configs/taskSetting_Enrichment.py`, `MULTIDIM_EXTRACTION_Rule`, shared by the two active `InfoExtraction-MultiDim*` task templates. This patch changes only the **general-news evidence** candidate ranking. Structured-record and per-item modes remain higher-priority and are not meant to inherit the preference.

When an article contains both an isolated date/heading/index token and a directly quoted complete event sentence, prefer the latter as primary Event evidence. A usable sentence identifies a supported subject and action/state plus necessary object/outcome. Date or numeric detail can help rank otherwise comparable sentences but is not alone proof of the action. Never splice sentences or Events, invent missing content, or discard a legitimate short source. Maintain exact quoted text, per-Event `event_ids`, at most 280 characters for a general-news snippet, existing event coverage/quotas, and no extra LLM call.

## Fixed synthetic source set

`tests/fixtures/news_evidence_prompt_cases.json` contains **candidate source spans**, not generated outputs. Cases cover (1) action vs date line, (2) date-only source, (3) two separately supported Events, (4) dated Event with empty Timeline, (5) structured-record mode exception and (6) an input exceeding 280 characters. `tests/test_multidim_news_evidence_prompt.py` checks actual shared prompt text, mode scoping, ordering and every expected quote being a literal substring of its case source. It deliberately does not claim an LLM followed the instructions.

## Required offline A/B before adoption decision

Run the original main prompt and candidate branch prompt against the exact six deidentified sources, with the *same* task, model, generation settings, input cut, run isolation and endpoint. Record per case: parseable JSON, valid event IDs, cross-event evidence mismatch, source-quote exactness, complete-action primary quote when one exists, preserved legitimate short evidence, Event count/kind, and 280-char behavior. For numeric metrics, record measured input/output tokens and total latency only if actually observed; do not invent cache hits or performance improvements. A/B counts should exclude provider failures from substantive quality claims and must show complete counts, not cherry-picked examples.

**Current status:** static source-level prompt change and synthetic contracts only. No real model A/B, GPU, news_test sample, SRAF writeback, reindex, rerun, or production deployment has been performed by this PR. Adoption remains pending Hosted CI, latest-head Codex Review, and model-backed A/B evidence.
