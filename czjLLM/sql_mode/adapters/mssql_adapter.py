# sql_mode/db_mssql.py
import pyodbc
from typing import Iterable, List, Tuple, Any
from .base_adapter import DBAdapter
from czjLLM.common.pending_conditions import build_any_output_missing_condition
from czjLLM.common.pending_decision import PendingDecision
from .pending_freshness import build_pending_condition, semantic_freshness_config

def Q(name: str) -> str:
    return f'[{name}]'  # SQL Server 使用中括號

def _trim_expr(expr: str) -> str:
    return f'LTRIM(RTRIM({expr}))'

class MSSQLAdapter(DBAdapter):
    def __init__(self, cfg: dict):
        """
        需要 cfg["connection_string"]（請在呼叫前組好）
        """
        self.cfg = cfg
        self.conn = None
        self.cur = None

    def connect(self):
        self.conn = pyodbc.connect(self.cfg["connection_string"])
        self.cur = self.conn.cursor()
        return self

    def close(self):
        try:
            if self.cur: self.cur.close()
        finally:
            if self.conn: self.conn.close()

    def list_columns(self, table: str) -> List[str]:
        self.cur.execute(f"SELECT TOP 1 * FROM {Q(table)}")
        return [d[0] for d in self.cur.description]

    def ensure_table(self, table: str, pk: str, pk_type: str = "NVARCHAR(255)"):
        # 修正：無尾逗號
        self.cur.execute(f"""
        IF OBJECT_ID(N'{table}', N'U') IS NULL
        BEGIN
            CREATE TABLE {Q(table)} (
                {Q(pk)} {pk_type} PRIMARY KEY
            )
        END
        """)
        self.conn.commit()

    def ensure_columns(self, table: str, columns: List[Tuple[str, str]]):
        exist = set(self.list_columns(table))
        for col, ctype in columns:
            if col not in exist:
                self.cur.execute(f"ALTER TABLE {Q(table)} ADD {Q(col)} {ctype}")
        self.conn.commit()

    def is_row_pending(self, *, tgt_table: str, pk: str, pk_value: Any, output_cols: List[str]) -> bool:
        return self.check_row_pending(tgt_table=tgt_table, pk=pk, pk_value=pk_value, output_cols=output_cols).pending

    def check_row_pending(self, *, tgt_table: str, pk: str, pk_value: Any, output_cols: List[str]) -> PendingDecision:
        if not output_cols:
            return PendingDecision(True, "missing_output")
        expected, identity_col = semantic_freshness_config(self.cfg)
        selected = [Q(c) for c in output_cols] + ([Q(identity_col)] if identity_col else [])
        sql = f"""
        SELECT TOP 1 {', '.join(selected)}
        FROM {Q(tgt_table)}
        WHERE {Q(pk)} = ?
        """
        self.cur.execute(sql, (pk_value,))
        row = self.cur.fetchone()
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
          AND (src.{Q(input_col)} IS NOT NULL AND LTRIM(RTRIM(src.{Q(input_col)})) <> '')
        """
        self.cur.execute(sql, pending_params)
        while True:
            rows = self.cur.fetchmany(fetch_size)
            if not rows:
                break
            for r in rows:
                text = "" if r[1] is None else str(r[1])
                extras = {}
                for i, c in enumerate(extra_input_cols, start=2):
                    extras[c] = "" if r[i] is None else str(r[i])
                yield (r[0], text, extras)
