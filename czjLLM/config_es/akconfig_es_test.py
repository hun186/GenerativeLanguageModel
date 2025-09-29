#akconfig_es_test.py
# Elasticsearch 設定
es_host = 'http://localhost:9200'
es_index = 'news_test'
es_user = ''
es_pass = ''

# 可選欄位
id_col = '_source.uuid'
input_col = 'rawInfo.content'
output_col = 'llm_result'