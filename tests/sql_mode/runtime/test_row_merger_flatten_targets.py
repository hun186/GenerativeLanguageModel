from types import SimpleNamespace

from czjLLM.sql_mode.runtime.row_merger_generic import (
    _resolve_flatten_targets,
    _process_flatten_target,
)


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




def test_resolve_flatten_targets_uses_llm_result_prefix_when_target_table_empty():
    ctx = SimpleNamespace(
        flatten_json_output=True,
        target_table="",
        output_col="OPA2",
        save_raw_input_when_flatten=False,
        allowed_output_fields=["formalName"],
        sql_writeback_rules=[{"output_col": "OPA2", "source": "combined"}],
        sql_flatten_writeback_rules=[{"writeback_rule": 0, "enabled": True}],
    )

    targets = _resolve_flatten_targets(ctx, {"OPA2": '[{"formalName":"ACME"}]'}, '[{"formalName":"ACME"}]')

    assert len(targets) == 1
    assert targets[0]["subtable_name"] == "LLM_result_OPA2_flattened"



def test_resolve_flatten_targets_avoids_double_prefix_when_output_col_already_prefixed():
    ctx = SimpleNamespace(
        flatten_json_output=True,
        target_table="",
        main_sheet_name="LLM_result",
        output_col="LLM_result_OPA2",
        save_raw_input_when_flatten=False,
        allowed_output_fields=["formalName"],
        sql_writeback_rules=[{"output_col": "LLM_result_OPA2", "source": "combined"}],
        sql_flatten_writeback_rules=[{"writeback_rule": 0, "enabled": True}],
    )

    targets = _resolve_flatten_targets(
        ctx,
        {"LLM_result_OPA2": '[{"formalName":"ACME"}]'},
        '[{"formalName":"ACME"}]',
    )

    assert len(targets) == 1
    assert targets[0]["subtable_name"] == "LLM_result_OPA2_flattened"

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


def test_resolve_flatten_targets_supports_rule_save_input_alias():
    ctx = SimpleNamespace(
        flatten_json_output=True,
        target_table="sampleSRC_LLM",
        output_col="File_result",
        save_raw_input_when_flatten=False,
        allowed_output_fields=["formalName"],
        sql_writeback_rules=[{"output_col": "File_result", "source": "combined"}],
        sql_flatten_writeback_rules=[{"writeback_rule": 0, "enabled": True, "flatten_store_input_col": True}],
    )

    targets = _resolve_flatten_targets(ctx, {"File_result": '[{"formalName":"ACME"}]'}, '[{"formalName":"ACME"}]')

    assert len(targets) == 1
    assert targets[0]["save_raw_input"] is True


def test_process_flatten_target_creates_schema_even_when_source_not_json():
    class DummySink:
        def __init__(self):
            self.ctx = SimpleNamespace()
            self.schema_calls = []
            self.write_calls = []

        def ensure_flatten_schema(self, allowed_fields=None):
            self.schema_calls.append(allowed_fields)

        def fetch_input(self, pk):
            return None

        def write_flatten(self, *args, **kwargs):
            self.write_calls.append((args, kwargs))

    ctx = SimpleNamespace(primary_key="id", input_col="File", subtable_input_col="File")
    sink = DummySink()
    ft = {
        "output_col": "File_route",
        "subtable_name": "sampleSRC_LLM_File_route_flattened",
        "allowed_fields": ["route"],
        "save_raw_input": False,
        "source_text": "not-json",
    }

    wrote = _process_flatten_target(ctx, sink, "pk-1", ft)

    assert wrote is False
    assert sink.schema_calls == [["route"]]
    assert sink.write_calls == []


def test_process_flatten_target_uses_input_col_when_rule_enables_raw_input():
    class DummySink:
        def __init__(self):
            self.ctx = SimpleNamespace()
            self.schema_calls = []
            self.write_calls = []
            self.fetch_calls = []

        def ensure_flatten_schema(self, allowed_fields=None):
            self.schema_calls.append(allowed_fields)

        def fetch_input(self, pk):
            self.fetch_calls.append(pk)
            return "RAW-INPUT"

        def write_flatten(self, *args, **kwargs):
            self.write_calls.append((args, kwargs))

    ctx = SimpleNamespace(
        primary_key="id",
        input_col="File",
        save_raw_input_when_flatten=False,
        subtable_input_col=None,
    )
    sink = DummySink()
    ft = {
        "output_col": "File_result",
        "subtable_name": "sampleSRC_LLM_File_result_flattened",
        "allowed_fields": ["formalName"],
        "save_raw_input": True,
        "source_text": '[{"formalName":"ACME"}]',
    }

    wrote = _process_flatten_target(ctx, sink, "pk-1", ft)

    assert wrote is True
    assert sink.schema_calls == [["formalName"]]
    assert sink.fetch_calls == ["pk-1"]
    assert len(sink.write_calls) == 1
    _, kwargs = sink.write_calls[0]
    assert kwargs["save_raw_input"] is True
    assert kwargs["input_col"] == "File"
    assert kwargs["input_value"] == "RAW-INPUT"
