# ES pipeline_hash 重跑機制說明

## `pipeline_hash` 是什麼

在 ES mode 中，`pipeline_hash` 是由操作人員／設定檔提供的 pipeline 版本標記。目前它不會由程式自動根據 Python 程式碼、prompt、stage config 或模型設定計算產生。

常見來源有兩種：

1. 主 YAML 的 `rerun.pipeline_hash`。
2. `es_config_file` Python config 裡的 `rerun["pipeline_hash"]`。

兩邊同時存在時，主 YAML 的值會覆寫 `es_config_file` 的值。

## 為什麼它會影響重跑

ES rerun 啟用時，生效的 `pipeline_hash` 會寫回 ES output meta 欄位，通常是：

```text
<output_col>_meta.pipeline_hash
```

ES pending / fresh 檢查會把「目前生效的 `pipeline_hash`」與「文件既有 output meta 內保存的 `pipeline_hash`」做比對。如果文件已經有 output，但既有 meta hash 與目前 hash 不同，該文件會被視為需要重跑。

這在 pipeline、prompt、輸出契約或 normalization 邏輯變更後，需要重新產生舊結果時很有用。不過如果不小心改到這個值，也可能讓既有文件反覆重新進入 pending，直到它們的 meta 被新 hash 更新為止。

## 安全使用建議

- 同一套 pipeline 的一般重複執行期間，請保持 `pipeline_hash` 穩定。
- 只有在刻意讓舊 output 視為過期時才調整，例如 prompt、stage flow、輸出 schema 或 writeback normalization 有變更。
- 建議使用有意義且可追溯的值，例如 `event-v3.2.2-prompt-20260723`，避免使用容易忘記用途的臨時字串。
- 如果文件一直非預期重跑，請先看啟動時的 rerun 提示，並比對目前生效值與 ES 文件中的 `<output_col>_meta.pipeline_hash`。
- 若要停止 hash-based rerun，可在確認沒有其他 rerun rule 需求後，恢復舊 hash、移除 `pipeline_hash`，或關閉 `rerun.enable`。

## 啟動時提示

ES mode 啟動時會印出生效的 rerun 設定。當偵測到 `pipeline_hash` 時，也會額外提示：

- 生效值的來源；
- 生效值；
- 它會寫回 ES meta，並參與 pending / fresh 檢查；
- 當值與既有 output meta 不一致時，文件會被視為需要重跑的風險。
