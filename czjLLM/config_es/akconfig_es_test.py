#akconfig_es_test.py
# Elasticsearch 設定
es_host = 'http://localhost:9200'
es_index = 'news_test'
es_user = ''
es_pass = ''

# 可選欄位
#id_col = '_source.uuid'
id_col = 'uuid'
input_col = 'rawInfo.content'
output_col = 'multidim_event_json'

reset_output = True          # True 或 False，控制是否重設欄位，如果無此項設定，會進行互動詢問。
reset_confirm_code = "12345"  # 自動跳過驗證碼用，建議搭配 reset_output= True 一起使用
es_apply_mapping = True
mapping_file = "czjLLM/config_es/schemas/InfoExtraction-MultiDim-mapping.yaml"