from pathlib import Path

import pytest

from utils_manager.utils_sync import PathContext, resolve_config_path


def _ctx(tmp_path: Path) -> PathContext:
    project_root = tmp_path / "TopicClassification"
    app_root = project_root / "GenerativeLanguageModel"
    caller_dir = app_root / "czjLLM"
    caller_dir.mkdir(parents=True)
    return PathContext(
        project_root=project_root,
        app_root=app_root,
        caller_dir=caller_dir,
        rel_to_root=Path("GenerativeLanguageModel/czjLLM"),
        rel_to_app=Path("czjLLM"),
    )


def test_resolve_config_path_finds_app_yaml_for_bare_filename(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    config_path = ctx.app_root / "yaml" / "sqlserver_json_singlestage_in_multistage.yaml"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text("name: sqlserver\n", encoding="utf-8")
    monkeypatch.chdir(ctx.app_root)

    resolved = resolve_config_path("sqlserver_json_singlestage_in_multistage.yaml", ctx)

    assert resolved == config_path


def test_resolve_config_path_keeps_input_path_before_yaml_fallback(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    direct_path = ctx.app_root / "config.yaml"
    yaml_path = ctx.app_root / "yaml" / "config.yaml"
    direct_path.write_text("source: direct\n", encoding="utf-8")
    yaml_path.parent.mkdir(parents=True, exist_ok=True)
    yaml_path.write_text("source: yaml\n", encoding="utf-8")
    monkeypatch.chdir(ctx.app_root)

    resolved = resolve_config_path("config.yaml", ctx)

    assert resolved == direct_path


def test_resolve_config_path_error_lists_yaml_fallback_without_duplicates(tmp_path, monkeypatch):
    ctx = _ctx(tmp_path)
    monkeypatch.chdir(ctx.app_root)

    with pytest.raises(FileNotFoundError) as exc_info:
        resolve_config_path("missing.yaml", ctx)

    message = str(exc_info.value)
    assert str(ctx.app_root / "yaml" / "missing.yaml") in message
    tried = message.split("已嘗試：\n", 1)[1].splitlines()
    assert len(tried) == len(set(tried))
