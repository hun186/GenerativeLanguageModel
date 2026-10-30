#czjLLM/config_ui/interactive_config_loader.py
import os
import pprint
#from utils.utilities_path import is_sqlite_path
from pathlib import Path

from czjLLM.job_manager.job_config import load_sql_config_from_file
from czjLLM.utilities.credential_config import redact_config
from czjLLM.utilities.private_connection_profiles import profile_options, resolve_profile_path
from czjLLM.job_manager.job_config import load_es_config_from_file  # 類似 SQL 的 load_sql_config_from_file

from utils.selector import OptionSelector


def load_sql_config_interactively(PGMSubDir, get_param, ctx):
    sql_config_path = get_param("sql_config_file")
    if sql_config_path:
        sql_config_path = str(resolve_profile_path(sql_config_path, "config_sql"))

    if sql_config_path:
        sql_cfg = load_sql_config_from_file(sql_config_path)
        print(f"✔ 已從設定檔指定 SQL config：{sql_config_path}")
    else:
        config_dir = os.path.join(PGMSubDir, "config_sql")
        os.makedirs(config_dir, exist_ok=True)
        # Git does not store empty ignored directories. Create one on demand.
        os.makedirs(os.path.join(config_dir, "private"), exist_ok=True)
        config_options = profile_options(config_dir)
        if not config_options:
            print("⚠️ 未找到任何 SQL 設定檔，將進入手動輸入模式。")
            sql_cfg = {}
        else:
            selected = OptionSelector(
                options=config_options,
                question="📁 偵測到以下 SQL 設定檔，請選擇："
            ).proc()
            sql_cfg = load_sql_config_from_file(config_options[selected])
            ctx.sql_config_file = config_options[selected]

    print("✔ 載入設定內容如下：")
    pprint.pprint(redact_config(sql_cfg), indent=4, width=100)
    return sql_cfg

def load_es_config_interactively(PGMSubDir, get_param, ctx):
    es_config_path = get_param("es_config_file")
    if es_config_path:
        es_config_path = str(resolve_profile_path(es_config_path, "config_es"))

    if es_config_path:
        es_cfg = load_es_config_from_file(es_config_path)
        print(f"✔ 已從設定檔指定 ES config：{es_config_path}")
    else:
        config_dir = os.path.join(PGMSubDir, "config_es")
        os.makedirs(config_dir, exist_ok=True)
        # Git does not store empty ignored directories. Create one on demand.
        os.makedirs(os.path.join(config_dir, "private"), exist_ok=True)
        config_options = profile_options(config_dir)
        if not config_options:
            print("⚠️ 未找到任何 ES 設定檔，將進入手動輸入模式。")
            es_cfg = {}
        else:
            selected = OptionSelector(
                options=config_options,
                question="📁 偵測到以下 ES 設定檔，請選擇："
            ).proc()
            es_cfg = load_es_config_from_file(config_options[selected])
            ctx.es_config_file = config_options[selected]

    print("✔ 載入設定內容如下：")
    pprint.pprint(redact_config(es_cfg), indent=4, width=100)
    return es_cfg