import sqlite3

import pytest

pytest.importorskip("colorama")
pytest.importorskip("yaml")

from czjLLM.sql_mode.adapters.sqlite_adapter import SQLiteAdapter
from czjLLM.sql_mode.adapters.mssql_adapter import Q as mssql_quote, _trim_expr as mssql_trim_expr
from czjLLM.common.pending_conditions import (
    build_all_outputs_complete_condition,
    build_any_output_missing_condition,
)


def _sqlite_adapter_with_rows():
    adapter = SQLiteAdapter({"server": ":memory:"})
    adapter.conn = sqlite3.connect(":memory:")
    adapter.cur = adapter.conn.cursor()
    adapter.cur.execute('CREATE TABLE src (id TEXT PRIMARY KEY, body TEXT)')
    adapter.cur.execute('CREATE TABLE tgt (id TEXT PRIMARY KEY, route TEXT, result TEXT, audit TEXT)')
    adapter.cur.executemany(
        'INSERT INTO src (id, body) VALUES (?, ?)',
        [("complete", "text"), ("missing_audit", "text"), ("missing_all", "text")],
    )
    adapter.cur.executemany(
        'INSERT INTO tgt (id, route, result, audit) VALUES (?, ?, ?, ?)',
        [("complete", "zh", "[]", "[]"), ("missing_audit", "zh", "[]", None)],
    )
    adapter.conn.commit()
    return adapter


def test_sqlite_pending_recheck_requires_all_output_columns_complete():
    adapter = _sqlite_adapter_with_rows()
    try:
        output_cols = ["route", "result", "audit"]

        assert adapter.is_row_pending(
            tgt_table="tgt", pk="id", pk_value="complete", output_cols=output_cols
        ) is False
        assert adapter.is_row_pending(
            tgt_table="tgt", pk="id", pk_value="missing_audit", output_cols=output_cols
        ) is True
        assert adapter.is_row_pending(
            tgt_table="tgt", pk="id", pk_value="missing_all", output_cols=output_cols
        ) is True
    finally:
        adapter.close()


def test_sqlite_select_pending_rows_includes_rows_with_any_missing_output_column():
    adapter = _sqlite_adapter_with_rows()
    try:
        rows = list(
            adapter.select_pending_rows(
                src_table="src",
                tgt_table="tgt",
                pk="id",
                input_col="body",
                output_cols=["route", "result", "audit"],
                record_update_time=False,
            )
        )

        assert [row[0] for row in rows] == ["missing_audit", "missing_all"]
    finally:
        adapter.close()


def test_mssql_pending_sql_checks_all_output_columns():
    condition = build_all_outputs_complete_condition(["route", "result", "audit"], mssql_quote, mssql_trim_expr)
    missing_condition = build_any_output_missing_condition(["route", "result", "audit"], mssql_quote, mssql_trim_expr)

    assert "[route]" in condition
    assert "[result]" in condition
    assert "[audit]" in condition
    assert " AND " in condition
    assert "tgt.[route]" in missing_condition
    assert "tgt.[result]" in missing_condition
    assert "tgt.[audit]" in missing_condition
    assert " OR " in missing_condition
