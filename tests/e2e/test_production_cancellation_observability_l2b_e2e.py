"""One localhost production-boundary E2E for the L2b cancellation/observer bridge."""
from concurrent.futures import ThreadPoolExecutor
import json
import time
from types import SimpleNamespace

import pytest

from czjLLM.reduction import (
    ExecutionCancelled, ReductionStage, TaskExecutable, build_production_execution_context,
    ensure_production_observer, parse_reduction_config, request_execution_cancel,
)
from czjLLM.reduction.execution_budget import ExecutionBudget

pytestmark = pytest.mark.e2e


def test_production_cancellation_and_observability_l2b(fake_openai, tmp_path):
    fake_openai.delay = .2
    root = SimpleNamespace(
        mode="sql", task="E2E_SUMMARY", taskSetting={}, model_spec_name="e2e-model",
        model_spec=fake_openai.model_spec, max_tokens=4096, think_mode=False,
        PGMSubDir=str(tmp_path), llm_call_audit_run_id="l2b-e2e",
        llm_call_audit_path=str(tmp_path / "audit.csv"), _execution_budget=ExecutionBudget(1),
        config_path="l2b-e2e.yaml",
    )
    context = build_production_execution_context(
        root, observability_tags={"collection_id": "safe-collection",
                                  "manifest_fingerprint": "a" * 64},
    )
    stage = ReductionStage(TaskExecutable("E2E_SUMMARY"), parse_reduction_config(
        {"enabled": True, "profile": "concat_text"}
    ))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(stage.execute, ["ROW_ID=first", "ROW_ID=later"], context)
        deadline = time.time() + 5
        while not fake_openai.requests and time.time() < deadline:
            time.sleep(.01)
        assert fake_openai.requests
        assert request_execution_cancel(root, source="e2e")
        with pytest.raises(ExecutionCancelled):
            pending.result(timeout=5)

    observer = ensure_production_observer(root)
    observer.emit("run_cancelled", {"attempted": 2, "succeeded": 0,
                                    "failed": 2, "stop_reason": "cancelled"})
    assert len(fake_openai.requests) == 1
    assert root._execution_budget.snapshot().in_use == 0
    records = [json.loads(line) for line in observer.path.read_text(encoding="utf-8").splitlines()]
    events = {record["event"] for record in records}
    assert {"cancellation_requested", "reduction_stage_started",
            "reduction_stage_cancelled", "run_cancelled"} <= events
    serialized = json.dumps(records)
    for secret in ("ROW_ID=first", "E2E_SUMMARY", "e2e-dummy-key",
                   fake_openai.base_url, repr(fake_openai.model_spec)):
        assert secret not in serialized
