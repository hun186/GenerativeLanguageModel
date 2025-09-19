import os
import pandas as pd
from datetime import datetime
def export_sql_to_excel(ctx, is_sqlite=False):
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

    conn.close()
