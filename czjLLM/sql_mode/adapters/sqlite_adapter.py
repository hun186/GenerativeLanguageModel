# sql_mode/db_sqlite.py
import sqlite3
from typing import Iterable, List, Tuple, Any
from .base_adapter import DBAdapter

def Q(name: str) -> str:
    return f'"{name}"'  # SQLite 使用雙引號

def _normalize_type(t: str) -> str:
    # SQLite 寛鬆型別：一律用 TEXT，避免跨 DB 型別不一致
    return "TEXT"

class SQLiteAdapter(DBAdapter):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.conn = None
        self.cur = None

    # 支援 with 語法：with adapter.connect(): ...
    def connect(self):
        self.conn = sqlite3.connect(self.cfg["server"])
        self.cur = self.conn.cursor()
        return self

    def close(self):
        try:
            if self.cur: self.cur.close()
        finally:
            if self.conn: self.conn.close()

    def list_columns(self, table: str) -> List[str]:
        self.cur.execute(f'PRAGMA table_info({Q(table)})')
        return [row[1] for row in self.cur.fetchall()]

    def ensure_table(self, table: str, pk: str, pk_type: str = "TEXT"):
        self.cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {Q(table)} (
                {Q(pk)} {pk_type} PRIMARY KEY
            )
        """)
        self.conn.commit()

    def ensure_columns(self, table: str, columns: List[Tuple[str, str]]):
        existing = set(self.list_columns(table))
        for col, ctype in columns:
            if col not in existing:
                self.cur.execute(
                    f'ALTER TABLE {Q(table)} ADD COLUMN {Q(col)} {_normalize_type(ctype)}'
                )
        self.conn.commit()

    def select_pending_rows(self, *,
                            src_table: str, tgt_table: str,
                            pk: str, input_col: str, output_cols: List[str],
                            record_update_time: bool,
                            fetch_size: int = 500) -> Iterable[Tuple[Any, str]]:
        out_col = output_cols[0]
        sql = f"""
        SELECT src.{Q(pk)}, src.{Q(input_col)}
        FROM {Q(src_table)} AS src
        LEFT JOIN {Q(tgt_table)} AS tgt
          ON src.{Q(pk)} = tgt.{Q(pk)}
        WHERE (tgt.{Q(out_col)} IS NULL OR TRIM(tgt.{Q(out_col)}) = '')
          AND (src.{Q(input_col)} IS NOT NULL AND TRIM(src.{Q(input_col)}) <> '')
        """
        self.cur.execute(sql)
        while True:
            rows = self.cur.fetchmany(fetch_size)
            #print("rows at fetchmany",rows)
            if not rows:
                break
            for r in rows:
                yield (r[0], "" if r[1] is None else str(r[1]))

    def is_row_pending(self, *, src_table: str, tgt_table: str, pk: str, pk_value,
                       input_col: str, output_cols: List[str]) -> bool:
        """重新查詢單一列是否仍未完成；供真正切片前避免排程重複計算。"""
        out_col = output_cols[0]
        sql = f"""
        SELECT 1
        FROM {Q(src_table)} AS src
        LEFT JOIN {Q(tgt_table)} AS tgt
          ON src.{Q(pk)} = tgt.{Q(pk)}
        WHERE src.{Q(pk)} = ?
          AND (tgt.{Q(out_col)} IS NULL OR TRIM(tgt.{Q(out_col)}) = '')
          AND (src.{Q(input_col)} IS NOT NULL AND TRIM(src.{Q(input_col)}) <> '')
        LIMIT 1
        """
        self.cur.execute(sql, (pk_value,))
        return self.cur.fetchone() is not None
