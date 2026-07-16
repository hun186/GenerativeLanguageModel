import json

from czjLLM.sql_utils.common import safe_sql_value


def test_safe_sql_value_serializes_dict_for_odbc_binding():
    value = {"date": "2026-07-16", "location": "台北"}

    out = safe_sql_value(value)

    assert isinstance(out, str)
    assert json.loads(out) == value


def test_safe_sql_value_serializes_nested_list_for_odbc_binding():
    value = [{"name": "A"}, {"name": "B"}]

    out = safe_sql_value(value)

    assert isinstance(out, str)
    assert json.loads(out) == value


def test_safe_sql_value_keeps_scalar_list_legacy_join_behavior():
    assert safe_sql_value(["A", "B", 3]) == "A, B, 3"
