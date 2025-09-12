import json
import pyodbc
import sqlite3
import pyodbc
from sql_utils.common import quote_column

from sql_utils.common import safe_sql_value
from sql_utils.column_utils import ensure_sql_columns_exist

from typing import List, Dict, Any, Union, Optional

def flatten_row_based_json_array_to_subtable(
    cursor,
    sub_table_name: str,
    pk_value: str,
    json_array: List[Dict[str, Any]],
    key_col: str = "main_key",
    seq_col: str = "seq",
    save_raw_input: bool = False,
    input_col: str = "",
    input_col_value: Optional[str] = None,
    is_sqlite: bool = False,
):
    """
    將 JSON 陣列展平為多列資料並寫入子表。
    
    - conn: 資料庫連線 (sqlite3.Connection 或 pyodbc.Connection)
    - sub_table_name: 子表名稱
    - pk_value: 對應主表的主鍵值
    - json_array: List of dicts (待展平)
    - seq_col: 流水號欄位名稱
    - database_type: "sqlite" 或 "sqlserver"
    """
    delete_sql = f"DELETE FROM {quote_column(sub_table_name)} WHERE {quote_column(key_col)} = ?"
    cursor.execute(delete_sql, (pk_value,))
    
    if not json_array:
        return f"✅ 原主鍵 {pk_value} 無需展平（空陣列）"
    #print("json_array in flatten_row_based_json_array_to_subtable",json_array)
    all_keys = []
    for obj in json_array:
        for k in obj:
            if k not in all_keys:
                all_keys.append(k)
    # 只在需要時建立 input_col 欄位；seq_col 與資料 keys 一定要確保
    cols_to_ensure = [seq_col] + all_keys + ([input_col] if save_raw_input and input_col else [])
    ensure_sql_columns_exist(cursor, sub_table_name, cols_to_ensure, is_sqlite)

    # 準備 INSERT 欄位
    if save_raw_input:
        insert_cols = [key_col, input_col, seq_col] + all_keys
    else:
        insert_cols = [key_col, seq_col] + all_keys
    
    placeholders = ", ".join(["?"] * len(insert_cols))
    #print("placeholders",placeholders)
    #print("sub_table_name",sub_table_name)
    #print("insert_cols",insert_cols)
    insert_sql = (
        f"INSERT INTO {quote_column(sub_table_name)} "
        f"({', '.join(quote_column(c) for c in insert_cols)}) "
        f"VALUES ({placeholders})"
    )

    # 寫入展平資料
    #print("insert_sql",insert_sql)
    for i, obj in enumerate(json_array, 1):
        base_vals = [pk_value, i] if not save_raw_input else [pk_value, input_col_value, i]
        row_vals = base_vals + [safe_sql_value(obj.get(k)) for k in all_keys]
        cursor.execute(insert_sql, row_vals)


    return f"✅ 展平完成：{len(json_array)} 筆已寫入 {sub_table_name}"


def write_flattened_json_to_sql(
    cursor, table_name: str, pk: str, pk_val: str,
    row_dict: dict, is_sqlite: bool = False, is_update_only: bool = False
):
    """
    將展平的 JSON 結果寫入 SQL，支援：
    - SQLite: INSERT OR REPLACE
    - SQL Server: MERGE
    - 主表模式（is_update_only=True）時，只做 UPDATE（避免 IDENTITY_INSERT 錯誤）
    """

    columns = list(row_dict.keys())
    values = [safe_sql_value(row_dict[col]) for col in columns]

    if is_update_only:
        update_expr = ", ".join(f"{quote_column(col)} = ?" for col in columns)
        sql = f"""
            UPDATE {quote_column(table_name)}
            SET {update_expr}
            WHERE {quote_column(pk)} = ?
        """
        cursor.execute(sql, values + [pk_val])
        return

    if is_sqlite:
        col_assignments = ", ".join([f"{quote_column(col)} = ?" for col in columns])
        sql = f"""
            INSERT INTO {quote_column(table_name)} ({quote_column(pk)}, {','.join(map(quote_column, columns))})
            VALUES (?, {','.join(['?'] * len(columns))})
            ON CONFLICT({quote_column(pk)}) DO UPDATE SET {col_assignments}
        """
        cursor.execute(sql, [pk_val] + values + values)
    else:
        set_expr = ", ".join([f"{quote_column(col)} = source.{quote_column(col)}" for col in columns])
        sql = f"""
            MERGE {quote_column(table_name)} AS target
            USING (SELECT ? AS {quote_column(pk)}, {','.join(['? AS ' + quote_column(col) for col in columns])}) AS source
            ON target.{quote_column(pk)} = source.{quote_column(pk)}
            WHEN MATCHED THEN UPDATE SET {set_expr}
            WHEN NOT MATCHED THEN INSERT ({quote_column(pk)}, {','.join(map(quote_column, columns))})
            VALUES (source.{quote_column(pk)}, {','.join(['source.' + quote_column(col) for col in columns])});
        """
        cursor.execute(sql, [pk_val] + values)

