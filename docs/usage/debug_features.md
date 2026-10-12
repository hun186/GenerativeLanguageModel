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

SQL / Table / ES 執行時，Windows GUI 會提供預設收合的 LLM Token / Context Distribution 區塊，讀取本次 run 的 `logs/llm_call_audit/llm_call_audit_<run_id>.csv`。背景 reader thread 解析 append-only CSV，Tk UI 僅接收計算完成的統計；不傳遞 prompt 或模型輸出內容。

展開為 **上排 3 張、下排 4 張**分布圖，各圖顯示 `n / P50 / P95 / max`。x 軸選取 `min / P50 / P95 / max` 等重要數值，會去重並避免碰撞，窄視窗不保證四個標籤全部呈現。所有 token/throughput 類數值完整顯示千分位，不使用 k/M 縮寫；百分比保留 `%`，時間保留 `s`。Template 僅放標題 compact P50/P95：

- 上排：**Input**（API input tokens）、**Output**（API completion tokens）、**Slice time**（真正送出切片 API request 到 response 的 elapsed_seconds）。
- 下排：**Task text**（本地 tokenizer 任務本文）、**Context %**（API total tokens/context limit）、**Total tok/s**、**Effective tok/s (est.)**。
- **Total tok/s** = `(API input_tokens + API output_tokens) / elapsed_seconds`，只納入 prompt_file 存在、API usage 已知且 elapsed > 0 的切片。既有 `processing_tps` 的來源是 API `total_tokens / elapsed_seconds`，零秒時有不同 fallback，因此保留舊欄位契約，GUI 依新明確公式計算。
- **Effective tok/s (est.)**：若 provider usage 明確回報 `prompt_cache_hit_tokens`、`prompt_tokens_details.cached_tokens` 或 `input_tokens_details.cached_tokens`，用 `(input - cached + output) / elapsed`，包含 provider 明確回報 0 cached 的情況。CSV 記錄 `cached_input_tokens` 及 `cached_input_token_source=provider_usage`；無回報則保持空白，不把猜測偽裝成真值。
- 無 provider cache truth 時，採保守 heuristic v1：需同一 `model / endpoint / task / stage_identity / local tokenizer source` 分組已有至少兩筆先前模板樣本、模板 token floor 與幅度在 5% 容差內，才以模板下界的最多 **50%** 估計可重用 token。使用 `(task_text_tokens + max(0, template_tokens - estimated_reusable) + output_tokens) / elapsed`。此值沒有 provider cache-hit 證據，不確保 prefix 完全相同、token boundary 對齊、provider 實際啟用 cache，也未偵測動態 runtime suffix；如證據不足便保持 unknown，不推測。
- 首兩筆同群組呼叫未必能形成 heuristic；本地 task/template 數字與 API usage 來源不同，估值不是確切的硬體效能量測，亦非直接可比較的 GPU token/s。兩種 throughput 都是 **observed request-level throughput**，elapsed 包含網路往返、server 排程、TTFT 和生成時間。

**資料與安全契約**：數值 sidecar 位於 TODO/RUNNING 外側；新增 `stage_identity` 是單階段固定代碼或 YAML stage 名稱，絕不以原始 task prompt/payload 做身份值。GUI 不讀取 prompt 文件或輸出內容；與 API usage 不符、elapsed 無效、provider cached 欄位缺失或不合法時，禁止宣稱 cache-hit 真值。

**閱讀方式**：分布圖不是時間序列。橫向為指標由小到大，縱向為樣本落入區間的數目，每張圖的峰值獨立正規化，不能比較不同圖的曲線高度。若樣本很少，優先看 P50/P95/max，不要過度解讀尖峰。標題 `ⓘ`、各小圖提供浮動說明；既有多螢幕 tooltip 位置校正與 resize redraw 保留。

## 建議排查流程

1. 若懷疑 Windows legacy single-stage Pool / worker 問題：先開 `llm_round_debug: true`。
2. 若需要追查 `multicoreJob.run()` Pool create/join 當下的 process / stack 狀態：開 `mp_debug: true`。
3. 若 LLM 已成功回傳但合併路徑、分片讀取或輸出檔名異常：開 `combine_debug: true`。
4. 若懷疑 stage prompt 組裝、input binding 或模型回覆內容不如預期：只在目標 stage 開 `debug_print_llm_io: true`，並設定合理的 `debug_print_max_chars`。
5. 問題確認後請關閉 debug，避免正式長批次洗版。
