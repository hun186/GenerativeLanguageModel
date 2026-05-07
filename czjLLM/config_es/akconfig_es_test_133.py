#akconfig_es_test.py
# Elasticsearch 設定
#es_host = 'http://localhost:9200'
es_host = 'https://192.168.0.133:9001'
es_index = 'news_test'
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
# 個人篩選（可選）：會與 pending_filters / only_selected 以 AND 合併；
# 下列備註、股名、代號、清單條件彼此採 OR，命中任一個就納入待處理。
# personal_filters = {
#     # 備註關鍵字篩選（可自訂 note_fields 對應實際欄位）
#     # "note_keywords": ["追蹤", "重要"],
#     # "note_fields": ["userNote", "rawInfo.remark"],
#
#     # 股名 / 代號篩選（可自訂欄位；代號會自動嘗試 .keyword 精確比對）
#     # "stock_names": ["台積電", "聯發科"],
#     # "stock_codes": ["2330", "2454"],
#     # "stock_name_fields": ["rawInfo.stockName", "companyName"],
#     # "stock_code_fields": ["rawInfo.stockCode", "ticker"],
#
#     # 清單篩選：簡單清單會用股名+代號欄位 OR 搜尋；也可指定 field/fields/values。
#     # "list_filter": ["2330", "台積電"],
#     # "list_filter": {"field": "rawInfo.stockCode", "values": ["2330", "2454"], "exact": True},
# }

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

es_prefetch_buffer = 1000           # 0 = 關閉預取
es_prefetch_first_timeout = 8      # 首批最大等待秒數

rerun = {
    "enable": True,
    "force_since": "2025-11-01T00:00:00Z",
    "force_if_missing_meta": True,
    "pipeline_hash": "v3.2.1",
    "fallback_date_field": "update_time_ai",

    # ✅ 新增：必要欄位檢查（output存在但缺這些欄位/格式不對，也要重跑）
    "required_output_checks": [
        {
            # 可寫相對 output_col 的路徑（預設 relative_to_output=True）
            "path": "Event_Timeline.date_iso",
    
            # 驗證器：日期格式 yyyy-MM-dd
            "validator": "date",
            "format": "yyyy-MM-dd",
    
            # 至少要找到幾個合法值（預設 1）
            "min_valid_count": 1,
    
            # 預設 True：會自動補成 output_col.path
            "relative_to_output": True
        }
    ]
}