from czjLLM.row_processors import flatten_utils

def test_flatten_simple_dict():
    data = {"a": 1, "b": {"c": 2}}
    flat = flatten_utils.flatten_json(data)
    assert flat["a"] == 1
    assert flat["b.c"] == 2
