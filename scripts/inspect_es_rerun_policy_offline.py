#!/usr/bin/env python3
"""Offline, read-only static preview of ES rerun configuration.

Never execute the operator-private connection Python or connect to ES/LLM.
Only literal top-level rerun dictionaries can be previewed. All output is
fixed-code metadata; source payloads, setting values and file paths stay local.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
from pathlib import Path
import stat
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from czjLLM.es_mode.config.rerun_logging import resolve_rerun_config

MAX_CONFIG_BYTES = 256 * 1024
_KNOWN_KEYS = frozenset({
    "enable", "pipeline_hash", "force_since", "force_if_missing_meta",
    "required_output_checks", "stale_after_days", "model_tag",
    "execution_fingerprint", "fallback_date_field",
})


def _file_identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns


def _read_stable(path: Path) -> str:
    """Best-effort stable local file snapshot; no filenames in exceptions."""
    if not path.is_absolute() or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("UNVERIFIED_PATH")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= MAX_CONFIG_BYTES:
        raise ValueError("UNVERIFIED_FILE")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_BINARY", 0)
    fd = os.open(path, flags)
    with os.fdopen(fd, "rb") as handle:
        first = os.fstat(handle.fileno())
        if not stat.S_ISREG(first.st_mode) or _file_identity(first) != _file_identity(before):
            raise ValueError("CHANGED")
        raw = handle.read(MAX_CONFIG_BYTES + 1)
        last = os.fstat(handle.fileno())
    after = path.lstat()
    if (len(raw) != before.st_size or len(raw) > MAX_CONFIG_BYTES
            or _file_identity(before) != _file_identity(last)
            or _file_identity(before) != _file_identity(after)):
        raise ValueError("CHANGED")
    return raw.decode("utf-8-sig")


def _load_yaml(text: str):
    import yaml

    class RejectDuplicateLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node):
        pairs = {}
        for knode, vnode in node.value:
            key = loader.construct_object(knode, deep=True)
            if not isinstance(key, str) or key in pairs:
                raise ValueError("NON_UNIQUE_YAML_KEY")
            pairs[key] = loader.construct_object(vnode, deep=True)
        return pairs

    RejectDuplicateLoader.add_constructor(
        yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping
    )
    data = yaml.load(text, Loader=RejectDuplicateLoader)
    if not isinstance(data, dict) or data.get("mode") != "es":
        raise ValueError("NOT_ES_TASK")
    if "rerun" in data and not isinstance(data["rerun"], dict):
        raise ValueError("UNVERIFIED_RERUN")
    return data


def _literal_python_rerun(text: str) -> dict:
    tree = ast.parse(text)
    # Reject all non-top-level or multiple assignments, and imports of rerun.
    stores = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "rerun"
        and isinstance(node.ctx, ast.Store)
    ]
    imports = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
        if (alias.asname or alias.name.split(".")[0]) == "rerun"
    ]
    dynamic = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"exec", "eval", "globals", "locals", "setattr"}
    ]
    references = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id == "rerun"
    ]
    # A .update(), subscript mutation or read outside the literal assignment
    # means the eventual runtime value cannot be established by static AST.
    if imports or dynamic or len(stores) > 1 or len(references) != len(stores):
        raise ValueError("UNVERIFIABLE_PYTHON")
    if not stores:
        return {}
    eligible = []
    for node in tree.body:
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "rerun"):
            eligible.append(node.value)
        elif (isinstance(node, ast.AnnAssign)
              and isinstance(node.target, ast.Name) and node.target.id == "rerun"):
            eligible.append(node.value)
    if len(eligible) != 1 or len(stores) != 1 or eligible[0] is None:
        raise ValueError("UNVERIFIABLE_PYTHON")
    value = ast.literal_eval(eligible[0])
    if not isinstance(value, dict) or any(not isinstance(k, str) for k in value):
        raise ValueError("UNVERIFIABLE_PYTHON")
    return value


def inspect(task_yaml: Path, connection_py: Path) -> dict:
    """Static snapshot only; never a production permission or factual rerun count."""
    try:
        yaml_cfg = _load_yaml(_read_stable(task_yaml))
        ref = yaml_cfg.get("es_config_file")
        if (not isinstance(ref, str) or not ref.strip()
                or ref.replace("\\", "/").rsplit("/", 1)[-1] != connection_py.name):
            raise ValueError("CONNECTION_NOT_MATCHED")
        py_rerun = _literal_python_rerun(_read_stable(connection_py))
        effective, diag = resolve_rerun_config(
            {"rerun": py_rerun},
            lambda key, default=None: yaml_cfg.get(key, default),
        )
        if not isinstance(effective, dict):
            raise ValueError("UNVERIFIABLE_POLICY")
        codes = set()
        if py_rerun:
            codes.add("LEGACY_PY_RERUN_PRESENT")
        if diag["inherited_keys"]:
            codes.add("INHERITED_PY_RERUN_KEYS")
        if effective.get("enable") is not True:
            codes.add("RERUN_NOT_EXPLICITLY_ENABLED")
        else:
            for key, code in (
                ("force_since", "FORCE_SINCE_ACTIVE"),
                ("pipeline_hash", "PIPELINE_HASH_ACTIVE"),
                ("force_if_missing_meta", "MISSING_META_FORCES_RERUN"),
                ("stale_after_days", "STALE_POLICY_ACTIVE"),
                ("model_tag", "MODEL_TAG_POLICY_ACTIVE"),
                ("execution_fingerprint", "FINGERPRINT_POLICY_ACTIVE"),
            ):
                if effective.get(key):
                    codes.add(code)
            checks = effective.get("required_output_checks")
            if checks is not None:
                if not isinstance(checks, list):
                    raise ValueError("UNVERIFIABLE_CHECKS")
                for check in checks:
                    if not isinstance(check, dict):
                        raise ValueError("UNVERIFIABLE_CHECKS")
                    candidate = check.get("path")
                    if not isinstance(candidate, str):
                        raise ValueError("UNVERIFIABLE_CHECKS")
                    if "Event_Timeline.time_iso" in candidate:
                        codes.add("TIMELINE_DATE_MINIMUM_PRESENT")
                    if check.get("validator") == "multidim_event_time":
                        codes.add("EVENT_FIRST_VALIDATOR_CONFIGURED")
        if any(k not in _KNOWN_KEYS for k in effective):
            codes.add("OTHER_POLICY_KEYS_REVIEW_REQUIRED")
        return {
            "schema_version": 1, "status": "STATIC_PREVIEW_REVIEW_REQUIRED",
            "reason_codes": sorted(codes),
            "legacy_python_present": bool(py_rerun),
            "inherited_known_key_count": sum(k in _KNOWN_KEYS for k in diag["inherited_keys"]),
            "inherited_unknown_key_count": sum(k not in _KNOWN_KEYS for k in diag["inherited_keys"]),
            "source_date_fidelity": "NOT_VERIFIED",
            "stored_es_outputs": "NOT_READ",
            "runtime_policy": "NOT_VERIFIED",
            "execution": "READ_ONLY_NO_PY_EXEC_NO_ES_NO_LLM_NO_REPLAY",
            "production_authorization": "NOT_GRANTED",
        }
    except Exception:
        # Including YAML parser errors: never emit raw exception text, input
        # payloads, credentials, paths or partial/optimistic assessment.
        return {
            "schema_version": 1, "status": "UNAVAILABLE",
            "reason_codes": ["STATIC_INPUT_UNVERIFIED"],
            "execution": "READ_ONLY_NO_PY_EXEC_NO_ES_NO_LLM_NO_REPLAY",
            "production_authorization": "NOT_GRANTED",
        }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Review one ES YAML and corresponding private Python without executing either."
    )
    parser.add_argument("--task-yaml", type=Path, required=True)
    parser.add_argument("--connection-py", type=Path, required=True)
    args = parser.parse_args(argv)
    result = inspect(args.task_yaml, args.connection_py)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "STATIC_PREVIEW_REVIEW_REQUIRED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
