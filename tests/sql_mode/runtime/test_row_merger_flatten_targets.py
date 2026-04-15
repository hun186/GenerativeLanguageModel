from types import SimpleNamespace

from czjLLM.sql_mode.runtime.row_merger_generic import _resolve_flatten_targets


def test_resolve_flatten_targets_supports_multi_rules():
    ctx = SimpleNamespace(
        flatten_json_output=True,
        target_table="sampleSRC_LLM",
        output_col="File_result",
        save_raw_input_when_flatten=True,
        allowed_output_fields=["defaultA"],
        sql_writeback_rules=[
            {"output_col": "File_route", "source": "stage", "stage": "route"},
            {"output_col": "File_result", "source": "stage", "stage": "extract"},
        ],
        sql_flatten_writeback_rules=[
            {"writeback_rule": 0, "enabled": True, "allowed_output_fields": ["route"]},
            {"writeback_rule": 1, "enabled": True, "allowed_output_fields": ["formalName"]},
        ],
    )
    write_map = {
        "File_route": '{"route":"org"}',
        "File_result": '[{"formalName":"ACME"}]',
    }

    targets = _resolve_flatten_targets(ctx, write_map, write_map["File_result"])

    assert len(targets) == 2
    assert targets[0]["output_col"] == "File_route"
    assert targets[0]["allowed_fields"] == ["route"]
    assert targets[0]["subtable_name"] == "sampleSRC_LLM_File_route_flattened"
    assert targets[1]["output_col"] == "File_result"
    assert targets[1]["allowed_fields"] == ["formalName"]


def test_resolve_flatten_targets_fallback_to_single_source():
    ctx = SimpleNamespace(
        flatten_json_output=True,
        target_table="sampleSRC_LLM",
        output_col="File_result",
        save_raw_input_when_flatten=False,
        allowed_output_fields=["formalName"],
        sql_writeback_rules=[],
        sql_flatten_writeback_rules=None,
    )

    targets = _resolve_flatten_targets(ctx, {}, '[{"formalName":"ACME"}]')

    assert len(targets) == 1
    assert targets[0]["output_col"] == "File_result"
    assert targets[0]["allowed_fields"] == ["formalName"]


def test_resolve_flatten_targets_uses_global_allowed_fields_when_rule_not_set():
    ctx = SimpleNamespace(
        flatten_json_output=True,
        target_table="sampleSRC_LLM",
        output_col="File_result",
        save_raw_input_when_flatten=False,
        allowed_output_fields=["formalName", "functionalDomain"],
        sql_writeback_rules=[{"output_col": "File_result", "source": "combined"}],
        sql_flatten_writeback_rules=[{"writeback_rule": 0, "enabled": True}],
    )

    targets = _resolve_flatten_targets(ctx, {"File_result": '[{"formalName":"ACME"}]'}, '[{"formalName":"ACME"}]')

    assert len(targets) == 1
    assert targets[0]["allowed_fields"] == ["formalName", "functionalDomain"]


def test_resolve_flatten_targets_respects_all_rules_disabled():
    ctx = SimpleNamespace(
        flatten_json_output=True,
        target_table="sampleSRC_LLM",
        output_col="File_result",
        save_raw_input_when_flatten=False,
        allowed_output_fields=["formalName"],
        sql_writeback_rules=[{"output_col": "File_result", "source": "combined"}],
        sql_flatten_writeback_rules=[{"writeback_rule": 0, "enabled": False}],
    )

    targets = _resolve_flatten_targets(ctx, {"File_result": '[{"formalName":"ACME"}]'}, '[{"formalName":"ACME"}]')

    assert targets == []
