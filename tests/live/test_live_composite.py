import pytest


@pytest.mark.live_e2e
def test_live_llm_composite_protocol(live_llm_config, live_run_id, tmp_path):
    """Small complete live LLM artifact smoke; service-specific writes stay isolated."""
    from czjLLM.prompt_pipeline.pipeline_controller import PromptAPIPipeline

    output = tmp_path / f"{live_run_id}.txt"
    result = PromptAPIPipeline(content="Return exactly: CZJLLM_LIVE_OK", OutputSaveFN=str(output), max_tokens=32, model_spec=live_llm_config, PGMSubDir=str(tmp_path)).proc()
    assert result["ok"] and output.read_text(encoding="utf-8").strip()


@pytest.mark.live_e2e
def test_live_sql_and_llm_owned_row_smoke(
    live_llm_config, live_sql_config, live_run_id, tmp_path
):
    """Real SQL-owned row → real LLM → exact target PK, with owned cleanup."""
    import pyodbc
    from czjLLM.prompt_pipeline.pipeline_controller import PromptAPIPipeline

    source = live_sql_config["LIVE_SQL_SOURCE_TABLE"]
    target = live_sql_config["LIVE_SQL_TARGET_TABLE"]
    conn = pyodbc.connect(live_sql_config["LIVE_SQL_CONN_STR"])
    cur = conn.cursor()
    try:
        cur.execute(
            f"INSERT INTO [{source}] ([id], [body]) VALUES (?, ?)",
            live_run_id,
            f"ROW_ID={live_run_id} Return a short non-empty result",
        )
        conn.commit()
        body = cur.execute(
            f"SELECT [body] FROM [{source}] WHERE [id] = ?", live_run_id
        ).fetchone()[0]
        result = PromptAPIPipeline(
            content=body,
            max_tokens=32,
            model_spec=live_llm_config,
            PGMSubDir=str(tmp_path),
        ).proc()
        assert result["ok"] and str(result["output"]).strip()
        cur.execute(
            f"INSERT INTO [{target}] ([id], [analysis]) VALUES (?, ?)",
            live_run_id,
            result["output"],
        )
        conn.commit()
        written = cur.execute(
            f"SELECT [analysis] FROM [{target}] WHERE [id] = ?", live_run_id
        ).fetchone()
        assert written and str(written[0]).strip()
    finally:
        cur.execute(f"DELETE FROM [{target}] WHERE [id] = ?", live_run_id)
        cur.execute(f"DELETE FROM [{source}] WHERE [id] = ?", live_run_id)
        conn.commit()
        conn.close()
