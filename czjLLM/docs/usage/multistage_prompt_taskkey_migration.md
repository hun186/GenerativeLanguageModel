# Multistage YAML 遷移指南：`prompt` + `task_key` 明確分流

## 目的

在多階段設定中，建議把兩種語意分開：

- `prompt`：直接給 LLM 的自訂文字任務（freeform）
- `task_key`：指向 `taskSetting` 既有任務鍵值（named task）

這樣可避免把「任務名稱」與「提詞內容」混在同一欄位造成維護混亂。

---

## 建議規則

1. 需要直接寫提示詞時，用 `prompt`。  
2. 想重用既有任務模板時，用 `task_key`。  
3. 盡量不要在新檔案使用舊欄位 `task`（僅保留相容）。  
4. 同一個 stage 優先選擇一種主要來源（`prompt` 或 `task_key`），避免語意不清。

---

## 轉換範例

### 舊寫法（混用 `task`）

```yaml
stages:
  - name: route
    task: |
      你是分類器...
  - name: extract
    task: Organization Profile Analyzer to json format
```

### 新寫法（分流）

```yaml
stages:
  - name: route
    prompt: |
      你是分類器...
  - name: extract
    task_key: Organization Profile Analyzer to json format
```

---

## 建議遷移策略（分批）

### Phase 1（立即可做）
- 先改「最常用／正在維護」的 YAML。
- 舊 YAML 保持可執行（相容模式），避免一次改壞全域。

### Phase 2（穩定後）
- 批次把明確是 freeform 的 stage 改成 `prompt`。
- 批次把明確是任務名的 stage 改成 `task_key`。

### Phase 3（治理）
- 在 code review 規範中要求新 YAML 不再新增 `task` 混用。

---

## 驗證建議

每次批次轉換後至少跑：

```bash
PYTHONPATH=. pytest -q tests/prompt_pipeline/test_stage_config.py
PYTHONPATH=. pytest -q tests/prompt_pipeline/test_simulated_multistage_e2e.py
```

若要跑 CLI E2E，需先確認：
- `model_spec` 在本環境可解析
- SQLite `server` 指向可讀寫檔案路徑

