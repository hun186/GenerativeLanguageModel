"""Platform-neutral numeric Audit distributions; no GUI or model dependency."""
import csv
import io
import math
import os
import stat
from pathlib import Path

MAX_AUDIT_BYTES = 8 * 1024 * 1024
MAX_AUDIT_ROWS = 20000

_AUDIT_SERIES = (
    ("input_tokens", "Input tokens", False),
    ("output_tokens", "Output tokens", False),
    ("template_tokens", "Template tokens", False),
    ("task_text_tokens", "Task text tokens", False),
    ("context_usage_ratio", "Context usage", True),
    ("elapsed_seconds", "Slice time", False),
    ("total_tok_per_s", "Total tok/s", False),
    ("effective_tok_per_s_est", "Effective tok/s (est.)", False),
)


def _audit_float(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        parsed = float(value)
        return parsed if math.isfinite(parsed) else None
    except Exception:
        return None


def _audit_token_count(value):
    """Parse exact nonnegative integer CSV counts; do not round floats."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not (1 <= len(value) <= 19 and value.isascii() and value.isdigit()):
        return None
    count = int(value)
    return count if count <= 2**63 - 1 else None


def _audit_percentile(values, q: float) -> float:
    ordered = sorted(float(v) for v in values)
    if not ordered:
        return 0.0
    if len(ordered) == 1:
        return ordered[0]
    pos = min(max(float(q), 0.0), 1.0) * (len(ordered) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1.0 - weight) + ordered[hi] * weight


def _audit_metric_snapshot(values, bins: int = 24) -> dict:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not vals:
        return {
            "count": 0, "min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0,
            "mean": 0.0, "histogram": (),
        }
    lo, hi = min(vals), max(vals)
    bucket_count = max(1, int(bins))
    counts = [0] * bucket_count
    if hi <= lo:
        counts[0] = len(vals)
    else:
        span = hi - lo
        for value in vals:
            idx = min(bucket_count - 1, int(((value - lo) / span) * bucket_count))
            counts[idx] += 1
    return {
        "count": len(vals),
        "min": lo,
        "p50": _audit_percentile(vals, 0.50),
        "p95": _audit_percentile(vals, 0.95),
        "max": hi,
        "mean": sum(vals) / len(vals),
        "histogram": tuple(counts),
    }


def load_llm_audit_distribution(audit_path: str, *, strict=False) -> dict:
    """Read the append-only numeric audit metadata; never read prompt/output payloads."""
    values = {name: [] for name, _, _ in _AUDIT_SERIES}
    calls = failures = component_rows = 0
    provider_rows = heuristic_rows = 0
    cache_eligible_rows = cache_observed_rows = 0
    cache_observed_input = cache_observed_cached = 0
    prior_templates = {}
    if audit_path:
        try:
            with (_strict_audit_snapshot(audit_path) if strict else
                  open(audit_path, "r", newline="", encoding="utf-8")) as fp:
                reader = csv.DictReader(fp, strict=strict)
                if strict and (not reader.fieldnames or len(set(reader.fieldnames)) != len(reader.fieldnames)
                               or not {"ok", "prompt_file", "token_usage_source"}.issubset(reader.fieldnames)):
                    raise ValueError("invalid audit schema")
                for row in reader:
                    if strict and (calls >= MAX_AUDIT_ROWS or None in row or any(v is None for v in row.values())):
                        raise ValueError("audit rows incomplete or over budget")
                    if not isinstance(row, dict):
                        continue
                    calls += 1
                    if str(row.get("ok", "")).strip().upper() == "NO":
                        failures += 1
                    usage_source = str(row.get("token_usage_source", "") or "").strip().lower()
                    has_api_usage = usage_source in {"", "llm_api_usage"}
                    is_slice = bool(str(row.get("prompt_file", "") or "").strip())
                    has_components = False
                    for name, _, as_percent in _AUDIT_SERIES:
                        if name in {"total_tok_per_s", "effective_tok_per_s_est"}:
                            continue
                        if name in {"input_tokens", "output_tokens", "context_usage_ratio"} and not has_api_usage:
                            continue
                        if name == "elapsed_seconds" and not is_slice:
                            continue
                        parsed = _audit_float(row.get(name))
                        if parsed is None:
                            continue
                        values[name].append(parsed * 100.0 if as_percent else parsed)
                        if name in {"template_tokens", "task_text_tokens"}:
                            has_components = True
                    if has_components:
                        component_rows += 1

                    # Derive directly from API In + Out; existing processing_tps
                    # uses API total_tokens and has a different zero-time fallback.
                    if not is_slice or usage_source != "llm_api_usage":
                        continue
                    # Cache coverage has its own denominator: no dependence
                    # on elapsed/output availability or heuristic estimates.
                    cache_input = _audit_token_count(row.get("input_tokens"))
                    cache_count = _audit_token_count(row.get("cached_input_tokens"))
                    if cache_input is not None and cache_input > 0:
                        cache_eligible_rows += 1
                        if (row.get("cached_input_token_source") == "provider_usage"
                                and cache_count is not None and cache_count <= cache_input):
                            cache_observed_rows += 1
                            cache_observed_input += cache_input
                            cache_observed_cached += cache_count
                    elapsed = _audit_float(row.get("elapsed_seconds"))
                    inp = _audit_float(row.get("input_tokens"))
                    out = _audit_float(row.get("output_tokens"))
                    if elapsed is None or elapsed <= 0 or inp is None or out is None or min(inp, out) < 0:
                        continue
                    values["total_tok_per_s"].append((inp + out) / elapsed)
                    cached = _audit_float(row.get("cached_input_tokens"))
                    if (row.get("cached_input_token_source") == "provider_usage"
                            and cached is not None and 0 <= cached <= inp):
                        values["effective_tok_per_s_est"].append((inp - cached + out) / elapsed)
                        provider_rows += 1
                        continue

                    task_tokens = _audit_float(row.get("task_text_tokens"))
                    template = _audit_float(row.get("template_tokens"))
                    stage = str(row.get("stage_identity", "") or "").strip()
                    source = str(row.get("prompt_component_token_source", "") or "").strip()
                    if (not stage or not source or task_tokens is None or template is None
                            or min(task_tokens, template) < 0):
                        continue
                    group = (row.get("model", ""), row.get("base_url", ""),
                             row.get("task", ""), stage, source)
                    # Running floor/ceiling avoid O(n²) rescans on long jobs.
                    prior = prior_templates.setdefault(
                        group, {"count": 0, "min": template, "max": template}
                    )
                    if prior["count"] >= 2:
                        floor, ceiling = prior["min"], prior["max"]
                        tolerance = max(1.0, floor * 0.05)
                        # Not token-level prefix proof. Require stable stage/size
                        # across prior requests; discount possible reusable floor.
                        if ceiling - floor <= tolerance and abs(template - floor) <= tolerance:
                            possibly_cached = min(template, floor * 0.5)
                            estimated_input = task_tokens + max(0.0, template - possibly_cached)
                            values["effective_tok_per_s_est"].append((estimated_input + out) / elapsed)
                            heuristic_rows += 1
                    prior["count"] += 1
                    prior["min"] = min(prior["min"], template)
                    prior["max"] = max(prior["max"], template)
        except (OSError, csv.Error, UnicodeError):
            if strict:
                raise
            pass
    return {
        "calls": calls, "failures": failures, "component_rows": component_rows,
        "effective_provider_rows": provider_rows,
        "effective_heuristic_rows": heuristic_rows,
        "provider_cache": {
            "eligible_rows": cache_eligible_rows,
            "observed_rows": cache_observed_rows,
            "observed_input_tokens": cache_observed_input,
            "observed_cached_tokens": cache_observed_cached,
            "hit_pct": (100 * cache_observed_cached / cache_observed_input
                        if cache_observed_input else None),
        },
        "metrics": {name: _audit_metric_snapshot(values[name]) for name, _, _ in _AUDIT_SERIES},
    }




def _strict_audit_snapshot(audit_path):
    """Fail closed on nonregular/symlink/oversized/changing or partial input."""
    path = Path(audit_path)
    if any(node.is_symlink() for node in (path, *path.parents)):
        raise ValueError("unsafe audit locator")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_AUDIT_BYTES:
        raise ValueError("audit exceeds read budget or is unsafe")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_BINARY", 0) |
                 getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as fp:
        opened = os.fstat(fp.fileno())
        if (not stat.S_ISREG(opened.st_mode) or opened.st_size > MAX_AUDIT_BYTES
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)):
            raise ValueError("audit changed before read")
        data = fp.read(MAX_AUDIT_BYTES + 1)
        after = os.fstat(fp.fileno())
    if (len(data) > MAX_AUDIT_BYTES or len(data) != opened.st_size
            or (opened.st_size, opened.st_mtime_ns) != (after.st_size, after.st_mtime_ns)
            or not data.endswith(b"\n")):
        raise ValueError("audit changed or incomplete tail")
    return io.StringIO(data.decode("utf-8"), newline="")


def load_public_audit(audit_path):
    """Only allowlisted numeric summaries; no grouping identifiers or raw rows."""
    if not audit_path:
        return {"status": "waiting_for_audit"}
    try:
        stats = load_llm_audit_distribution(audit_path, strict=True)
        # A derived number may overflow even when the original CSV value is finite.
        def safe_number(value):
            if type(value) not in (int, float) or not math.isfinite(value):
                raise ValueError("invalid metric")
            return value
        metrics = {}
        for key, _, _ in _AUDIT_SERIES:
            value = stats["metrics"][key]
            metrics[key] = {"count": value["count"],
                            "p50": safe_number(value["p50"]) if value["count"] else None,
                            "p95": safe_number(value["p95"]) if value["count"] else None,
                            "max": safe_number(value["max"]) if value["count"] else None}
        return {"status": "observed", "calls": stats["calls"],
                "failures": stats["failures"], "metrics": metrics,
                "provider_cache": stats["provider_cache"],
                "effective_provider_rows": stats["effective_provider_rows"],
                "effective_heuristic_rows": stats["effective_heuristic_rows"],
                "phase_metrics": {"ttft": None, "prefill": None, "decode": None},
                "scope": "bounded_current_audit_snapshot"}
    except FileNotFoundError:
        return {"status": "waiting_for_audit"}
    except (OSError, ValueError, UnicodeError, csv.Error, OverflowError):
        return {"status": "unavailable_or_over_budget"}
