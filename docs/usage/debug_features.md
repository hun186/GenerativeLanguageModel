# Debug 功能集中說明

本文件集中整理 czjLLM 目前可由 YAML 或環境變數開啟的 debug 功能。Debug 功能主要用於診斷 pipeline、LLM 呼叫、合併與寫回流程；一般正式批次建議保持關閉，避免大量終端輸出影響觀察進度列與效能。

## 快速總覽

| 功能 | YAML key | 環境變數 | 預設 | 主要用途 |
| --- | --- | --- | --- | --- |
| Legacy LLM round debug | `llm_round_debug` | `CZJLLM_LLM_ROUND_DEBUG` | 關閉 | 診斷舊單階段 consumer 的 multiprocessing / Pool / Windows spawn 狀態 |
| Combine step debug | `combine_debug` | `CZJLLM_COMBINE_DEBUG` | 關閉 | 顯示 `combine_api_finished_item()` 合併分片、輸出路徑、清理工作目錄的逐步 checkpoint（`CombBackFN` 一行仍固定保留） |
| Multiprocessing Pool create debug | `mp_pool_create_debug` | `CZJLLM_MP_POOL_CREATE_DEBUG` | 關閉 | 顯示 `[MP-POOL-CREATE]` Pool 建立診斷，包含 pid、平台、start method、job 數、active children 與 stack |
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

## Multiprocessing Pool create debug

### 用途

`mp_pool_create_debug` 控制 `utils.MP_utils.multicoreJob.run()` 在建立或執行 multiprocessing job 前是否列印 `[MP-POOL-CREATE]` 診斷區塊。此訊息原本會固定輸出；現在預設關閉，避免正式批次洗版。

啟用後會輸出：

- 目前 process id、parent process id 與 thread name。
- 作業系統平台與 multiprocessing start method。
- 本輪 `nProcess`、job 數與 active child process 數量。
- 觸發 `multicoreJob.run()` 的 stack trace。

### YAML 範例

```yaml
mp_pool_create_debug: true
```

### 環境變數範例

```bash
CZJLLM_MP_POOL_CREATE_DEBUG=1 python -m czjLLM.czjLLM_TextProcessing --config czjLLM/yaml/txt_config.yaml
```

### 注意事項

- 此開關只控制 `[MP-POOL-CREATE]` 診斷輸出，不改變平行化策略、prompt、LLM 回覆、合併結果或寫回格式。
- YAML 頂層 `mp_pool_create_debug: true` 會由 `czjLLM_TextProcessing` 載入到 `ctx`，並傳給 legacy LLM API 呼叫路徑的 `multicoreJob`。
- 環境變數 `CZJLLM_MP_POOL_CREATE_DEBUG` 可臨時覆寫 YAML，接受 `1/true/yes/y/on/debug` 等 truthy 值。

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

## 建議排查流程

1. 若懷疑 Windows legacy single-stage Pool / worker 問題：先開 `llm_round_debug: true`。
2. 若需要追查 `multicoreJob.run()` Pool 建立當下的 process / stack 狀態：開 `mp_pool_create_debug: true`。
3. 若 LLM 已成功回傳但合併路徑、分片讀取或輸出檔名異常：開 `combine_debug: true`。
4. 若懷疑 stage prompt 組裝、input binding 或模型回覆內容不如預期：只在目標 stage 開 `debug_print_llm_io: true`，並設定合理的 `debug_print_max_chars`。
5. 問題確認後請關閉 debug，避免正式長批次洗版。
