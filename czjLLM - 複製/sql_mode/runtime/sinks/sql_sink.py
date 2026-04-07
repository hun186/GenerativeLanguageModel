# sql_mode/runtime/sinks/sql_sink.py
from typing import Any, Optional, List, Dict
import sqlite3, pyodbc

#from czjLLM.prompt_pipeline.pipeline_controller import (
    #flatten_row_based_json_array_to_subtable,
    #quote_column,
#)
from czjLLM.sql_utils.writer import flatten_row_based_json_array_to_subtable
from czjLLM.sql_utils.row_utils import upsert_single_value
from czjLLM.sql_utils.common import quote_column
from ...schema.schema_ops import ensure_flatten_schema as ensure_flatten_schema_op

class SqlSink:
    def __init__(self, ctx, is_sqlite=False):
        self.ctx = ctx
        self.is_sqlite = is_sqlite
        self.conn = None
        self.cursor = None
        self._flatten_ready_sig = None   # ✨ 用來記錄已完成的 schema 簽章

    def open(self):
        if getattr(self.ctx, "is_sqlite", self.is_sqlite):
            # 關鍵：timeout 拉長、WAL、synchronous、busy_timeout
            self.conn = sqlite3.connect(self.ctx.sqlite_path, timeout=60)
            cur = self.conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
            cur.execute("PRAGMA busy_timeout=60000;")
            cur.close()
        else:
            self.conn = pyodbc.connect(self.ctx.sql_connection_string)
        self.cursor = self.conn.cursor()

    def write_main(self, pk, result_text, update_time=None):
        # 舉例：沿用你原本 upsert_single_value 內的 SQL
        #print("result_text in write_main",result_text)
        upsert_single_value(self.ctx, self.cursor, pk, result_text,
                            is_sqlite=self.is_sqlite, update_time=update_time)
        # 關鍵：每筆後就 commit，避免長交易持有鎖
        self.conn.commit()

    # ★ 這裡接上你原本的自動建/補子表 schema
    def ensure_flatten_schema(self, allowed_fields=None):
        sig = (
            self.ctx.subtable_name,
            tuple(allowed_fields or (self.ctx.allowed_output_fields or [])),
            bool(getattr(self.ctx, "save_raw_input_when_flatten", False)),
        )
        if self._flatten_ready_sig == sig:
            return
        ensure_flatten_schema_op(self.ctx, self.cursor, self.is_sqlite)
        self.conn.commit()
        self._flatten_ready_sig = sig
            
    def fetch_input(self, pk):
        # 和舊版相同的 SELECT
        try:
            q = (f"SELECT {quote_column(self.ctx.input_col)} "
                 f"FROM {quote_column(self.ctx.sql_table)} "
                 f"WHERE {quote_column(self.ctx.primary_key)} = ?")
            self.cursor.execute(q, (pk,))
            r = self.cursor.fetchone()
            return r[0] if r else None
        except Exception:
            return None

    def write_flatten(self, pk, json_array, save_raw_input, input_col, input_value):
        flatten_row_based_json_array_to_subtable(
            cursor=self.cursor,
            sub_table_name=self.ctx.subtable_name,
            pk_value=pk,
            json_array=json_array,
            key_col=self.ctx.primary_key,
            seq_col="seq",
            save_raw_input=save_raw_input,
            input_col=input_col,
            input_col_value=input_value,
            is_sqlite=self.is_sqlite,
        )
        # 同樣每批後 commit
        self.conn.commit()
    # ▶ 新增：顯式 flush，close() 前一定再保險一次
    def flush(self):
        try:
            if self.conn:
                self.conn.commit()
        except Exception:
            pass

    def close(self):
        try:
            self.flush()
        except Exception:
            pass
        try:
            if self.cursor: self.cursor.close()
        except Exception:
            pass
        try:
            if self.conn: self.conn.close()
        except Exception:
            pass
    '''
    def close(self):
        try: 
            if self.cursor: self.cursor.close()
        except: pass
        try: 
            if self.conn: self.conn.close()
        except: pass
    '''