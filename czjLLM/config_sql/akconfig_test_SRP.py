import os

# czjLLM/config_sql/akconfig_test_SRP.py

# 服务器信息
server = '192.168.0.136'
username = 'aiapp'
password = os.environ.get("CZJLLM_SQL_SRP_PASSWORD")
# 数据库和表信息
database_name = 'AIDB'
table_name = 'vessel_activities'
primary_key = 'hash_value'

target_table = 'vessel_activities_LLM_result'

reset_output = False          # True 或 False，控制是否重設欄位，如果無此項設定，會進行互動詢問。
reset_confirm_code = "12345"  # 自動跳過驗證碼用，建議搭配 reset_output= True 一起使用