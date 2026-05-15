from pathlib import Path


def test_default_es_config_documents_legacy_event_profile_auto():
    text = Path("czjLLM/yaml/es_config.yaml").read_text(encoding="utf-8")

    assert "output_col: multidim_event_json" in text
    assert "output_profile: auto" in text
    assert "有效行為會推斷為 multidim_event" in text
    assert "stage_cfg:" in text
    assert "enabled: false" in text


def test_multistage_langroute_example_documents_stage_runtime_and_writeback():
    text = Path("czjLLM/yaml/es_json_multistage_langroute_config.yaml").read_text(encoding="utf-8")

    assert "這份檔案會實際執行 route -> extract -> audit_json" in text
    assert 'task: "@taskSetting:InfoExtraction-MultiDim-SQLFriendly-to json format"' in text
    assert "input_from: none" in text
    assert "max_attempts: 3" in text
    assert "debug_print_llm_io: true" in text
    assert "route_value_mode: task" in text
    assert "output_col: multidim_event_json" in text
    assert "source: stage" in text
    assert "stage: extract" in text
    assert "stage: audit_json" in text
    assert "output_profile: multidim_event" in text
    assert "mapping_file: czjLLM/config_es/schemas/generic-json-mapping.yaml" in text
    assert "stage_cfg:" in text
    assert "merge_slices: true" in text
