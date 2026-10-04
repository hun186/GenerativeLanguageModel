# sql_mode/db_sqlite.py
import sqlite3
from threading import RLock
from typing import Iterable, List, Tuple, Any
from .base_adapter import DBAdapter
from czjLLM.common.pending_conditions import build_any_output_missing_condition
from czjLLM.common.pending_decision import PendingDecision
from .pending_freshness import build_pending_condition, semantic_freshness_config

def Q(name: str) -> str:
    return f'"{name}"'  # SQLite 使用雙引號

def _normalize_type(t: str) -> str:
    # SQLite 寛鬆型別：一律用 TEXT，避免跨 DB 型別不一致
    return "TEXT"

def _trim_expr(expr: str) -> str:
    return f'TRIM({expr})'

class SQLiteAdapter(DBAdapter):
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.conn = None
        self.cur = None
        self._lock = RLock()

    # 支援 with 語法：with adapter.connect(): ...
    def connect(self):
        self.conn = sqlite3.connect(self.cfg["server"])
        self.cur = self.conn.cursor()
        return self

    def _can_open_independent_connection(self) -> bool:
        server = str(self.cfg.get("server", "") or "")
        return bool(server) and server != ":memory:"

    def _open_independent_connection(self):
        return sqlite3.connect(self.cfg["server"], timeout=60)

    def close(self):
        with self._lock:
            try:
                if self.cur:
                    self.cur.close()
            finally:
                if self.conn:
                    self.conn.close()

    def list_columns(self, table: str) -> List[str]:
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(f'PRAGMA table_info({Q(table)})')
                return [row[1] for row in cur.fetchall()]
            finally:
                cur.close()

    def ensure_table(self, table: str, pk: str, pk_type: str = "TEXT"):
        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(f"""
                    CREATE TABLE IF NOT EXISTS {Q(table)} (
                        {Q(pk)} {pk_type} PRIMARY KEY
                    )
                """)
                self.conn.commit()
            finally:
                cur.close()

    def ensure_columns(self, table: str, columns: List[Tuple[str, str]]):
        existing = set(self.list_columns(table))
        with self._lock:
            cur = self.conn.cursor()
            try:
                for col, ctype in columns:
                    if col not in existing:
                        cur.execute(
                            f'ALTER TABLE {Q(table)} ADD COLUMN {Q(col)} {_normalize_type(ctype)}'
                        )
                self.conn.commit()
            finally:
                cur.close()

    def is_row_pending(self, *, tgt_table: str, pk: str, pk_value: Any, output_cols: List[str]) -> bool:
        return self.check_row_pending(tgt_table=tgt_table, pk=pk, pk_value=pk_value, output_cols=output_cols).pending

    def check_row_pending(self, *, tgt_table: str, pk: str, pk_value: Any, output_cols: List[str]) -> PendingDecision:
        if not output_cols:
            return PendingDecision(True, "missing_output")
        expected, identity_col = semantic_freshness_config(self.cfg)
        selected = [Q(c) for c in output_cols] + ([Q(identity_col)] if identity_col else [])
        sql = f"""
        SELECT {', '.join(selected)}
        FROM {Q(tgt_table)}
        WHERE {Q(pk)} = ?
        LIMIT 1
        """
        def decide(row):
            if row is None:
                return PendingDecision(True, "row_missing")
            if any(v is None or not str(v).strip() for v in row[:len(output_cols)]):
                return PendingDecision(True, "missing_output")
            if expected is not None:
                persisted = row[-1]
                if persisted is None or not str(persisted).strip():
                    return PendingDecision(True, "missing_processing_identity", {"expected_execution_fingerprint": expected})
                if str(persisted) != expected:
                    return PendingDecision(True, "execution_fingerprint_mismatch", {"expected_execution_fingerprint": expected, "persisted_execution_fingerprint": str(persisted)})
            return PendingDecision(False, "fresh_completed")
        if self._can_open_independent_connection():
            # Pending recheck may run inside producer worker threads. Use a fresh
            # read-only operation connection for file-backed SQLite so thread
            # ownership of the main iterator connection cannot disable recheck.
            conn = self._open_independent_connection()
            try:
                cur = conn.cursor()
                try:
                    cur.execute(sql, (pk_value,))
                    row = cur.fetchone()
                    return decide(row)
                finally:
                    cur.close()
            finally:
                conn.close()

        with self._lock:
            cur = self.conn.cursor()
            try:
                cur.execute(sql, (pk_value,))
                row = cur.fetchone()
                return decide(row)
            finally:
                cur.close()

    def select_pending_rows(self, *,
                            src_table: str, tgt_table: str,
                            pk: str, input_col: str, output_cols: List[str],
                            record_update_time: bool,
                            fetch_size: int = 500,
                            extra_input_cols: List[str] | None = None) -> Iterable[Tuple[Any, str]]:
        extra_input_cols = [c for c in (extra_input_cols or []) if c and c != input_col]
        select_cols = [f"src.{Q(pk)}", f"src.{Q(input_col)}"] + [f"src.{Q(c)}" for c in extra_input_cols]
        pending_condition, pending_params = build_pending_condition(output_cols, Q, _trim_expr, cfg=self.cfg)
        sql = f"""
        SELECT {", ".join(select_cols)}
        FROM {Q(src_table)} AS src
        LEFT JOIN {Q(tgt_table)} AS tgt
          ON src.{Q(pk)} = tgt.{Q(pk)}
        WHERE ({pending_condition})
          AND (src.{Q(input_col)} IS NOT NULL AND TRIM(src.{Q(input_col)}) <> '')
        """
        cur = self.conn.cursor()
        try:
            with self._lock:
                cur.execute(sql, pending_params)
            while True:
                with self._lock:
                    rows = cur.fetchmany(fetch_size)
                #print("rows at fetchmany",rows)
                if not rows:
                    break
                for r in rows:
                    text = "" if r[1] is None else str(r[1])
                    extras = {}
                    for i, c in enumerate(extra_input_cols, start=2):
                        extras[c] = "" if r[i] is None else str(r[i])
                    yield (r[0], text, extras)
        finally:
            cur.close()
