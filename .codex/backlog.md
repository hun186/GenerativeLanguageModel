# 待辦事項（Backlog）

## 高優先度

- 

## 中優先度

- 

## 低優先度

- 

## 技術債

- 

## 未來構想

- 

## 

- 
## 2026-07-14 large file split backlog

- [x] 初步拆分 `czjLLM/prompt_pipeline/pipeline_controller.py`：已抽出 registry/load meter、prompt queue、watchdogs，並集中到 `prompt_pipeline/runtime_support/`，保留相容匯入；LLM dispatch 與多階段 orchestration 可留待後續第二階段。
- [ ] 拆分 `czjLLM/utilities/combine_utils.py`：分離 JSON parsing/repair、prompt result combiner、audited merge strategy 與 legacy compatibility。
- [ ] 評估 `utils/utilities.py` 是否仍為活躍依賴；若是，逐步改為 focused utility modules 並保留 re-export 過渡層。
- [ ] 評估 Elasticsearch mode 大型檔案：`czjLLM/es_mode/adapters/elasticsearch_adapter.py` 與 `czjLLM/es_mode/entry/steps_es.py`。
