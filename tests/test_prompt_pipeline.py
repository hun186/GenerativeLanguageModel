from czjLLM.prompt_pipeline import prompt_generator, result_handler

def test_prompt_generator():
    prompt = prompt_generator.generate_prompt("Hello", template="Q: {input}\nA:")
    assert "Hello" in prompt
    assert "A:" in prompt

def test_result_handler_parsing():
    raw_output = '{"answer": "42"}'
    parsed = result_handler.parse_result(raw_output)
    assert parsed["answer"] == "42"
