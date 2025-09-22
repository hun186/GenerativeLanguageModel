from czjLLM.prompt_pipeline import prompt_generator, result_handler

def test_result_handler_parsing():
    raw_output = '{"answer": "42"}'
    parsed = result_handler.parse_result(raw_output)
    assert parsed["answer"] == "42"
