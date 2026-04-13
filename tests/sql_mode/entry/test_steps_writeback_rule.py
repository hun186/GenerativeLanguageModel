from types import SimpleNamespace

from czjLLM.sql_mode.entry.steps import choose_columns_and_io_cols


class _AdapterStub:
    def list_columns(self, _table_name):
        return ["index", "File", "File_result", "File_route"]


def _build_get_param(values):
    def _get_param(key, default=None):
        return values.get(key, default)
    return _get_param


def test_choose_columns_loads_sql_flatten_writeback_rule_from_config():
    ctx = SimpleNamespace(primary_key="index", sql_table="sampleSrc", target_table="sampleSRC_LLM")
    adapter = _AdapterStub()
    sql_cfg = {}
    args = SimpleNamespace(config="dummy.yaml")
    get_param = _build_get_param(
        {
            "input_col": "File",
            "output_col": "File_result",
            "record_update_time": False,
            "sql_flatten_writeback_rule": 1,
            "sql_writeback_rules": [
                {"output_col": "File_route", "source": "stage", "stage": "route"},
                {"output_col": "File_result", "source": "stage", "stage": "extract"},
            ],
        }
    )

    choose_columns_and_io_cols(ctx, get_param, adapter, sql_cfg, args)

    assert ctx.sql_flatten_writeback_rule == 1


def test_choose_columns_fallback_sql_flatten_writeback_rule_to_zero_on_bad_value():
    ctx = SimpleNamespace(primary_key="index", sql_table="sampleSrc", target_table="sampleSRC_LLM")
    adapter = _AdapterStub()
    sql_cfg = {}
    args = SimpleNamespace(config="dummy.yaml")
    get_param = _build_get_param(
        {
            "input_col": "File",
            "output_col": "File_result",
            "record_update_time": False,
            "sql_flatten_writeback_rule": "not-an-int",
            "sql_writeback_rules": [
                {"output_col": "File_route", "source": "stage", "stage": "route"},
                {"output_col": "File_result", "source": "stage", "stage": "extract"},
            ],
        }
    )

    choose_columns_and_io_cols(ctx, get_param, adapter, sql_cfg, args)

    assert ctx.sql_flatten_writeback_rule == 0
