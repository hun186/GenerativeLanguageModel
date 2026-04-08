from czjLLM.prompt_pipeline.pipeline_controller import _compact_stage_key_for_output


def test_compact_stage_key_prefers_head_before_dash():
    assert _compact_stage_key_for_output("PDF OPT-Instruction First", "pdf_opt") == "PDF OPT"
    assert _compact_stage_key_for_output("Translation-toTWZH", "en_to_zh") == "Translation"
    assert _compact_stage_key_for_output("Summary-toTWZH", "summarize") == "Summary"


def test_compact_stage_key_fallbacks_to_stage_name_and_limits_length():
    assert _compact_stage_key_for_output("", "en_to_zh") == "en_to_zh"
    long_key = "A" * 80
    assert _compact_stage_key_for_output(long_key, "s") == ("A" * 32)
