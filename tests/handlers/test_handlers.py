import os
from czjLLM.handlers import handle_txt_file
from czjLLM.job_manager.job_config import LLMJobConfig

def test_handle_txt_file_basic(tmp_path,defer_merge=False):
    # 建立測試檔案
    test_file = tmp_path / "sample.txt"
    test_file.write_text("This is a test")
    ctx = LLMJobConfig()
    ctx.model_spec = {'base_url': 'http://192.168.0.134:11435/v1', 
                      #'model_name': 'qwen3:30b-a3b-32k',
                      'model_name': 'gpt-oss:latest-32k',
                      'api_key': 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpZCI6IjIyYzIzYWVkLWM4YzktNGZhYS1hNGRkLTg1NGNlZDg0YTE3ZCJ9.zP5xKqCemX2J3GFra03jMYPngipCbCUfFfIUyO96JOQ'
                      }
    ctx.task = "Summary-toTWZH"
    #ctx.task = "這是一個測試"
    des_filename = handle_txt_file.handle_single_input_file(str(test_file),ctx=ctx)
    return_message = open(des_filename,'rt').read()
    print("des_filename",des_filename)
    print("return_message",return_message)
    assert os.path.isfile(des_filename), "The destination file does not exist."
    assert "測試" in return_message, "The return message seems not be right."
    #assert False, "wrong"
    #assert "test" in result.lower(), "Processed text should contain 'test'"
