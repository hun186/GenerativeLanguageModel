from czjLLM.handlers import test_handle_txt_mode

def test_handle_txt_file_basic(tmp_path):
    # 建立測試檔案
    test_file = tmp_path / "sample.txt"
    test_file.write_text("This is a test")

    result = test_handle_txt_mode.test_handle_single_input_file_happy_path(str(test_file))
    assert isinstance(result, str), "Result should be a string"
    assert "test" in result.lower(), "Processed text should contain 'test'"
