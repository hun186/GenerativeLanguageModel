from __future__ import annotations

import json
from types import SimpleNamespace

from czjLLM.prompt_pipeline.pending_central import record_adjustment


def test_record_adjustment_returns_persisted_log_path(tmp_path):
    log_path = tmp_path / "logs" / "pending-adjustments.jsonl"
    ctx = SimpleNamespace(
        pending_running_console_enabled=True,
        pending_running_console_log_path=str(log_path),
        mode="es",
        task="multidim-event",
        target_index="news-test",
    )

    returned = record_adjustment(
        ctx,
        "writeback_failed_schema_release",
        pk="doc-1",
        error="Event[1] contains fields not present in the current schema: ['constance']",
        output_col="multidim_event_json",
        combined_result_path="runtime/doc-1-result.json",
    )

    assert returned == log_path
    record = json.loads(log_path.read_text(encoding="utf-8"))
    assert record["event"] == "writeback_failed_schema_release"
    assert record["pk"] == "doc-1"
    assert record["output_col"] == "multidim_event_json"
    assert record["combined_result_path"] == "runtime/doc-1-result.json"
    assert "constance" in record["error"]
