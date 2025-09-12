import getpass
import sqlite3
import pyodbc
from ..sql_utils.export_utils import export_sql_to_excel
from ..sql_utils.common import build_sql_connection_string
from ..sql_utils.schema_manager import detect_all_table_names
from ..sql_utils.schema_manager import table_exists
from utils.selector import MultiOptionSelector
from utils.utilities_path import is_sqlite_path
from ..config_ui.interactive_config_loader import load_sql_config_interactively

def handle_sql_to_excel_mode(ctx, get_param, table_sector = True):
    print("📤 SQL 匯出 Excel 模式")
    
    sql_cfg = load_sql_config_interactively(ctx.PGMSubDir, get_param, ctx)
    
    server = sql_cfg.get("server", "").strip()
    
    if is_sqlite_path(server):
        is_sqlite = True
        ctx.sqlite_path = server        
        conn = sqlite3.connect(ctx.sqlite_path)
    else:
        is_sqlite = False
        ctx.sql_connection_string = build_sql_connection_string(sql_cfg)
        conn = pyodbc.connect(ctx.sql_connection_string)

    ctx.sql_table = sql_cfg.get("table_name") or input("📋 請輸入主表名稱：").strip()
    ctx.target_table = sql_cfg.get("target_table", ctx.sql_table)
    ctx.output_col = get_param("output_col")

    # 🔍 自動偵測所有資料表名稱
    all_tables = detect_all_table_names(conn, is_sqlite)

    # ✅ 互動複選
    default_table=[ctx.sql_table, ctx.target_table] if ctx.target_table != ctx.sql_table else [ctx.sql_table]
    if hasattr(ctx, "output_col") and ctx.output_col:
        flattened_table = f"{ctx.target_table}_{ctx.output_col}_flattened"
        if is_sqlite:
            conn = sqlite3.connect(ctx.sqlite_path)
        else:
            conn = pyodbc.connect(ctx.sql_connection_string)
        if table_exists(cursor=conn.cursor(), table_name=flattened_table, is_sqlite=is_sqlite):
            default_table.append(f"{ctx.target_table}_{ctx.output_col}_flattened")      
           
    if table_sector:
        table_selector = MultiOptionSelector(
            options={t: f"匯出資料表：{t}" for t in all_tables},
            question="請選擇要匯出的表格（可多選）",
            default=default_table
        )
        selected_tables = table_selector.proc()
        conn.close()
        # ✅ 加入是否分存詢問
        separate_excel_input = input("是否要將每個資料表分別存為獨立的 Excel 檔案？(y/N)：").strip().lower()
        separate_excel = (separate_excel_input in ["y", "yes"])

    #非互動模式，自動由設定檔決定輸出表格，並且合併儲存到同一個excel檔。
    else:
        selected_tables = default_table
        separate_excel = False

    # 📤 匯出
    export_sql_to_excel(ctx, selected_tables=selected_tables, is_sqlite=is_sqlite, separate_excel=separate_excel)


def handle_sql_to_excel_mode_old(ctx, get_param):
    print("📤 SQL 匯出 Excel 模式")
    
    sql_cfg = load_sql_config_interactively(ctx.PGMSubDir, get_param, ctx)
    
    server = sql_cfg.get("server", "").strip()
    if is_sqlite_path(server):
        ctx.sqlite_path = server
        ctx.sql_table = sql_cfg.get("table_name") or input("📋 請輸入 SQLite 表格名稱：").strip()
        is_sqlite = True
    else:
        username = sql_cfg.get("username") or input("🔐 請輸入使用者名稱：").strip()
        password = sql_cfg.get("password") or getpass.getpass("🔐 請輸入密碼：")
        database_name = sql_cfg.get("database_name") or input("🗂️ 請輸入資料庫名稱：").strip()
        ctx.sql_connection_string = (
            f"DRIVER={{SQL Server}};SERVER={server};"
            f"DATABASE={database_name};UID={username};PWD={password}"
        )
        ctx.sql_table = sql_cfg.get("table_name") or input("📋 請輸入資料表名稱：").strip()
        is_sqlite = False
    ctx.target_table = sql_cfg.get("target_table",ctx.sql_table)
    # 設定 target_table（預設與 sql_table 相同）
    ctx.target_table = sql_cfg.get("target_table", ctx.sql_table)

    # 📋 準備所有候選表格
    all_tables = [ctx.sql_table]
    if ctx.target_table.strip().lower() != ctx.sql_table.strip().lower():
        all_tables.append(ctx.target_table)

    if hasattr(ctx, "output_col") and ctx.output_col:
        flattened_table = f"{ctx.target_table}_{ctx.output_col}_flattened"
        if is_sqlite:
            conn = sqlite3.connect(ctx.sqlite_path)
        else:
            conn = pyodbc.connect(ctx.sql_connection_string)
        if table_exists(cursor=conn, table_name=flattened_table, is_sqlite=is_sqlite):
            all_tables.append(flattened_table)
    #all_tables = detect_all_table_names(conn, is_sqlite)
    # ✅ 互動複選
    table_selector = MultiOptionSelector(
        options={t: f"匯出資料表：{t}" for t in all_tables},
        question="請選擇要匯出的表格（可多選）",
        default=all_tables
    )
    selected_tables = table_selector.proc()

    # 📤 匯出
    export_sql_to_excel(ctx, selected_tables, is_sqlite)