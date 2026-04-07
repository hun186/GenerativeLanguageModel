# Pipeline Skeleton Guide (Deep Integration Edition)

## Purpose

Define the minimal but production-aware scaffold.

## Structure

```text
pipeline/
  pipeline_context.py
  pipeline_types.py
  pipeline_config.py
  pipeline_utils.py
  pipeline_controller.py
  steps/
    chunk_summary.py
    doc_type_classification.py
    extraction_multidim.py
    merge_multidim.py
  merge/
    base_strategy.py
    merge_selector.py
    *.py
```

## Design rules

1. `pipeline/` is orchestration only
2. `prompt_pipeline/` keeps LLM execution
3. existing runtime remains operationally important
4. steps are thin wrappers
5. no logic duplication
6. merge is strategy-based
7. scaffold must leave room for runtime adapter, stage trace, dispatcher compatibility, monitoring metadata flow

## Must avoid

- moving LLM logic into `pipeline/`
- rewriting extraction
- detached scaffold that ignores actual runtime
- losing monitoring / downstream compatibility

## Goal

> minimal stable scaffold that plugs into the repo's real execution flow
