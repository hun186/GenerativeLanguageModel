import pyodbc
import sqlite3
from datetime import datetime
from colorama import Fore, Style#, Back

from czjLLM.sql_utils.common import quote_column
from czjLLM.sql_utils.schema_manager import table_exists

def get_existing_columns(cursor, table_name: str, is_sqlite: bool) -> list[str]:
    if is_sqlite:
        cursor.execute(f"PRAGMA table_info({quote_column(table_name)})")
        return [row[1] for row in cursor.fetchall()]
    else:
        cursor.execute(f"SELECT TOP 1 * FROM {quote_column(table_name)}")
        return [desc[0] for desc in cursor.description]
    
def ensure_sql_columns_exist(cursor, table_name: str, new_fields: list[str], is_sqlite: bool = False):
    """
    檢查資料表是否已有指定欄位，若無則新增
    """
    if is_sqlite:
        cursor.execute(f"PRAGMA table_info({quote_column(table_name)})")        
        existing_cols = [row[1] for row in cursor.fetchall()]
    else:
        cursor.execute(f"SELECT TOP 1 * FROM {quote_column(table_name)}")
        existing_cols = [desc[0] for desc in cursor.description]

    for col in new_fields:
        if col not in existing_cols:
            print(f"⚠️ 欄位 {col} 不存在，將自動新增")
            alter_sql = (
                f"ALTER TABLE {quote_column(table_name)} ADD COLUMN {quote_column(col)} TEXT"
                if is_sqlite else
                f"ALTER TABLE {quote_column(table_name)} ADD {quote_column(col)} NVARCHAR(MAX)"
            )
            cursor.execute(alter_sql)
            print(f"✅ 成功新增欄位：{col}")
            
def reset_output_col_with_backup(ctx, is_sqlite):  
    # 建立資料庫連線
    conn = sqlite3.connect(ctx.sqlite_path) if is_sqlite else pyodbc.connect(ctx.sql_connection_string)
    cursor = conn.cursor()

    # 🔍 檢查主表是否存在
    if not table_exists(cursor, ctx.target_table, is_sqlite):
        print(f"⚠️ 主表 {ctx.target_table} 不存在，跳過備份與清空作業")
        cursor.close()
        conn.close()
        return

    # 檢查主表是否包含輸出欄位
    if not ctx.output_col in get_existing_columns(cursor, ctx.target_table, is_sqlite):
        print(f"⚠️ 欄位 {ctx.output_col} 不存在於主表 {ctx.target_table}，跳過備份與清空作業")
        cursor.close()
        conn.close()
        return
    
    # 產生唯一備份表名稱（含時間戳）
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_table = f"{ctx.sql_table}_{ctx.output_col}_backup_{timestamp}"
    timestamp_col = "backup_time"

    print(f"📦 正在備份至資料庫表格：{backup_table}")

    # 建立備份表
    if is_sqlite:
        create_sql = (
            f"CREATE TABLE {quote_column(backup_table)} ("
            f"{quote_column(ctx.primary_key)} TEXT, "
            f"{quote_column(ctx.output_col)} TEXT, "
            f"{timestamp_col} DATETIME)"
        )
    else:
        create_sql = (
            f"CREATE TABLE {quote_column(backup_table)} ("
            f"{quote_column(ctx.primary_key)} NVARCHAR(255), "
            f"{quote_column(ctx.output_col)} NVARCHAR(MAX), "
            f"{timestamp_col} DATETIME)"
        )
    cursor.execute(create_sql)
    conn.commit()
    ensure_sql_columns_exist(cursor, backup_table, [ctx.output_col], is_sqlite)
    # 將原始值寫入備份表
    insert_sql = (
        f"INSERT INTO {quote_column(backup_table)} "
        f"SELECT {quote_column(ctx.primary_key)}, {quote_column(ctx.output_col)}, CURRENT_TIMESTAMP "
        f"FROM {quote_column(ctx.target_table)}"
    )
    print("insert_sql",insert_sql)
    cursor.execute(insert_sql)
    conn.commit()

    print(f"✅ 備份完成，儲存於表格：{Fore.CYAN}{backup_table}{Style.RESET_ALL}")

    # 清空原欄位
    reset_sql = f"UPDATE {quote_column(ctx.target_table)} SET {quote_column(ctx.output_col)} = NULL"
    cursor.execute(reset_sql)
    conn.commit()

    cursor.close()
    conn.close()

    print(f"✅ 成功清空欄位 {ctx.output_col}，您可透過備份表還原歷史資料")
