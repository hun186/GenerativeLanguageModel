import os
import pandas as pd
from datetime import datetime
import re

def sanitize_sheet_name(name):
    # 移除非法字元
    name = re.sub(r'[\\/*?:\[\]]', '', name)
    # 截斷為最多 31 字元（Excel 限制）
    return name[:31]

def export_sql_to_excel(ctx, is_sqlite=False, selected_tables: list = None, separate_excel: bool = False):
    print("📤 開始從 SQL 資料庫匯出成 Excel...")

    if is_sqlite:
        import sqlite3
        conn = sqlite3.connect(ctx.sqlite_path)
    else:
        import pyodbc
        conn = pyodbc.connect(ctx.sql_connection_string)

    export_dir = os.path.join(ctx.PGMSubDir, "exported_excel")
    os.makedirs(export_dir, exist_ok=True)

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    exported = set()

    if separate_excel:
        # 每個表格存一個 Excel
        for table in selected_tables:
            try:
                query = f"SELECT * FROM {table}"
                df = pd.read_sql(query, conn)
                excel_path = os.path.join(export_dir, f"{table}_export_{timestamp}.xlsx")
                df.to_excel(excel_path, index=False)
                print(f"✅ 已匯出資料表 {table} 到檔案：{excel_path}")
                exported.add(table.lower())
            except Exception as e:
                print(f"⚠️ 匯出 {table} 時發生錯誤：{e}")
    else:
        # 合併成單一 Excel，多工作表
        combined_excel_path = os.path.join(export_dir, f"SQL_export_combined_{timestamp}.xlsx")
        failed_tables = []
        
        with pd.ExcelWriter(combined_excel_path, engine='openpyxl') as writer:
            for table in selected_tables:
                try:
                    query = f"SELECT * FROM {table}"
                    df = pd.read_sql(query, conn)
                    sheet_name = sanitize_sheet_name(table)
                    df.to_excel(writer, sheet_name=sheet_name, index=False)
                    print(f"✅ 已加入資料表 {table} 至工作表")
                    exported.add(table.lower())
                except Exception as e:
                    print(f"⚠️ 匯出 {table} 至合併 Excel 失敗：{e}")
                    failed_tables.append(table)
        
        if failed_tables:
            print("📤 以下表格將改為個別儲存：", failed_tables)
            for table in failed_tables:
                try:
                    query = f"SELECT * FROM {table}"
                    df = pd.read_sql(query, conn)
                    excel_path = os.path.join(export_dir, f"{table}_export_{timestamp}.xlsx")
                    df.to_excel(excel_path, index=False)
                    print(f"✅ 已改為分開匯出資料表 {table} 到：{excel_path}")
                    exported.add(table.lower())
                except Exception as e:
                    print(f"❌ 無法匯出 {table}（即使改用分存）：{e}")
        print(f"📦 多表合併匯出完成：{combined_excel_path}")

    conn.close()



def export_sql_to_excel_old(ctx, is_sqlite=False, selected_tables: list = None, auto_export_flattened: bool = True):
    print("📤 開始從 SQL 資料庫匯出成 Excel...")

    if is_sqlite:
        import sqlite3
        conn = sqlite3.connect(ctx.sqlite_path)
    else:
        import pyodbc
        conn = pyodbc.connect(ctx.sql_connection_string)

    def export_table(table_name):
        try:
            query = f"SELECT * FROM {table_name}"
            df = pd.read_sql(query, conn)
            export_dir = os.path.join(ctx.PGMSubDir, "exported_excel")
            os.makedirs(export_dir, exist_ok=True)
    
            excel_path = os.path.join(
                export_dir,
                f"{table_name}_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            )
            df.to_excel(excel_path, index=False)
            print(f"✅ 已匯出資料表 {table_name}：{excel_path}")
        except Exception as e:
            print(f"⚠️ 匯出 {table_name} 時發生錯誤：{e}")

    exported = set()

    for table in selected_tables:
        export_table(table)
        exported.add(table.lower())
    conn.close()
    
def export_sql_to_excel_old(ctx, is_sqlite=False):
    print("📤 開始從 SQL 資料庫匯出成 Excel...")

    if is_sqlite:
        import sqlite3
        conn = sqlite3.connect(ctx.sqlite_path)
    else:
        import pyodbc
        conn = pyodbc.connect(ctx.sql_connection_string)

    def export_table(table_name):
        try:
            query = f"SELECT * FROM {table_name}"
            df = pd.read_sql(query, conn)
            excel_path = os.path.join(
                ctx.PGMSubDir,
                f"{table_name}_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            )
            df.to_excel(excel_path, index=False)
            print(f"✅ 已匯出資料表 {table_name}：{excel_path}")
        except Exception as e:
            print(f"⚠️ 匯出 {table_name} 時發生錯誤：{e}")

    # 匯出來源表
    export_table(ctx.sql_table)

    # 若目標表不同，則也一併匯出
    if ctx.target_table.strip().lower() != ctx.sql_table.strip().lower():
        export_table(ctx.target_table)

    # 匯出 flattened 子表（若有）
    if hasattr(ctx, "output_col") and ctx.output_col:
        flattened_name = f"{ctx.target_table}_{ctx.output_col}_flattened"
        try:
            # 嘗試先查詢資料確認子表是否存在
            cursor = conn.cursor()
            if is_sqlite:
                cursor.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (flattened_name,)
                )
            else:
                cursor.execute(
                    "SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?",
                    (flattened_name,)
                )
            exists = cursor.fetchone() is not None
            cursor.close()

            if exists:
                export_table(flattened_name)
            else:
                print(f"📁 子表 {flattened_name} 不存在，略過匯出")
        except Exception as e:
            print(f"⚠️ 檢查 flattened 子表時發生錯誤：{e}")

    conn.close()
