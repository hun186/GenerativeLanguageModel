# api contract


---

## 


-

## 2026-08-20 ES model metadata contract

- `<output_col>_meta` 可保存 `model_tag`、`model_name`、`base_url_alias`、`num_ctx`、`temperature`、`model_version` 及既有 pipeline/task tracking fields。
- `base_url_alias` 必須是非敏感 alias，不得以實際 `base_url` 代替。
- `model_spec`、`base_url`、`api_key`、access/auth token、Authorization、password、client secret、private key 等 credential 不得寫入 ES metadata；ES sink 在 writeback boundary 會移除 credential-like keys。
