"""Required-output rule identity and observation for future retry accounting.

Only the existing shared evaluator is invoked. This is not an output profile
attestation, provider result, retry authorization, or durable ledger update.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import re

from czjLLM.common.required_output_guard import evaluate_required_output_checks

# Bump whenever shared evaluator/validator semantics change. The digest
# identifies normalized configuration within this explicitly versioned contract.
_CONTRACT = "required-output-v1"
_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,511}\Z")
_VALIDATORS = {"non_empty", "date", "multidim_event_time"}
_DATE_FORMATS = {"yyyy-MM-dd", "iso8601", "strict_date_optional_time"}
_KEYS = {"path", "full_path", "relative_to_output", "validator", "format",
         "min_valid_count", "allow_empty_events"}


class RequiredOutputObservationUnavailable(ValueError):
    """Fixed diagnostic; never includes document contents or settings."""


@dataclass(frozen=True)
class RequiredOutputObservation:
    rule_version: str
    passed: bool


def _require(ok):
    if not ok:
        raise RequiredOutputObservationUnavailable("required output observation unavailable")


def observe_required_output(policy, source, output_col):
    """Observe only explicitly enabled, supported, output-local checks.

    Resolve paths through the actual adapter. Reject malformed/unsupported
    settings rather than treating the permissive legacy fallback as evidence.
    The same canonical snapshot drives both the digest and evaluation.
    """
    try:
        cfg = policy.cfg
        rr = cfg.get("rerun") or {}
        _require(type(source) is dict and type(output_col) is str
                 and _PATH.fullmatch(output_col))
        _require(rr.get("enable") is True
                 or cfg.get("required_output_checks_apply_without_rerun") is True)
        raw = rr.get("required_output_checks") or cfg.get("required_output_checks") or []
        _require(type(raw) is list and 0 < len(raw) <= 128)
        for item in raw:
            _require(type(item) is str or (type(item) is dict and
                     set(item) <= (_KEYS - {"full_path"})))
        resolved = policy._get_required_output_checks(output_col)
        _require(len(resolved) == len(raw))
        checks = []
        for item in resolved:
            path = item["full_path"]
            _require(type(path) is str and _PATH.fullmatch(path)
                     and (path == output_col or path.startswith(output_col + ".")))
            relative = item.get("relative_to_output", True)
            _require(type(relative) is bool)
            validator = item.get("validator") or "non_empty"
            _require(type(validator) is str and validator.lower() in _VALIDATORS)
            validator = validator.lower()
            fmt = item.get("format")
            if validator == "date":
                fmt = fmt or "yyyy-MM-dd"
                _require(type(fmt) is str and fmt in _DATE_FORMATS)
            else:
                _require(fmt is None)
            minimum = item.get("min_valid_count", 1)
            _require(type(minimum) is int and 1 <= minimum <= 100000)
            allow_empty = item.get("allow_empty_events", False)
            _require(type(allow_empty) is bool
                     and (not allow_empty or validator == "multidim_event_time"))
            checks.append({"full_path": path, "validator": validator,
                           "format": fmt, "min_valid_count": minimum,
                           "allow_empty_events": allow_empty})
        canonical = json.dumps([_CONTRACT, output_col, checks], ensure_ascii=True,
                               sort_keys=True, separators=(",", ":"), allow_nan=False)
        version = _CONTRACT + "-" + hashlib.sha256(canonical.encode("ascii")).hexdigest()
        passed, _ = evaluate_required_output_checks(source, checks)
        _require(type(passed) is bool)
        return RequiredOutputObservation(version, passed)
    except RequiredOutputObservationUnavailable:
        raise
    except Exception:
        raise RequiredOutputObservationUnavailable("required output observation unavailable") from None
