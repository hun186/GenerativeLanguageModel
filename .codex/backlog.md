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
- [x] 第一階段拆分 `czjLLM/utilities/combine_utils.py`：JSON parsing/repair 與 audited slice merge strategy 已移至 focused modules，舊路徑保留 re-export；prompt result filesystem orchestration 可於後續第二階段再拆。
- [ ] 評估 `utils/utilities.py` 是否仍為活躍依賴；若是，逐步改為 focused utility modules 並保留 re-export 過渡層。
- [x] 已拆分 `czjLLM/es_mode/adapters/elasticsearch_adapter.py` 的 freshness/rerun policy 與 value helpers；`czjLLM/es_mode/entry/steps_es.py` 仍可後續獨立評估。

## 2026-09-18 Reduction Engine v1 implementation roadmap (not implemented)

- [ ] PR A：Characterization / Golden Tests（production behavior change: NO）。
- [ ] PR B-C：Reducer registry + legacy adapters；strict opt-in single-pass routing。
- [ ] PR D-E：hierarchical controller/checkpoints；shared inherited Execution Budget。
- [ ] PR F-G：Logical Work Unit/immutable Collection Manifest；SQL/ES snapshot adapters與 idempotent aggregate upsert。
- [ ] PR H-J：deterministic composite、semantic、structured relational reducers。
- [ ] PR K-L：bounded ReductionStage/PipelineRef nesting；retention/GC與 production hardening。
- [ ] PR #177 reviewer 需比對 supplied clone 中缺少的 `eaaf89e...` draft，確認 v2 重建版未遺漏仍有效決策。
