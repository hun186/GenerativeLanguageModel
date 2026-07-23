from czjLLM.es_mode.config.rerun_logging import log_rerun_config, resolve_rerun_config


def test_resolve_rerun_config_reports_yaml_overrides_and_inherited_keys():
    es_cfg = {
        "rerun": {
            "enable": True,
            "force_since": "2025-11-01T00:00:00Z",
            "pipeline_hash": "v3.2.1",
        }
    }

    def get_param(key, default=None):
        if key == "rerun":
            return {
                "pipeline_hash": "v3.2.2",
                "force_if_missing_meta": True,
            }
        return default

    rerun_cfg, diagnostics = resolve_rerun_config(es_cfg, get_param)

    assert rerun_cfg == {
        "enable": True,
        "force_since": "2025-11-01T00:00:00Z",
        "pipeline_hash": "v3.2.2",
        "force_if_missing_meta": True,
    }
    assert diagnostics["overridden_keys"] == ["pipeline_hash"]
    assert diagnostics["inherited_keys"] == ["enable", "force_since"]
    assert diagnostics["yaml_only_keys"] == ["force_if_missing_meta"]


def test_log_rerun_config_warns_about_source_and_effective_settings(capsys):
    rerun_cfg = {
        "enable": True,
        "force_since": "2025-11-01T00:00:00Z",
        "pipeline_hash": "v3.2.2",
        "required_output_checks": [{"path": "Event_Timeline.date_iso"}],
    }
    diagnostics = {
        "base_has_rerun": True,
        "yaml_has_rerun": True,
        "overridden_keys": ["pipeline_hash"],
        "inherited_keys": ["enable", "force_since", "required_output_checks"],
        "yaml_only_keys": [],
    }

    log_rerun_config(rerun_cfg, diagnostics)

    out = capsys.readouterr().out
    assert "ES rerun 設定會影響 pending / 重跑判斷" in out
    assert "來源：es_config_file.rerun + 主 YAML rerun" in out
    assert "覆寫 key：pipeline_hash" in out
    assert "繼承 key：enable, force_since, required_output_checks" in out
    assert "- required_output_checks: list[1]" in out
    assert "pipeline_hash 已啟用" in out
    assert "來源：主 YAML rerun.pipeline_hash（覆寫 es_config_file.rerun.pipeline_hash）" in out
    assert "寫回 ES meta.pipeline_hash" in out
    assert "若值與既有 output meta 不一致" in out
    assert "既有 output 重新進入 pending" in out
