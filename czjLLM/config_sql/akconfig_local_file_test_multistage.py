# SQLite 多階段測試連線檔

# 服务器信息（本機 sqlite）
server = 'GenerativeLanguageModel/czjLLM/LLMSourcePool/excel_source/DFPreambleCols_df_ALL_Law.sql3'

# 数据库和表信息
table_name = 'sampleSrc'
primary_key = 'index'

target_table = 'sampleSRC_LLM'
# target_table = 'sampleSrc'

# 若要重跑可改 True（會觸發輸出欄位清空流程）
reset_output = False
reset_confirm_code = "12345"
