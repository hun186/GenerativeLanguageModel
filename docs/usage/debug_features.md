# Debug 功能集中說明

本文件集中整理 czjLLM 目前可由 YAML 或環境變數開啟的 debug 功能。Debug 功能主要用於診斷 pipeline、LLM 呼叫、合併與寫回流程；一般正式批次建議保持關閉，避免大量終端輸出影響觀察進度列與效能。

## 快速總覽

| 功能 | YAML key | 環境變數 | 預設 | 主要用途 |
| --- | --- | --- | --- | --- |
| Legacy LLM round debug | `llm_round_debug` | `CZJLLM_LLM_ROUND_DEBUG` | 關閉 | 診斷舊單階段 consumer 的 multiprocessing / Pool / Windows spawn 狀態 |
| Combine step debug | `combine_debug` | `CZJLLM_COMBINE_DEBUG` | 關閉 | 顯示 `combine_api_finished_item()` 合併分片、輸出路徑、清理工作目錄的逐步 checkpoint（`CombBackFN` 一行仍固定保留） |
| Multiprocessing debug | `mp_debug` | `CZJLLM_MP_DEBUG` | 關閉 | 顯示 MP 工具診斷，例如 `[MP-POOL-CREATE]` / `[MP-POOL-JOINED]` 的 pid、平台、start method、job 數、active children 與 stack |
| Stage LLM I/O debug | stage 內 `debug_print_llm_io`、`debug_print_max_chars` | `CZJLLM_DEBUG_PRINT_LLM_IO`、`CZJLLM_DEBUG_PRINT_MAX_CHARS` | 關閉 / 2000 字 | 顯示多階段送入 LLM 的 prompt 與 LLM 回傳內容 |

> 注意：環境變數適合臨時診斷；YAML 適合把某次任務的 debug 設定和任務設定一起保存。若同時設定，對應功能通常以環境變數作臨時覆寫。

## Legacy LLM round debug

### 用途

`llm_round_debug` 用於舊版單階段 consumer 的 round-level 診斷。啟用後會輸出 `[round-debug]` 區塊，包含平台、process/thread、multiprocessing start method、active children、`n_process`、job sample 與例外資訊。

此功能適合排查：

- Windows `spawn` / `DuplicateHandle` / `EOFError`。
- multiprocessing Pool 建立或 join 時機。
- legacy single-stage round 是否進入 Windows spawn-overlap fallback。

### YAML 範例

```yaml
llm_round_debug: true
```

### 環境變數範例

```bash
CZJLLM_LLM_ROUND_DEBUG=1 python -m czjLLM.czjLLM_TextProcessing --config czjLLM/yaml/es_config_fishing.yaml
```

### 注意事項

- 只影響診斷輸出，不改變 prompt、LLM 回傳、合併結果或寫回格式。
- 一般多階段 scheduler path 不一定會走 legacy `run_round()`，因此不一定會看到 `[round-debug]`。
- 大批次開啟會增加終端輸出，建議只在重現問題時使用。

## Combine step debug

### 用途

`combine_debug` 控制 `combine_api_finished_item()` 的 verbose checkpoint。啟用後會輸出 `[combine-step]`，包含：

- 進入合併函式的位置、process/thread 與 item 路徑。
- Success 分片掃描、讀取、OpenCC 轉換、JSON parse 狀態。
- 分片合併、輸出根目錄與輸出檔名解析。
- atomic write 與工作目錄清理 checkpoint。
- 最終 `CombBackFN` 輸出路徑仍固定保留；此行只有一行，方便 row merger / operator 快速定位合併產物。

### YAML 範例

```yaml
combine_debug: true
```

### 環境變數範例

```bash
CZJLLM_COMBINE_DEBUG=1 python -m czjLLM.czjLLM_TextProcessing --config czjLLM/yaml/sqlite_json_multistage_config.yaml
```

### 注意事項

- 預設關閉，避免 `[combine-step]` 洗版並干擾進度列。
- 此開關只控制 `[combine-step]` checkpoint；`CombBackFN` 單行診斷、JSON 解析失敗、修復失敗、工作目錄無法刪除等重要訊息仍會照常輸出。
- `combine_debug` 不等同於既有 `ctx.debug`。既有 `debug=True` 在部分流程會保留工作目錄避免 row merger 接手前被刪除；`combine_debug` 只控制是否列印 verbose 訊息。
- 環境變數 `CZJLLM_COMBINE_DEBUG` 可臨時覆寫 YAML，接受 `1/true/yes/on/debug` 等 truthy 值。

## Multiprocessing debug

### 用途

`mp_debug` 統一控制 `utils.MP_utils.multicoreJob.run()` 的 MP 工具診斷訊息，例如 `[MP-POOL-CREATE]` 與 `[MP-POOL-JOINED]`。這些訊息原本會固定輸出；現在預設關閉，避免正式批次洗版。

啟用後會輸出：

- 目前 process id、parent process id 與 thread name。
- 作業系統平台與 multiprocessing start method。
- 本輪 `nProcess`、job 數與 active child process 數量。
- 觸發 `multicoreJob.run()` 的 stack trace。

### YAML 範例

```yaml
mp_debug: true
```

### 環境變數範例

```bash
CZJLLM_MP_DEBUG=1 python -m czjLLM.czjLLM_TextProcessing --config czjLLM/yaml/txt_config.yaml
```

### 注意事項

- 此開關只控制 MP 工具診斷輸出，不改變平行化策略、prompt、LLM 回覆、合併結果或寫回格式。
- YAML 頂層 `mp_debug: true` 會由 `czjLLM_TextProcessing` 載入到 `ctx`，並傳給 legacy LLM API 呼叫路徑的 `multicoreJob`。
- 環境變數 `CZJLLM_MP_DEBUG` 可臨時覆寫 YAML，接受 `1/true/yes/y/on/debug` 等 truthy 值。

## Stage LLM I/O debug

### 用途

多階段 stage 可用 `debug_print_llm_io` 印出該 stage 實際送往 LLM 的 prompt，以及 LLM 回傳內容；`debug_print_max_chars` 控制每段最多輸出字元。

### YAML 範例

```yaml
stages:
  - name: extract_events
    task_key: InfoExtraction-MultiDim-SQLFriendly-to json format
    debug_print_llm_io: true
    debug_print_max_chars: 2000
```

`debug_print_max_chars` 設為 `0` 或負數代表不截斷：

```yaml
debug_print_llm_io: true
debug_print_max_chars: -1
```

### 環境變數範例

```bash
CZJLLM_DEBUG_PRINT_LLM_IO=1 CZJLLM_DEBUG_PRINT_MAX_CHARS=4000 \
python -m czjLLM.czjLLM_TextProcessing --config czjLLM/yaml/excel_json_multistage_config_with_score_route.yaml
```

### 注意事項

- 可能輸出大量原文、prompt 與模型回覆；請勿在共享 log 中暴露敏感資料。
- 開啟完整輸出（`debug_print_max_chars: -1`）時，長文件或大量 row/doc 會讓終端與 log 快速膨脹。
- 此功能只用於觀察 prompt 組裝與回覆內容，不應用來替代正式輸出檔驗證。

## Windows GUI：LLM Token / Context Distribution

SQL / Table / ES 執行時的 Windows GUI 會顯示一個預設收合的 **LLM Token / Context Distribution** 區塊。這不是 debug 開關，不需要額外 YAML 設定；它直接讀取本次 run 的 `logs/llm_call_audit/llm_call_audit_<run_id>.csv`。

展開後會顯示五組分布曲線與 `n / P50 / P95 / max`；Template 改為標題列中的 compact `P50/P95` 摘要，不再單獨畫分布曲線：

- **Input**：LLM API 回報的 input/prompt tokens。
- **Output**：LLM API 回報的 completion/output tokens。
- **Template**：本地 tokenizer 估算的「rendered prompt − task text」模板／提示詞 overhead。由於同一 YAML stage 通常固定或近固定，GUI 僅在標題摘要顯示 Template P50/P95；multi-stage 或動態模板仍可能出現差異。由於同一 YAML stage 通常固定或近固定，GUI 僅在標題摘要顯示 Template P50/P95；multi-stage 或動態模板仍可能出現差異。
- **Task text**：不含模板的任務文本切片 token 數，本地 tokenizer 計數。
- **Context %**：既有 `context_usage_ratio`，以 API total tokens 相對已解析 context limit 計算。
- **Slice time（切片耗時）**：有實際 `prompt_file` 的切片 LLM request `elapsed_seconds`；從真正送出 API 呼叫到取得模型回應。它不包含等待 worker/queue、response 後處理、merge/reduction 或輸出寫檔時間，也不混入 JSON repair 等沒有切片 prompt 檔的 direct call。

注意：

- Input / Output / Context 只採用 `token_usage_source=llm_api_usage` 的資料；API 未回報 usage 的失敗呼叫不會被當成 0-token 樣本。
- Template / Task text 是觀測用本地 tokenizer 估算，不等於計費 token，也不取代 API usage。
- 若某些 direct/retry 路徑沒有 prompt-component metadata，欄位保持未知；收合摘要會顯示 `Components n/Calls` 讓使用者知道覆蓋率。
- GUI 的背景 audit reader 每秒最多檢查一次 CSV 是否有更新；整檔解析與 percentile/histogram 計算不在 Tk event loop 執行，Tk 只接收已完成的統計 snapshot。LLM worker 仍不傳遞 prompt/output 內容給 GUI。
- 標題列有 `ⓘ` 提示；滑鼠停在標題可看整體分布圖說明，移到任一小圖會顯示該指標的浮動說明。曲線是 histogram 的平滑輪廓，不是時間序列：橫向代表指標值由低到高、縱向代表各區間樣本數；各小圖的高度以自身峰值正規化，不能跨圖比較線高。樣本數很少時應優先解讀 P50/P95/max，而不是曲線尖峰。
- 收合摘要可快速看 Context P50/P95、Input/Output P50、Template P50/P95 與 Slice time P50/P95；若 Context P95 長期逼近 100%，應重新檢視模型 context limit、輸入切片上限與 output budget；若 Slice time P95 明顯高於 P50，則代表模型/API 回應存在長尾，可再交叉比對 input/context 分布。

## 建議排查流程

1. 若懷疑 Windows legacy single-stage Pool / worker 問題：先開 `llm_round_debug: true`。
2. 若需要追查 `multicoreJob.run()` Pool create/join 當下的 process / stack 狀態：開 `mp_debug: true`。
3. 若 LLM 已成功回傳但合併路徑、分片讀取或輸出檔名異常：開 `combine_debug: true`。
4. 若懷疑 stage prompt 組裝、input binding 或模型回覆內容不如預期：只在目標 stage 開 `debug_print_llm_io: true`，並設定合理的 `debug_print_max_chars`。
5. 問題確認後請關閉 debug，避免正式長批次洗版。
