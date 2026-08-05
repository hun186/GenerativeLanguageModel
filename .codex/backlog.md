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

## 2026-08-05 class-tree boundary migration backlog

- [ ] 新增 class-tree root 設定（CLI / YAML / env 擇一或集中設計），讓 `TopicTree.csv`、`TopicTree_AK4.csv`、`TopicTree_PAK.txt` 可由專案內路徑載入。
- [x] 本 checkout 中的 `RawAndPredictionMerger.GetInfoScoreTable()` 已改用 resolver：明確設定 > `CLASS_TREE_ROOT` > `config/class_trees/default/` > legacy TACA fallback；仍需在實際 `ClassesTree/ClassesTree_utils.py::SetTreeFiles()` 接入同一 resolver。
- [x] `utils/class_tree_paths.py` 缺少類別樹檔案時會輸出所有候選路徑；仍需把使用者實際 stack 中的 `SetTreeFiles()` 改成使用此 resolver。
- [ ] 補充 TACA 匯出 CSV 到分類專案 config 目錄的同步文件或工具。
