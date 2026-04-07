from czjLLM.task_configs.taskConfig_ANKInt import taskSetting_ANKInt


def test_pdf_opt_instruction_first_interpolates_main_file_name():
    tpl = taskSetting_ANKInt["PDF OPT-Instruction First"]["template"]
    out = tpl(MainFileName="demo_file", content="sample content")
    assert "主檔名為「demo_file」" in out
    assert "{MainFileName}" not in out
