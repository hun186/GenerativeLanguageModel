# GLM #337 — General-news Evidence source-sentence preference

## Scope and entrypoint

Active prompt: `czjLLM/task_configs/taskSetting_Enrichment.py`, `MULTIDIM_EXTRACTION_Rule`, shared by the two active `InfoExtraction-MultiDim*` task templates. This patch changes only the **general-news evidence** candidate ranking. Structured-record and per-item modes remain higher-priority and are not meant to inherit the preference.

When an article contains both an isolated date/heading/index token and a directly quoted complete event sentence, prefer the latter as primary Event evidence. A usable sentence identifies a supported subject and action/state plus necessary object/outcome. Date or numeric detail can help rank otherwise comparable sentences but is not alone proof of the action. Never splice sentences or Events, invent missing content, or discard a legitimate short source. Maintain exact quoted text, per-Event `event_ids`, at most 280 characters for a general-news snippet, existing event coverage/quotas, and no extra LLM call.

## Fixed synthetic source set

`tests/fixtures/news_evidence_prompt_cases.json` contains **candidate source spans**, not generated outputs. Cases cover (1) action vs date line, (2) date-only source, (3) two separately supported Events, (4) dated Event with empty Timeline, (5) structured-record mode exception and (6) an input exceeding 280 characters. `tests/test_multidim_news_evidence_prompt.py` checks actual shared prompt text, mode scoping, ordering and every expected quote being a literal substring of its case source. It deliberately does not claim an LLM followed the instructions.


## Read-only A/B output comparator (does not call the model)

After an operator has run the **same six fixed deidentified inputs** using both the original main prompt and this candidate prompt, save each **raw model response as a UTF-8 JSON array** (not a wrapped object or a JSON markdown fence). Put all six files in each of two **separate local directories**, using the exact case_id filenames defined by tests/fixtures/news_evidence_prompt_cases.json: news_action_over_date.json, only_date_no_action.json, two_distinct_events.json, event_date_empty_timeline.json, structured_record_unchanged.json, news_280_boundary.json.

Run **only after model outputs exist**:

    python scripts/compare_multidim_news_evidence_ab.py --baseline-dir PATH_TO_BASELINE --candidate-dir PATH_TO_CANDIDATE

This script never calls an LLM, modifies a file or fetches ES/SQL/Queue data. It checks complete six-pair presence, parseable strict JSON, one native top-level JSON array containing a single object, native Event/evidence arrays, unique Event IDs, valid references, literal substring source quotes, per-Event evidence coverage, 280-character general-news bound and matching the fixed candidate quote spans. For readability, its JSON report contains **only case identifiers and numeric/boolean aggregate observations**, never actual raw snippets, paths, source content, tokens or credentials. Invalid/missing/oversized/symlinked result files are reported using fixed codes; missing or unparseable pairs make the CLI exit nonzero. Run-specific logs and model parameters are **not collected or verified** by this script.

An exact fixed-source quote match is a *candidate coverage metric*, not proof that other valid word-for-word snippets are worse. A passing parser/metric report is **not a real-model A/B success certificate**; independently verify identical endpoint/model/temperature/context/input cut, request counts, request completion, semantic accuracy, Event count, any provider errors, and whether the six outputs are actually from the two indicated prompt versions. Do not put raw private articles or complete model responses into PR comments or public CI logs.

## Required offline A/B before adoption decision

Run the original main prompt and candidate branch prompt against the exact six deidentified sources, with the *same* task, model, generation settings, input cut, run isolation and endpoint. Record per case: parseable JSON, valid event IDs, cross-event evidence mismatch, source-quote exactness, complete-action primary quote when one exists, preserved legitimate short evidence, Event count/kind, and 280-char behavior. For numeric metrics, record measured input/output tokens and total latency only if actually observed; do not invent cache hits or performance improvements. A/B counts should exclude provider failures from substantive quality claims and must show complete counts, not cherry-picked examples.

**Current status:** static source-level prompt change, synthetic contracts and a read-only A/B output evaluator only. No real model A/B, GPU, news_test sample, SRAF writeback, reindex, rerun, or production deployment has been performed by this PR. Adoption remains pending Hosted CI, latest-head Codex Review, and model-backed A/B evidence.
