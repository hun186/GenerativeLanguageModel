import os
import pprint
#from utils.utilities_path import is_sqlite_path
from pathlib import Path

from czjLLM.job_manager.job_config import load_sql_config_from_file
from utils.selector import OptionSelector

def load_sql_config_interactively(PGMSubDir, get_param, ctx):
    sql_config_path = get_param("sql_config_file")
    if sql_config_path:
        sql_config_path = str(Path(sql_config_path))

    if sql_config_path:
        sql_cfg = load_sql_config_from_file(sql_config_path)
        print(f"✔ 已從設定檔指定 SQL config：{sql_config_path}")
    else:
        config_dir = os.path.join(PGMSubDir, "config_sql")
        os.makedirs(config_dir, exist_ok=True)
        config_files = [f for f in os.listdir(config_dir) if f.endswith((".py", ".yaml", ".yml"))]
        if not config_files:
            print("⚠️ 未找到任何 SQL 設定檔，將進入手動輸入模式。")
            sql_cfg = {}
        else:
            config_options = {f: os.path.join(config_dir, f) for f in config_files}
            selected = OptionSelector(
                options=config_options,
                question="📁 偵測到以下 SQL 設定檔，請選擇："
            ).proc()
            sql_cfg = load_sql_config_from_file(config_options[selected])
            ctx.sql_config_file = config_options[selected]

    print("✔ 載入設定內容如下：")
    pprint.pprint(sql_cfg, indent=4, width=100)
    return sql_cfg
