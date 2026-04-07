from czjLLM.task_configs.taskConfig_ANKInt import taskSetting_ANKInt
from czjLLM.job_manager.job_config import task_template_preview
from collections import UserDict


def test_pdf_opt_instruction_first_interpolates_main_file_name():
    tpl = taskSetting_ANKInt["PDF OPT-Instruction First"]["template"]
    out = tpl(MainFileName="demo_file", content="sample content")
    assert "主檔名為「demo_file」" in out
    assert "{MainFileName}" not in out


def test_task_template_preview_supports_task_key_and_task_spec():
    key_preview = task_template_preview("PDF OPT-Instruction First")
    dict_preview = task_template_preview(taskSetting_ANKInt["PDF OPT-Instruction First"])
    assert "MainFileName" in key_preview
    assert "MainFileName" in dict_preview


def test_task_template_preview_supports_mapping_type():
    spec = UserDict(taskSetting_ANKInt["PDF OPT-Instruction First"])
    preview = task_template_preview(spec)
    assert "MainFileName" in preview or "template" in preview
