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
    assert "偵測到 ES 連線 Python 內的舊 rerun" in out
    assert "建議分工：config_es 連線 Python 只管理 ES" in out
    assert "每份任務 YAML 獨立管理 rerun" in out
    assert "跨任務意外重算" in out
    assert "docs/usage/es_connection_profile_examples.md" in out
    assert "[ES_RERUN_PY_INHERITED]" in out
    assert "force_since：可能重新挑出" in out
    assert "相容模式仍會合併舊值" in out
    assert "覆寫 key：pipeline_hash" in out
    assert "繼承 key：enable, force_since, required_output_checks" in out
    assert "- required_output_checks: list[1]" in out
    assert "pipeline_hash 已啟用" in out
    assert "來源：主 YAML rerun.pipeline_hash（覆寫 es_config_file.rerun.pipeline_hash）" in out
    assert "寫回 ES meta.pipeline_hash" in out
    assert "若值與既有 output meta 不一致" in out
    assert "既有 output 重新進入 pending" in out


def test_yaml_only_rerun_has_no_legacy_warning(capsys):
    rerun = {"enable": True, "required_output_checks": []}
    log_rerun_config(rerun, {
        "base_has_rerun": False,
        "yaml_has_rerun": True,
        "overridden_keys": [],
        "inherited_keys": [],
        "yaml_only_keys": ["enable", "required_output_checks"],
    })
    stdout = capsys.readouterr().out
    assert "來源：主 YAML rerun" in stdout
    assert "偵測到 ES 連線 Python 內的舊 rerun" not in stdout
    assert "建議分工：" not in stdout


def test_warning_when_all_rerun_rules_come_from_legacy_python(capsys):
    legacy = {
        "enable": True,
        "force_since": "2025-11-01T00:00:00Z",
        "pipeline_hash": "old-marker",
        "force_if_missing_meta": True,
        "required_output_checks": [{"path": "Event_Timeline.time_iso", "validator": "date"}],
    }
    effective, source = resolve_rerun_config(
        {"rerun": legacy}, lambda key, default=None: default)
    log_rerun_config(
        effective, source,
        es_config_file="czjLLM/config_es/akconfig_es_test.py",
    )
    out = capsys.readouterr().out
    assert "[ES_RERUN_LEGACY_PY]" in out
    assert "[ES_RERUN_PY_ONLY]" in out
    assert "建議分工：config_es 連線 Python 只管理 ES" in out
    assert "每份任務 YAML 獨立管理 rerun" in out
    assert "akconfig_es_test.py" in out
    assert "config_es/private/" in out
    assert "force_since：可能重新挑出" in out
    assert "pipeline_hash：不同／缺少版本標記" in out
    assert "force_if_missing_meta：缺 meta" in out
    assert "required_output_checks：可能仍使用舊 Timeline" in out
    assert "先將需要的 rerun 規則完整移至該任務 YAML" in out
    assert effective == legacy  # logging must not silently deactivate rerun


def test_partial_yaml_override_warns_only_effective_inherited_risks(capsys):
    legacy = {
        "enable": True, "force_since": "2025-11-01T00:00:00Z",
        "pipeline_hash": "private-legacy", "force_if_missing_meta": True,
    }
    yaml_policy = {"pipeline_hash": "yaml-selected", "force_if_missing_meta": False}
    effective, source = resolve_rerun_config(
        {"rerun": legacy},
        lambda key, default=None: yaml_policy if key == "rerun" else default,
    )
    log_rerun_config(effective, source, es_config_file="test_133.py")
    out = capsys.readouterr().out
    assert "[ES_RERUN_PY_INHERITED]" in out
    assert "從 Python 繼承：enable, force_since" in out
    assert "force_since：可能重新挑出" in out
    assert "繼承的重跑風險：pipeline_hash" not in out
    assert "繼承的重跑風險：force_if_missing_meta" not in out
    assert "private-legacy" not in out
    assert effective["pipeline_hash"] == "yaml-selected"
    assert effective["force_if_missing_meta"] is False


def test_full_yaml_override_of_legacy_python_warns_but_not_false_inheritance(capsys):
    legacy = {"enable": True, "force_since": "old"}
    yaml_policy = {"enable": False, "force_since": None}
    effective, source = resolve_rerun_config(
        {"rerun": legacy},
        lambda key, default=None: yaml_policy if key == "rerun" else default,
    )
    log_rerun_config(effective, source, es_config_file="legacy.py")
    out = capsys.readouterr().out
    assert "[ES_RERUN_LEGACY_PY]" in out
    assert "[ES_RERUN_PY_SHADOWED]" in out
    assert "[ES_RERUN_PY_INHERITED]" not in out
    assert "繼承的重跑風險" not in out
    assert effective == yaml_policy


def test_yaml_only_does_not_emit_legacy_warning(capsys):
    yaml_policy = {"enable": True, "required_output_checks": []}
    effective, source = resolve_rerun_config(
        {}, lambda key, default=None: yaml_policy if key == "rerun" else default)
    log_rerun_config(effective, source, es_config_file="shared_es.py")
    out = capsys.readouterr().out
    assert "[ES_RERUN_LEGACY_PY]" not in out
    assert "[ES_RERUN_PY_ONLY]" not in out
    assert "[ES_RERUN_PY_INHERITED]" not in out
    assert effective == yaml_policy


def test_legacy_rerun_file_name_diagnostic_handles_windows_paths_safely(capsys):
    effective, source = resolve_rerun_config(
        {"rerun": {"enable": True}},
        lambda key, default=None: default,
    )
    log_rerun_config(
        effective, source,
        es_config_file=r"D:\\work\\config_es\\akconfig_es_test.py",
    )
    out = capsys.readouterr().out
    assert "YAML 的 es_config_file 指向：akconfig_es_test.py" in out
    assert "D:\\work" not in out
