import os

# akconfig.py

# 服务器信息
server = os.environ.get("CZJLLM_SQL_ORION_SERVER") or (
    "" if os.environ.get("CZJLLM_ENV", "").strip().lower() in {"production", "prod"}
    else "localhost"
)
username = os.environ.get("CZJLLM_SQL_ORION_USERNAME", "")
password = os.environ.get("CZJLLM_SQL_ORION_PASSWORD")
# 数据库和表信息
database_name = 'Orion'
table_name = 'UserAcc'
primary_key = 'Auto'

target_table = 'UserAcc_LLM_result'    # 
#target_table = 'UserAcc'    # 

reset_output = False          # True 或 False，控制是否重設欄位
reset_confirm_code = "12345"  # 自動跳過驗證碼用，建議搭配 reset_output= True 一起使用