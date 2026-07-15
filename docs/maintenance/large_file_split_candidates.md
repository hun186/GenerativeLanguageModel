# Large Python File Split Candidates

Generated on 2026-07-14 as a static maintainability audit. The line counts exclude common generated/cache/data directories and focus on Python source files that are likely to benefit from modularization.

## Top candidates

| Priority | File | Approx. lines | Main reason to split | Suggested split direction |
| --- | --- | ---: | --- | --- |
| 1 | `czjLLM/prompt_pipeline/pipeline_controller.py` | 2,971 | Mixes registry state, queue claiming, LLM consumers, watchdogs, multistage orchestration, retry logic, and pipeline facade classes in one module. | Extract queue/registry helpers, watchdogs, LLM caller wrappers, multistage orchestration, and facade/retry classes into focused modules under `czjLLM/prompt_pipeline/`. |
| 2 | `czjLLM/utilities/combine_utils.py` | 2,200 | Combines JSON parsing/repair, API result combination, legacy combination paths, and audited dictionary/list merge strategies. | Split into JSON parsing/normalization, prompt-result combiner, audited merge strategy, and legacy compatibility modules. |
| 3 | `utils/utilities.py` | 1,656 | General-purpose catch-all containing text normalization, regex helpers, file/hash helpers, archive extraction, date parsing, formatting, and console helpers. | Create focused utility modules (`text_utils`, `archive_utils`, `hash_utils`, `date_utils`, `console_utils`) and keep backwards-compatible re-exports during migration. |
| 4 | `czjLLM/es_mode/adapters/elasticsearch_adapter.py` | 1,107 | One adapter class owns connection setup, schema/index management, querying, flattening/extraction, reset/writeback, and value normalization helpers. | Split low-level client/connection concerns, schema/index operations, query builders, document extraction, and writeback/update operations. |
| 5 | `czjLLM/es_mode/entry/steps_es.py` | 775 | Entry-step module includes connection resolution, column selection, schema checks, reset behavior, prefetch iterators, and pending iteration. | Move connection/config resolution, schema preparation, prefetching, and pending iteration into separate entry helpers. |
| 6 | `czjLLM/job_manager/job_config.py` | 606 | Configuration parsing and runtime defaults are concentrated in a single job-manager module. | Split typed config models/defaults from environment/CLI resolution helpers if future job-manager changes grow. |
| 7 | `czjLLM/es_mode/runtime/sinks/es_sink.py` | 604 | Runtime sink logic likely mixes serialization, batching, and Elasticsearch write semantics. | Split bulk payload construction, response/error handling, and sink orchestration if touched again. |
| 8 | `czjLLM/tabular_mode/entry/steps.py` | 589 | Tabular entry setup includes several workflow steps in one module. | Split data-source setup, column selection, pending iteration, and output reset helpers. |
| 9 | `czjLLM/sql_mode/runtime/row_merger_generic.py` | 560 | Generic row merger handles polling/watchdog behavior, merge readiness, and writeback release coordination. | Split watchdog loop, item readiness predicates, writeback invocation, and pending-console release concerns. |
| 10 | `czjLLM/sql_mode/runtime/orchestrator.py` | 508 | Runtime orchestration coordinates producer, scheduler, row merger, and lifecycle handling. | Split lifecycle orchestration from runtime wiring if more modes are added. |

## Immediate refactor recommendation

Start with `czjLLM/prompt_pipeline/pipeline_controller.py` because it is the largest file and contains multiple clearly separable responsibilities. A low-risk first pass would be extraction-only: move helper functions without changing public call sites, then keep compatibility imports from the original module until downstream imports are updated.

Recommended first extraction sequence:

1. Move `ItemsRegistry` and prompt-claim/resume helpers into `prompt_pipeline/registry.py` or `prompt_pipeline/queue_state.py`.
2. Move `_stall_watchdog`, `_stall_watchdog_0119`, and watchdog startup helpers into `prompt_pipeline/watchdogs.py`.
3. Move LLM call wrappers and stream consumer helpers into `prompt_pipeline/llm_dispatch.py`.
4. Move multistage orchestration helpers into `prompt_pipeline/multistage_controller.py`.
5. Leave `PromptAPIPipeline`, `PromptRetryManager`, and compatibility imports in `pipeline_controller.py` until callers are migrated.

## Notes

- Files such as `utils/Edited_zipfile.py` and `utils/utilities - 複製.py` are large but appear to be standalone archive code or copied backup-style files; they should be reviewed separately before refactoring because they may be vendor-like or legacy backups rather than active core modules.
- Task configuration files such as `czjLLM/task_configs/taskSetting_Enrichment.py` and `czjLLM/task_configs/taskConfig_ANKInt.py` are large primarily because they store configuration literals. Splitting them is lower priority unless the project wants a dedicated YAML/JSON config migration.
