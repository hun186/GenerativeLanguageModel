#akconfig_es_test.py
# Elasticsearch 設定
#es_host = 'http://localhost:9200'
#es_host = 'http://192.168.0.228:9200'
es_host = 'https://192.168.0.133:9001'
es_index = 'nav_intel_sentences_synthetic_v1'
es_user = 'SRA'
es_pass = 'AAEAAWVsYXN0aWMv'

# ✅ 推薦：CA 憑證（ES 8/9 預設的 http_ca.crt）
es_ca_certs = 'czjLLM/es_mode/certs/http_ca.crt'

# ✅ 進階（可選）
es_verify_certs = True          # 預設 True
es_ssl_assert_hostname = False  # 用 IP 常會需要 False

# 可選欄位
#id_col = '_source.uuid'
#id_col = 'uuid'
id_col = '_id'
input_col = 'rawInfo.content'
output_col = 'multidim_event_json'

reset_output = False          # True 或 False，控制是否重設欄位，如果無此項設定，會進行互動詢問。
reset_confirm_code = "12345"  # 自動跳過驗證碼用，建議搭配 reset_output= True 一起使用
es_apply_mapping = True
mapping_file = "czjLLM/config_es/schemas/InfoExtraction-MultiDim-mapping.yaml"

# 只挑選 selectedMessage==true
only_selected = False

# （可選）更多條件，使用原生 ES DSL 子句
# 會與 only_selected 以 AND 併入 bool.filter
pending_filters = [
    # 例：高價值
    # {"term": {"ai.classLabels.highValue": True}},
    # 例：語言 zh（注意用 .keyword）
    # {"term": {"rawInfo.langCode.keyword": "zh"}},
    # 例：日期區間
    # {"range": {"importDT": {"gte": "2025-10-01T00:00:00Z"}}},
    # 例：nested 欄位（multidim_event_json.Event.location = 台北）
    # {
    #   "nested": {
    #     "path": "multidim_event_json.Event",
    #     "query": { "term": { "multidim_event_json.Event.location": "台北" } }
    #   }
    # },
]

#pending_filters = [
#    {"ids": {"values": ["894349c7b5e001a2b153fdd35c64ed97e7df97df"]}}
#]

#es_request_timeout = 60          # 每次 ES 請求最大等待秒數（scan/mget/get）
#es_scroll_keepalive = "2m"       # scroll 的 keepalive
#es_max_retries = 3               # timeout/瞬斷時重試次數
#es_retry_on_timeout = True       # 逾時自動重試

es_prefetch_buffer = 0              # 預設關閉；LLM-heavy/多程序協作較穩定，必要時可設 5~50 試用
es_prefetch_first_timeout = 8      # 首批最大等待秒數


rerun = {
    "enable": True,                       # 關閉就完全不影響現有流程
    #"model_tag": "gpt-oss:20b",  # 本輪使用的模型/管線標記
    #"meta_field": "multidim_event_json_meta",  # 建議：文件層級的結果中繼欄位（見下）
    "force_since": "2025-11-01T00:00:00Z",     # 可選：重跑 update_time_ai < 此時間的文件
    #"stale_after_days": 90,               # 可選：結果逾期視為需要重跑
    "force_if_missing_meta": True,        # 有 output，但 meta 遺失 → 也當需重跑
    "pipeline_hash": "v3.2.1",            # 可選：管線版本比對（不同即需重跑）
    "fallback_date_field": "update_time_ai",
}
