"""Diagnostics for ES rerun configuration merging."""

from typing import Any, Dict, Tuple


def summarize_rerun_value(value: Any) -> str:
    if isinstance(value, list):
        return f"list[{len(value)}]"
    if isinstance(value, dict):
        return f"dict[{len(value)}]"
    return repr(value)


def resolve_rerun_config(es_cfg: Dict[str, Any], get_param) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Merge ES config and YAML rerun settings, returning diagnostics metadata."""
    base_rerun = es_cfg.get("rerun", {}) or {}
    yaml_rerun = get_param("rerun", None)
    yaml_has_rerun = isinstance(yaml_rerun, dict)

    if yaml_has_rerun:
        rerun_cfg = {**base_rerun, **yaml_rerun}
    else:
        yaml_rerun = {}
        rerun_cfg = base_rerun

    base_keys = set(base_rerun.keys()) if isinstance(base_rerun, dict) else set()
    yaml_keys = set(yaml_rerun.keys()) if isinstance(yaml_rerun, dict) else set()
    overridden_keys = sorted(base_keys & yaml_keys)
    inherited_keys = sorted(base_keys - yaml_keys) if yaml_has_rerun else sorted(base_keys)
    yaml_only_keys = sorted(yaml_keys - base_keys)

    diagnostics = {
        "base_has_rerun": bool(base_keys),
        "yaml_has_rerun": yaml_has_rerun,
        "overridden_keys": overridden_keys,
        "inherited_keys": inherited_keys,
        "yaml_only_keys": yaml_only_keys,
    }
    return rerun_cfg, diagnostics


def _pipeline_hash_source(diagnostics: Dict[str, Any]) -> str:
    overridden = diagnostics.get("overridden_keys") or []
    inherited = diagnostics.get("inherited_keys") or []
    yaml_only = diagnostics.get("yaml_only_keys") or []

    if "pipeline_hash" in overridden:
        return "主 YAML rerun.pipeline_hash（覆寫 es_config_file.rerun.pipeline_hash）"
    if "pipeline_hash" in yaml_only:
        return "主 YAML rerun.pipeline_hash"
    if "pipeline_hash" in inherited or diagnostics.get("base_has_rerun"):
        return "es_config_file.rerun.pipeline_hash"
    return "未知來源"


def log_rerun_config(rerun_cfg: Dict[str, Any], diagnostics: Dict[str, Any]) -> None:
    if not rerun_cfg and not diagnostics.get("base_has_rerun") and not diagnostics.get("yaml_has_rerun"):
        return

    print("\n" + "=" * 72)
    print("⚠️  ES rerun 設定會影響 pending / 重跑判斷")

    if diagnostics.get("base_has_rerun") and diagnostics.get("yaml_has_rerun"):
        print("來源：es_config_file.rerun + 主 YAML rerun（主 YAML 同名 key 會覆寫 es_config_file）")
    elif diagnostics.get("yaml_has_rerun"):
        print("來源：主 YAML rerun")
    elif diagnostics.get("base_has_rerun"):
        print("來源：es_config_file.rerun（主 YAML 未設定 rerun，將完整繼承）")

    overridden = diagnostics.get("overridden_keys") or []
    inherited = diagnostics.get("inherited_keys") or []
    yaml_only = diagnostics.get("yaml_only_keys") or []
    if overridden:
        print(f"覆寫 key：{', '.join(overridden)}")
    if inherited:
        print(f"繼承 key：{', '.join(inherited)}")
    if yaml_only:
        print(f"僅主 YAML key：{', '.join(yaml_only)}")

    if rerun_cfg:
        print("生效 rerun 摘要：")
        for key in sorted(rerun_cfg.keys()):
            print(f"  - {key}: {summarize_rerun_value(rerun_cfg[key])}")

    if rerun_cfg.get("pipeline_hash"):
        source = _pipeline_hash_source(diagnostics)
        print("⚠️  pipeline_hash 已啟用：")
        print(f"  - 來源：{source}")
        print(f"  - 生效值：{summarize_rerun_value(rerun_cfg.get('pipeline_hash'))}")
        print("  - 作用：寫回 ES meta.pipeline_hash，並在 pending / fresh 檢查時比對既有 output 的 hash。")
        print("  - 風險：若值與既有 output meta 不一致，該文件會被視為需重跑；請只在 pipeline/prompt/輸出契約變更或刻意重跑時調整。")

    if rerun_cfg.get("enable"):
        print("提示：enable=true 時，缺 meta、pipeline_hash 不合、force_since、required_output_checks 等都可能讓既有 output 重新進入 pending。")
    print("=" * 72 + "\n")
