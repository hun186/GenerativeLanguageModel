import json
import pyodbc
import sqlite3
from sql_utils.common import quote_column

def table_exists(cursor, table_name: str, is_sqlite: bool) -> bool:
    if is_sqlite:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,))
        return cursor.fetchone() is not None
    else:
        cursor.execute("""
            SELECT 1 FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_NAME = ?
        """, (table_name,))
        return cursor.fetchone() is not None
    

def ensure_subtable_exists(cursor, subtable: str, key_col: str, input_col: str,
                           seq_col: str, is_sqlite: bool = False):
    if is_sqlite:
        cursor.execute(f"""
            CREATE TABLE IF NOT EXISTS {quote_column(subtable)} (
                {quote_column(key_col)} TEXT,
                {quote_column(seq_col)} INTEGER
            )
        """)
    else:
        # SQL Server 不支援 IF NOT EXISTS CREATE TABLE，建議手動建一次或先檢查再建
        #print("subtable",subtable)
        cursor.execute(f"""
            IF NOT EXISTS (
                SELECT * FROM INFORMATION_SCHEMA.TABLES
                WHERE TABLE_NAME = N'{subtable}'
            )
            BEGIN
                CREATE TABLE {quote_column(subtable)} (
                    {quote_column(key_col)} NVARCHAR(255),
                    {quote_column(seq_col)} INT
                )
            END
        """)

def detect_all_table_names(conn, is_sqlite: bool) -> list:
    cursor = conn.cursor()
    try:
        if is_sqlite:
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
        else:
            cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE = 'BASE TABLE'")
            tables = [row[0] for row in cursor.fetchall()]
    finally:
        cursor.close()
    return sorted(tables)