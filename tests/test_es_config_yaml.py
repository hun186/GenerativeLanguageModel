from pathlib import Path


def test_default_es_config_documents_legacy_event_profile_auto():
    text = Path("czjLLM/yaml/es_config.yaml").read_text(encoding="utf-8")

    assert "output_col: multidim_event_json" in text
    assert "output_profile: auto" in text
    assert "有效行為會推斷為 multidim_event" in text
    assert "stage_cfg:" in text
    assert "enabled: false" in text


def test_multistage_langroute_example_documents_current_single_stage_runtime():
    text = Path("czjLLM/yaml/es_json_multistage_langroute_config.yaml").read_text(encoding="utf-8")

    assert "尚未真正執行 router/routes" in text
    assert "實際執行仍使用下方 task/output_col/output_profile" in text
    assert "task: InfoExtraction-MultiDim-SQLFriendly-to json format" in text
    assert "output_col: multidim_event_json" in text
    assert "stage_cfg:" in text
