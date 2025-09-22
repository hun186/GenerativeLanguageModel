import pytest
from czjLLM.handlers import handle_txt_file

def test_handle_txt_file_basic(tmp_path,defer_merge=False):
    # 建立測試檔案
    test_file = tmp_path / "sample.txt"
    test_file.write_text("This is a test")

    result = handle_txt_file.handle_single_input_file(str(test_file))
    assert isinstance(result, str), "Result should be a string"
    assert "test" in result.lower(), "Processed text should contain 'test'"

if __name__ == '__main__':
    test_handle_txt_file_basic()