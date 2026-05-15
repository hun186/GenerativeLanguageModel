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


def test_multidim_template_contains_aggregate_event_guardrails():
    from czjLLM.task_configs.taskSetting_Enrichment import taskSetting_Enrichment

    tpl = taskSetting_Enrichment["InfoExtraction-MultiDim-SQLFriendly-to json format"]["template"]
    out = tpl(content="查詢綜整結果：東亞區域安全／海空活動／國際回應\n整理時間：2026-03-13 14:20")

    assert "同一主題綜整事件：原則上只輸出 1 個事件物件" in out
    assert "不得把每一句或每一條拆成多個頂層事件物件" in out
    assert "Event.consequence` 必須是整體後果 / 風險 / 影響" in out
    assert "航空自衛隊緊急升空應對" in out
    assert "不得覆蓋事件發生時間" in out
    assert "evidence_snippets 必須保留檢索可用性" in out
    assert "聚合事件只改變頂層事件物件數量" in out


def test_multidim_task_uses_larger_chunk_for_multistage_context():
    from czjLLM.task_configs.taskSetting_Enrichment import taskSetting_Enrichment

    cfg = taskSetting_Enrichment["InfoExtraction-MultiDim-SQLFriendly-to json format"]

    assert cfg["InputCutLen"] >= 1200


def test_multidim_template_allows_multi_topic_hot_news_lists():
    from czjLLM.task_configs.taskSetting_Enrichment import taskSetting_Enrichment

    tpl = taskSetting_Enrichment["InfoExtraction-MultiDim-SQLFriendly-to json format"]["template"]
    out = tpl(content="十大熱點新聞：1. 國際軍事；2. 科技公司財報；3. 颱風災情")

    assert "十大熱點新聞" in out
    assert "每則獨立新聞各輸出 1 個事件物件" in out
    assert "最多輸出 10 個事件物件" in out
    assert "每個事件物件只收自己的 evidence_snippets 與 Event.consequence" in out
