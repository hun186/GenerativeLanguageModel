# 長文章切片尾段的 GPU 併行派工

ES 多階段流程有兩個不同的併行層級：

1. `multistage_row_parallelism` / `stream_multistage_row_parallelism`：同時處理幾份 doc。
2. `multistage_slice_parallelism`：當某份 doc 被切成很多 prompt slice 時，同時派送幾個 slice。

這兩個值必須分開。前者只能避免 doc 之間完全序列化；批次尾端只剩一份超長 doc 時，真正決定 GPU 利用率的是後者。

## 預設自動設定

不需要在每份 ES YAML 新增並行參數。預設行為是：

1. `ctx.n_process` 優先讀取 model profile 的 `n_process` 或現有 `nProcess`。
2. model profile 未指定時，依現有規則用 endpoint 數量自動計算 `ctx.n_process`。
3. doc-level 與 slice-level 併行度都預設沿用 `ctx.n_process`。

因此現有 model config 中的 `"nProcess": 4` 現在會成為該模型的實際 process/slice budget；沒有這個欄位時才自動估算。

## Model profile 手動介入

只有某個模型的 slice 容量與一般 process budget 不同時，才需在 `model_configs` 中設定 `slice_parallelism`：

```python
32: {
    "nProcess": 4,
    "slice_parallelism": 6,
}
```

建議長期新設定使用 snake_case `n_process`；程式仍支援現有 `nProcess` 以避免破壞 model profile。`slice_parallelism` 只控制單批 prompt slices，不會改變同時進入 pipeline 的 doc 數。

YAML 的 `multistage_row_parallelism` 與 `multistage_slice_parallelism` 仍保留為單次任務 override，但不是日常必填設定。

每批 slice 開始時會輸出：

```text
[llm-dispatch] slice-level parallelism: jobs=37, workers=8
```

若看到 `workers=1`，即使 `model_spec.base_url` 有多個 Ollama endpoint，該批仍只會有一個 slice 呼叫在執行。請確認：

- `model_spec.base_url` 是 endpoint **list**，不是單一字串。
- model profile 的 `nProcess` / `n_process` 或 `slice_parallelism` 大於 1，或本次 YAML 有明確 override。
- 每個 endpoint 實際指向不同 Ollama runtime / GPU，而不是多個 URL 最後代理到同一張卡。
- `logs/base_url_load.human.json` 顯示租約有分散到各 endpoint。

設定優先序為：本次任務/YAML override → model profile `slice_parallelism` → `ctx.n_process`。

## 其他模式

- ES、SQL 與 table/CSV/Excel 的明確多階段 stream 共用 scheduler 與 prompt slice 呼叫路徑，因此都可能有「批次尾端只剩超長單筆」的不均問題，也都可用此設定。
- TXT 與 legacy 單階段流程同樣會把 TODO slice 送到 LLM worker pool；當批次內只剩一篇長文時，也由 slice parallelism 決定能否用滿 endpoint。
- 若某個後續 stage 已將前一階段全部結果合併成單一 prompt，該 stage 本質上只有一個 job，無法靠增加 worker 拆開；需調整 stage 的 `input_from` / 合併時機，或接受該階段的單 job barrier。
