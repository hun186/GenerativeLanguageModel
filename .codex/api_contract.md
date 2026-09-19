# api contract


---

## 


-

## 2026-08-20 ES model metadata contract

- `<output_col>_meta` 可保存 `model_tag`、`model_name`、`base_url_alias`、`num_ctx`、`temperature`、`model_version` 及既有 pipeline/task tracking fields。
- `base_url_alias` 必須是非敏感 alias，不得以實際 `base_url` 代替。
- `model_spec`、`base_url`、`api_key`、access/auth token、Authorization、password、client secret、private key 等 credential 不得寫入 ES metadata；ES sink 在 writeback boundary 會移除 credential-like keys。

## 2026-09-19 Reduction Engine PR D1 Python contract

- `reduce_hierarchical_text()` 僅接受 prepared text sequence、registered `concat_text` reducer、deterministic controller，以及 `next_round_items(previous_payload, next_round_index)` callback。
- Normal stop reasons 為 `target_reached`、`fixed_rounds_complete`、`max_rounds`、`stalled`；後兩者回傳最後有效 payload 並附 warning。Empty output、reducer failure、checkpoint corruption、checkpoint incompatibility 是不同 error paths。
- 此為 inactive Python seam，不是 production YAML/API contract；production 設定仍僅接受 PR C `single_pass`。

## 2026-09-19 PR D1 checkpoint execution identity corrective

- `reduce_hierarchical_text(..., checkpoint_root=..., execution_fingerprint=...)` requires a non-blank caller-owned execution fingerprint whenever checkpointing is enabled. In-memory execution without `checkpoint_root` does not require it.
- Changing only this identity creates a distinct run key; the value is also persisted and strictly compatibility-validated. Callers must cover external deterministic round-builder and reducer-context semantics without placing secrets in the fingerprint.
