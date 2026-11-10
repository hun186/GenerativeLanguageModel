# JSON 結果完整性保護：finish_reason 與既有 rerun 共同規則

## 不建立第二套 rerun 欄位清單

ES 既有 rerun.required_output_checks 是**已合併、已寫回的文件**是否符合必要輸出欄位的條件。
程式支援 path、validator（date / non_empty）、format 和 min_valid_count，
這份 PR 將具體欄位檢查抽成共用的 evaluate_required_output_checks 函式，
由兩種 ES pending policy 共同呼叫，保留原本 retry / pending 決策。
不在每個 JSON 切片上套用整份文件的 Event、Event_Timeline 規則。

特別注意：Event_Timeline 為空可能完全合法。如果仍設定
Event_Timeline.time_iso / min_valid_count: 1，舊有 rerun 就會把這類文件排入 pending，
這是配置規則，不是 JSON 語法問題。可按政策改用 Event.time_iso（如確有時間），
或把 Timeline 的 min_valid_count 設為 0 / 不要求非空。
**這份 PR 不擅自更動用戶既有 YAML 條件。**

## LLM 產生階段：明確截斷證據

LLM audit CSV 新增 finish_reason，僅存 provider 有回報的固定狀態
stop／length／content_filter／tool_calls／function_call／other／空白（未知）。
原本 output_tokens、max_output_tokens、max_tokens 已有記錄，保持不變。
新 CSV 增加一欄；已開始的舊 CSV 沿用其原始欄位數，不破壞 header。

如果 JSON 輸出者明確回報 finish_reason=length，即使得到語法合法 JSON，
也不允許將該次輸出寫入 Success；沿用原本分割後重做的安全路徑。
JSON 修復呼叫本身如果回報 length，也不把它當作可用的修復成功。
當 provider 完全不回報 finish_reason 時，不能憑空推定截斷；
只觀察現有 token/上下文/修復結果指標。

在 JSON 修復成功的品質事件中，前版已保存 lexical diff 的
error_pos_pct 和固定 error_kind，但此百分比不代表事件流失比例。

## 邊界

這是明確 token 截斷情境的保守 Success gate，不代表已建置完整
語意保真檢查。僅從 JSON 長度／字面值重疊度不能證實 Event／
Event_Timeline 是否完整，須在合併後的文件層另行建立證據驗證。
沒有真實本地 GPU 或實體 Windows 工作站的驗收，本版結果不得稱為實機驗證。
