from pathlib import Path

from czjLLM.utilities.path_utils import init_project_root
project_root = init_project_root()
from PackageImport import set_working_dir_to, PackageImporter
PackageImporter.proc()
PGMSubDir = Path(set_working_dir_to("TopicClassification"))

##########################################################################
import pprint

from utils.selector import OptionSelector

from job_manager.job_config import initialize_config
from job_manager.job_config import load_config_from_file
from cli_tools.cli_utils import parse_args

from handlers.handle_txt_file import handle_txt_mode
#from sql_mode.entry.handle_tabular import handle_tabular_mode
from handlers.handle_data_mode import handle_data_mode
from handlers.handle_sql_to_excel import handle_sql_to_excel_mode
    
if __name__ == '__main__':
    args = parse_args()
    file_config = {}

    # 嘗試讀取設定檔
    if args.config:
        file_config = load_config_from_file(PGMSubDir=PGMSubDir, config_path=args.config)
        if file_config:
            #print(f"載入設定檔 :\n{file_config}")
            print("載入設定檔 :")
            pprint.pprint(file_config, indent=4, width=100)

    def get_param(key, default=None):
        return file_config.get(key, default)

    # 模式選擇
    mode = get_param("mode")
    if not mode:
        mode = OptionSelector(
            options={"txt": "處理 llm_source_dir 下所有 .txt 檔",
                     "table": "讀取 Excel/CSV 並對某欄進行分析",
                     "sql": "逐筆處理遠端 SQL 資料庫並即時更新",
                     "sql_to_excel": "將 SQL 資料表內容匯出為 Excel"},
            question="請選擇處理模式：",
            default="txt"
        ).proc()

    # 初始化任務參數
    ctx = initialize_config(
        PGMSubDir=PGMSubDir,
        mode=mode,
        channel=get_param("channel"),
        model_spec_name=get_param("model_spec"),
        task_name=get_param("task")
    )
    # txt 模式：處理所有 .txt
    if mode == "txt":
        handle_txt_mode(ctx, args)

    # 表格模式 / Tabular 模式
    elif mode in ["table","sql"]:
        #handle_tabular_mode(ctx=ctx, get_param=get_param, args=args)
        handle_data_mode(ctx=ctx, get_param=get_param, args=args)
        
    elif mode == "sql_to_excel":
        handle_sql_to_excel_mode(ctx=ctx, get_param=get_param,table_sector = args.config is None)

    else:
        print(f"不支援的mode:{mode}")
        
        
