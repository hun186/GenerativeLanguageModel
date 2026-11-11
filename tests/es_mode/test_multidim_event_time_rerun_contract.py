"""Offline Issue #293: SRAF Event-first date completeness; no ES/LLM I/O."""
from pathlib import Path

import pytest

from czjLLM.common.required_output_guard import evaluate_required_output_checks
from czjLLM.es_mode.adapters.pending_policy import ElasticsearchPendingPolicyMixin
from czjLLM.es_mode.adapters.pending_policy_no_eventids import (
    ElasticsearchPendingPolicyMixin as LegacyPolicyMixin,
)

CHECK = {
    "path": "multidim_event_json",
    "full_path": "multidim_event_json",
    "validator": "multidim_event_time",
    "min_valid_count": 1,
    "relative_to_output": False,
}


def document(event_time="2023-08-24", precision="day", timeline=None):
    return {
        "multidim_event_json": [{
            "Event": [{
                "event_id": "E1", "time_iso": event_time,
                "time_raw": "近日" if event_time is None else event_time,
                "time_precision": precision,
            }],
            "Event_Timeline": [] if timeline is None else timeline,
        }]
    }


@pytest.mark.parametrize("source,expected", [
    (document(), True),  # Event-only: empty Timeline is legitimate
    (document(None, "unknown"), True),  # unknown, not an infinite rerun
    ({"multidim_event_json": [{
        "Event": [{"event_id": "E1", "time_iso": None,
                   "time_raw": None, "time_precision": "unknown"}],
        "Event_Timeline": [],
    }]}, True),  # exact user case: explicitly unknown, no raw time
    ({"multidim_event_json": [{
        "Event": [{"event_id": "E1", "time_iso": None,
                   "time_raw": None, "time_precision": "day"}],
        "Event_Timeline": [],
    }]}, False),  # null date/raw cannot claim day precision
    ({"multidim_event_json": [{
        "Event": [{"event_id": "E1", "time_iso": None,
                   "time_raw": "05:04", "time_precision": "minute"}],
        "Event_Timeline": [],
    }]}, True),  # partial raw time but unknown full date
    ({"multidim_event_json": [{
        "Event": [{"time_iso": None,
                   "time_raw": None, "time_precision": "unknown"}],
        "Event_Timeline": [],
    }]}, False),  # missing core event_id
    ({"multidim_event_json": [{
        "Event": [{"event_id": "E1", "time_iso": None,
                   "time_raw": None, "time_precision": "unknown"},
                  {"event_id": "E1", "time_iso": None,
                   "time_raw": None, "time_precision": "unknown"}],
        "Event_Timeline": [],
    }]}, False),  # duplicate event_id
    (document("not-an-iso-date"), False),
    (document("2025-02-30"), False),
    (document(timeline=[{
        "event_ids": ["E1"], "time_iso": "not-a-date",
        "time_raw": "not-a-date", "time_precision": "day",
    }]), False),
    ({"multidim_event_json": [{
        "Event": [], "Event_Timeline": [],
    }]}, False),
    ({"multidim_event_json": [{
        "Event": [{"event_id": "E1", "time_iso": None,
                   "time_raw": None, "time_precision": "unknown"}],
        "Event_Timeline": [{"event_ids": ["E1"], "time_iso": "2023-08-24",
                            "time_raw": "2023-08-24", "time_precision": "day"}],
    }]}, True),
])
def test_structured_date_or_unknown_contract(source, expected):
    passed, failure = evaluate_required_output_checks(source, [CHECK])
    assert passed is expected
    assert (failure is None) is expected


@pytest.mark.parametrize("mixin", [ElasticsearchPendingPolicyMixin, LegacyPolicyMixin])
def test_both_es_adapters_use_same_contract_and_keep_force_hash(mixin):
    class Policy(mixin):
        def __init__(self, rerun):
            self.cfg = {"output_col": "multidim_event_json", "rerun": rerun}

    rule = {key: value for key, value in CHECK.items() if key != "full_path"}
    policy = Policy({"enable": True, "required_output_checks": [rule]})
    for source in (document(), document(None, "unknown")):
        assert policy.check_source_pending(source, ["multidim_event_json"]).reason == "fresh_completed"
    assert policy.check_source_pending(document("invalid"), ["multidim_event_json"]).reason == "required_output_invalid"
    # Temporal rule success must NOT suppress independent explicit stale policy.
    forced = Policy({"enable": True, "required_output_checks": [rule], "pipeline_hash": "new"})
    source = document()
    source["multidim_event_json_meta"] = {"pipeline_hash": "old"}
    assert forced.check_source_pending(source, ["multidim_event_json"]).reason == "pipeline_hash_mismatch"


def test_legacy_timeline_only_rule_still_supported_when_explicitly_selected():
    old = dict(full_path="multidim_event_json.Event_Timeline.time_iso",
               validator="date", format="iso8601", min_valid_count=1)
    assert evaluate_required_output_checks(document(), [old])[0] is False


def test_all_three_sraf_es_yaml_examples_use_event_time_not_timeline_minimum():
    root = Path(__file__).resolve().parents[2] / "czjLLM" / "yaml"
    for name in (
        "es_config_fishing.yaml",
        "es_fishing_json__singlestage_in_multistage.yaml",
        "es_json_multistage_langroute_config.yaml",
    ):
        content = (root / name).read_text(encoding="utf-8")
        assert "validator: multidim_event_time" in content
        assert "path: multidim_event_json" in content
        assert "path: Event_Timeline.time_iso" not in content

def test_one_canonical_python_es_config_example_has_no_rerun_policy():
    import ast

    config_dir = Path(__file__).resolve().parents[2] / "czjLLM" / "config_es"
    examples = sorted(p.name for p in config_dir.glob("*.py.example"))
    assert examples == ["connection.py.example"], examples
    template = (config_dir / "connection.py.example").read_text(encoding="utf-8")
    ast.parse(template, filename="connection.py.example")
    module = ast.parse(template, filename="connection.py.example")
    assigned = {
        node.targets[0].id
        for node in module.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
    }
    assert "rerun" not in assigned
    assert "rerun = {" not in template
    assert 'es_index = ""' in template  # user must deliberately choose index
    assert 'es_ssl_assert_hostname = True' in template

    # Keep legacy YAML/runtime names. Private copies with the same basenames
    # are resolved independently of whether a public .example file exists.
    yaml_dir = config_dir.parent / "yaml"
    expected = {
        "es_config.yaml": "akconfig_es_test.py",
        "es_config_fishing.yaml": "akconfig_es_fishing.py",
        "es_config_mil.yaml": "akconfig_es_test_mil.py",
        "es_config_nav_intel_sentences.yaml": "akconfig_es_test_nav_intel_sentences_133.py",
        "es_config_satmeta.yaml": "akconfig_es_test_satmeta_133.py",
        "es_config_srp.yaml": "akconfig_es_test_srp_133.py",
        "es_config_single_stage_original.yaml": "akconfig_es_test_133.py",
        "es_json_multistage_langroute_config.yaml": "akconfig_es_test_133.py",
        "es_fishing_json__singlestage_in_multistage.yaml": "akconfig_es_fishing.py",
    }
    for yaml_name, private_name in expected.items():
        text = (yaml_dir / yaml_name).read_text(encoding="utf-8")
        assert f"es_config_file: czjLLM/config_es/{private_name}" in text


def test_two_yaml_jobs_sharing_connection_keep_independent_rerun_rules():
    from czjLLM.es_mode.config.rerun_logging import resolve_rerun_config

    connection = {"es_host": "https://example.invalid:9200", "es_index": "synthetic"}
    task_a = {"enable": True, "required_output_checks": [{
        "path": "multidim_event_json", "validator": "multidim_event_time",
        "min_valid_count": 1, "relative_to_output": False,
    }]}
    task_b = {"enable": False}
    merged_a, diagnostics_a = resolve_rerun_config(
        connection, lambda key, default=None: task_a if key == "rerun" else default)
    merged_b, diagnostics_b = resolve_rerun_config(
        connection, lambda key, default=None: task_b if key == "rerun" else default)
    assert merged_a == task_a
    assert merged_b == task_b
    assert "required_output_checks" not in merged_b
    assert not diagnostics_a["base_has_rerun"]
    assert not diagnostics_b["base_has_rerun"]
