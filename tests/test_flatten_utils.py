import pytest
from czjLLM.row_processors.flatten_utils import extract_json_list_for_flatten

def test_string_input_with_allowed_fields_filters_and_fills_missing_keys():
    s = '[{"a":1,"b":2},{"a":3}]'
    out = extract_json_list_for_flatten(s, allowed_fields=["a","b"])
    assert out == [{"a":1,"b":2}, {"a":3,"b":""}]

def test_list_input_without_allowed_fields_returns_as_is():
    data = [{"x":10}, {"y":20}]
    out = extract_json_list_for_flatten(data)
    assert out == data  # 不過濾時應原樣回傳（非同一物件沒關係，值一致）

def test_non_dict_items_are_ignored_and_missing_keys_empty_string():
    data = [{"a":1}, ["not-a-dict"], "str", 123, {"b":2}]
    out = extract_json_list_for_flatten(data, allowed_fields=["a","b"])
    # 只保留 dict，且缺鍵補空字串
    assert out == [{"a":1,"b":""}, {"a":"","b":2}]

def test_bad_json_string_returns_empty_list(capfd):
    s = '{"a":1'  # 壞 JSON
    out = extract_json_list_for_flatten(s, allowed_fields=["a"])
    assert out == []
    # 可選：確認有錯誤訊息（不強制字面一致）
    captured = capfd.readouterr().out
    assert "JSON 解析失敗" in captured

def test_allowed_fields_empty_list_behaves_as_no_filter():
    data = [{"a":1,"b":2}]
    # 注意：allowed_fields=[] 在函式中視為 False，故相當於不過濾
    out = extract_json_list_for_flatten(data, allowed_fields=[])
    assert out == data
