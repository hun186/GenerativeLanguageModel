# akconfig.py

# 服务器信息
server = 'GenerativeLanguageModel/czjLLM/LLMSourcePool/excel_source/DFPreambleCols_df_ALL_Law.sql3'

# 数据库和表信息
table_name = 'sampleSrc'
primary_key = 'index'

target_table = 'sampleSRC_LLM_TR_flattened'
#target_table = 'sampleSrc'

reset_output = False          # True 或 False，控制是否重設欄位
reset_confirm_code = "12345"  # 自動跳過驗證碼用，建議搭配 reset_output= True 一起使用