from czjLLM.es_mode.config.stage_cfg import build_es_stage_cfg, stage_name_from_cfg


def _getter(data):
    return lambda key, default=None: data.get(key, default)


def test_build_es_stage_cfg_returns_empty_without_stage_keys():
    cfg = build_es_stage_cfg(_getter({}), {})

    assert cfg == {}
    assert stage_name_from_cfg(cfg) is None


def test_build_es_stage_cfg_accepts_top_level_stage_cfg_block():
    cfg = build_es_stage_cfg(
        _getter(
            {
                "stage_cfg": {
                    "enabled": True,
                    "name": "es_json_multistage_langroute",
                    "version": "v1",
                    "router": {"name": "language_route", "route_field": "route"},
                    "routes": {"zh": {"stages": [{"name": "extract_zh"}]}},
                }
            }
        ),
        {},
    )

    assert cfg["enabled"] is True
    assert cfg["name"] == "es_json_multistage_langroute"
    assert cfg["version"] == "v1"
    assert cfg["router"]["route_field"] == "route"
    assert cfg["routes"]["zh"]["stages"][0]["name"] == "extract_zh"


def test_build_es_stage_cfg_merges_route_keys():
    cfg = build_es_stage_cfg(
        _getter(
            {
                "pipeline_name": "legacy_langroute",
                "stages": [{"name": "route"}],
                "routes": {"fallback": {"stages": []}},
            }
        ),
        {"pipeline_version": "from_es_cfg"},
    )

    assert cfg["enabled"] is True
    assert cfg["name"] == "legacy_langroute"
    assert cfg["version"] == "from_es_cfg"
    assert cfg["stages"][0]["name"] == "route"


def test_build_es_stage_cfg_accepts_steps_alias():
    cfg = build_es_stage_cfg(
        _getter(
            {
                "pipeline_name": "doc_type_aware_extraction",
                "steps": ["chunk_summary", "doc_type_classification"],
            }
        ),
        {},
    )

    assert cfg["enabled"] is True
    assert cfg["name"] == "doc_type_aware_extraction"
    assert cfg["stages"] == ["chunk_summary", "doc_type_classification"]


def test_build_es_stage_cfg_accepts_plain_stage_list():
    cfg = build_es_stage_cfg(_getter({"stage_cfg": ["stage_a", "stage_b"]}), {})

    assert cfg["enabled"] is True
    assert cfg["stages"] == ["stage_a", "stage_b"]


def test_collect_stage_es_bindings_reads_route_stage_index_mapping_options():
    from czjLLM.es_mode.config.stage_cfg import collect_stage_es_bindings

    cfg = build_es_stage_cfg(
        _getter(
            {
                "stage_cfg": {
                    "router": {
                        "name": "route_lang",
                        "output_col": "route_lang_json",
                        "write_output": False,
                        "es": {"tgt_index": "routing-index", "mapping_file": "route.yaml"},
                    },
                    "routes": {
                        "zh": {
                            "stages": [
                                {
                                    "name": "extract_zh",
                                    "input": "rawInfo.content",
                                    "output_col": "zh_result_json",
                                    "output_profile": "json",
                                    "es": {
                                        "src_index": "zh-source",
                                        "tgt_index": "zh-result",
                                        "mapping_file": "zh.yaml",
                                    },
                                }
                            ]
                        }
                    },
                }
            }
        ),
        {},
    )

    bindings = collect_stage_es_bindings(cfg, default_src_index="default-source", default_tgt_index="default-result")

    assert bindings[0]["role"] == "router"
    assert bindings[0]["stage_name"] == "route_lang"
    assert bindings[0]["src_index"] == "default-source"
    assert bindings[0]["tgt_index"] == "routing-index"
    assert bindings[0]["mapping_file"] == "route.yaml"
    assert bindings[0]["write_output"] is False
    assert bindings[1]["route"] == "zh"
    assert bindings[1]["stage_name"] == "extract_zh"
    assert bindings[1]["input_col"] == "rawInfo.content"
    assert bindings[1]["src_index"] == "zh-source"
    assert bindings[1]["tgt_index"] == "zh-result"
    assert bindings[1]["mapping_file"] == "zh.yaml"


def test_collect_stage_es_bindings_reads_route_map_execution_options():
    from czjLLM.es_mode.config.stage_cfg import collect_stage_es_bindings

    cfg = build_es_stage_cfg(
        _getter(
            {
                "stage_cfg": {
                    "stages": [
                        {
                            "name": "extract",
                            "route_by": "route",
                            "route_value_mode": "task",
                            "retry_source_on_route_miss": True,
                            "write_output": True,
                            "max_attempts": 2,
                            "debug_print_llm_io": True,
                            "debug_print_max_chars": -1,
                            "route_map": {
                                "zh": {
                                    "task": "@taskSetting:InfoExtraction-MultiDim-SQLFriendly-to json format",
                                    "input_from": "original",
                                    "input_col": "rawInfo.content",
                                    "output_col": "multidim_event_json",
                                    "output_profile": "multidim_event",
                                    "es": {"tgt_index": "zh-result", "mapping_file": "multi.yaml"},
                                },
                                "non_zh": {
                                    "task": "return skip json",
                                    "input_from": "none",
                                    "output_col": "llm_result_json",
                                    "output_profile": "json",
                                },
                            },
                        }
                    ]
                }
            }
        ),
        {},
    )

    bindings = collect_stage_es_bindings(cfg, default_src_index="source", default_tgt_index="default-result")

    zh_binding = next(b for b in bindings if b.get("route") == "zh")
    assert zh_binding["role"] == "route_map"
    assert zh_binding["stage_name"] == "extract:zh"
    assert zh_binding["task"] == "@taskSetting:InfoExtraction-MultiDim-SQLFriendly-to json format"
    assert zh_binding["input_from"] == "original"
    assert zh_binding["input_col"] == "rawInfo.content"
    assert zh_binding["route_by"] == "route"
    assert zh_binding["route_value_mode"] == "task"
    assert zh_binding["retry_source_on_route_miss"] is True
    assert zh_binding["max_attempts"] == 2
    assert zh_binding["debug_print_llm_io"] is True
    assert zh_binding["debug_print_max_chars"] == -1
    assert zh_binding["write_output"] is True
    assert zh_binding["tgt_index"] == "zh-result"
    assert zh_binding["mapping_file"] == "multi.yaml"

    non_zh_binding = next(b for b in bindings if b.get("route") == "non_zh")
    assert non_zh_binding["input_from"] == "none"
    assert non_zh_binding["output_col"] == "llm_result_json"
    assert non_zh_binding["output_profile"] == "json"
