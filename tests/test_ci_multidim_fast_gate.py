"""Guard CI fast feedback without weakening the full GLM offline E2E gate."""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / ".github" / "workflows" / "ci.yml"
FAST = {
    "Verify offline Quality retry budget contract (Issue 313)": (
        "tests/es_mode/test_quality_retry_contract.py",),
    "Verify offline multidim Event and Timeline time rerun audit": (
        "tests/test_multidim_time_audit.py",
        "tests/es_mode/test_multidim_profile_audit.py",
        "tests/es_mode/test_multidim_event_time_rerun_contract.py",
        "tests/es_mode/test_es_rerun_policy_static_preflight.py",
    ),
    "Verify offline GLM MultiDim search-consumer schema contract v1": (
        "tests/es_mode/test_multidim_search_contract_v1.py",),
    "Verify read-only MultiDim live-Mapping contract probe": (
        "tests/es_mode/test_multidim_es_mapping_readonly.py",),
    "Verify privacy-safe nested-only MultiDim ES sample (offline)": (
        "tests/es_mode/test_multidim_structured_sample_readonly.py",),
}
ORDER_CHECK = "Verify fast MultiDim gate ordering and no omitted checks"
FULL_GATE = "Run offline production E2E gate"


def test_multidim_fast_gate_precedes_full_e2e_without_removing_it():
    data = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    job = data["jobs"]["offline-e2e"]
    steps = job["steps"]
    labels = [step.get("name") for step in steps]
    for name in (*FAST, ORDER_CHECK, FULL_GATE):
        assert labels.count(name) == 1, name

    # All required dependencies and import paths still initialize first.
    setup = labels.index("Set PYTHONPATH")
    collected = labels.index("Prove offline E2E dependency completeness")
    assert setup < collected < min(labels.index(name) for name in FAST)
    assert max(labels.index(name) for name in FAST) < labels.index(ORDER_CHECK)
    assert labels.index(ORDER_CHECK) < labels.index(FULL_GATE)

    gate = steps[labels.index(FULL_GATE)]
    assert "tests/e2e -m e2e" in gate["run"]
    assert "--maxfail=1" in gate["run"]
    for name, paths in FAST.items():
        step = steps[labels.index(name)]
        command = step["run"]
        assert "python -m pytest -q" in command
        assert "--maxfail=1" in command
        assert not step.get("continue-on-error", False)
        assert not step.get("if"), name
        for path in paths:
            assert command.count(path) == 1, (name, path)
            assert (REPO / path).is_file(), path
    # Same job and environment; no unreviewed self-hosted/privileged shortcut.
    assert job["runs-on"] == "ubuntu-latest"
