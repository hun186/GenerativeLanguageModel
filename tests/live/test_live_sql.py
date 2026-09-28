import pytest


@pytest.mark.live_sql
def test_live_sql_service_owned_rows_round_trip(live_sql_config, live_run_id):
    """Connectivity/storage smoke only; offline E2E owns application orchestration."""
    import pyodbc

    source = live_sql_config["LIVE_SQL_SOURCE_TABLE"]
    target = live_sql_config["LIVE_SQL_TARGET_TABLE"]
    conn = None
    cur = None
    try:
        conn = pyodbc.connect(live_sql_config["LIVE_SQL_CONN_STR"])
        cur = conn.cursor()
        cur.execute(f"INSERT INTO [{source}] ([id], [body]) VALUES (?, ?)", live_run_id, "live sql input")
        cur.execute(f"INSERT INTO [{target}] ([id], [analysis]) VALUES (?, ?)", live_run_id, "RESULT::" + live_run_id)
        conn.commit()
        row = cur.execute(f"SELECT [analysis] FROM [{target}] WHERE [id] = ?", live_run_id).fetchone()
        assert row and row[0] == "RESULT::" + live_run_id
    finally:
        try:
            if cur is not None:
                cur.execute(f"DELETE FROM [{target}] WHERE [id] = ?", live_run_id)
                cur.execute(f"DELETE FROM [{source}] WHERE [id] = ?", live_run_id)
            if conn is not None:
                conn.commit()
        finally:
            if conn is not None:
                conn.close()
