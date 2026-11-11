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


def log_rerun_config(
    rerun_cfg: Dict[str, Any],
    diagnostics: Dict[str, Any],
    *,
    es_config_file: str | None = None,
) -> None:
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

    if diagnostics.get("base_has_rerun"):
        # Warn only. Never change how old private Python and task YAML merge.
        # Do not print connection credentials or arbitrary setting values.
        print("⚠️  [ES_RERUN_LEGACY_PY] 偵測到 ES 連線 Python 內的舊 rerun。")
        print("  - 建議分工：config_es 連線 Python 只管理 ES host/認證/TLS/index/基本 I/O；")
        print("              每份任務 YAML 獨立管理 rerun、重跑時間窗、版本及輸出品質檢查。")
        print("  - 原因：同一連線 .py 可能被多份 YAML 共用，舊 rerun 易造成跨任務意外重算。")
        print("  - 遷移指南：docs/usage/es_connection_profile_examples.md")
        if isinstance(es_config_file, str) and es_config_file.strip():
            # File name is enough to locate the setting; avoid multiline
            # injection and dumping a private path with user-specific parts.
            from pathlib import PurePath
            name = PurePath(es_config_file.replace(chr(92), "/")).name
            if name:
                print(f"  - YAML 的 es_config_file 指向：{name}")
                print("  - 注意：實際載入可能是 config_es/private/ 下的同名檔。")
        if not diagnostics.get("yaml_has_rerun"):
            print("⚠️  [ES_RERUN_PY_ONLY] 任務 YAML 未設定 rerun，全部沿用連線 Python 的舊政策。")
        elif inherited:
            print("⚠️  [ES_RERUN_PY_INHERITED] YAML 只有部分覆寫，仍繼承 Python 的 rerun keys。")
            print(f"  - 從 Python 繼承：{', '.join(inherited)}")
        else:
            print("  - [ES_RERUN_PY_SHADOWED] 此任務的 Python rerun keys 已全部被 YAML 覆寫。")
            print("  - 目前沒有 Python key 被繼承，但共用檔仍應日後整理。")

        effective_inherited = set(inherited)
        if rerun_cfg.get("enable"):
            risks = {
                "force_since": "force_since：可能重新挑出較早處理的文件",
                "pipeline_hash": "pipeline_hash：不同／缺少版本標記的文件可能重新處理",
                "force_if_missing_meta": "force_if_missing_meta：缺 meta 的舊輸出可能重新處理",
                "required_output_checks": "required_output_checks：可能仍使用舊 Timeline 必填條件",
                "stale_after_days": "stale_after_days：較早輸出的文件可能重新處理",
                "model_tag": "model_tag：模型標籤不符的文件可能重新處理",
                "execution_fingerprint": "execution_fingerprint：執行身分不符可能重新處理",
            }
            for key, meaning in risks.items():
                if key in effective_inherited and rerun_cfg.get(key):
                    print(f"  - ⚠️  繼承的重跑風險：{meaning}")
        if inherited:
            print("  - 修正：先將需要的 rerun 規則完整移至該任務 YAML，")
            print("          再從對應私人連線 .py 移除 rerun = {...}。")
        else:
            print("  - 修正：其他共用任務可能仍受影響，日後檢查私人連線 .py。")
        print("  - 相容模式仍會合併舊值；此警告不代表設定已停用。")
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
