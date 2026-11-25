"""Opt-in model request settings; absent fields preserve historical defaults."""
from __future__ import annotations

import math


def optional_seconds(spec, key):
    if key not in spec:
        return None
    value = spec[key]
    if type(value) not in (int, float) or not math.isfinite(value) or value < 1:
        raise ValueError(f"{key} must be a finite number >= 1")
    return float(value)


def request_policy(spec):
    read = optional_seconds(spec, "llm_read_timeout_sec")
    retries = spec.get("llm_max_retries")
    if "llm_max_retries" in spec and (type(retries) is not int or retries < 0 or retries > 10):
        raise ValueError("llm_max_retries must be an integer between 0 and 10")
    effort = None
    if "thinking_level" in spec:
        level = spec["thinking_level"]
        if level is False:
            effort = "none"
        elif isinstance(level, str) and level in {
            "none", "minimal", "low", "medium", "high", "xhigh", "max"
        }:
            effort = level
        else:
            raise ValueError("thinking_level must be False or a supported named effort")
    optional_seconds(spec, "llm_round_timeout_sec")
    return read, retries, effort


def model_round_timeout(spec):
    return optional_seconds(spec or {}, "llm_round_timeout_sec")


def context_round_timeout(ctx):
    explicit = getattr(ctx, "llm_round_timeout_sec", None)
    if explicit is not None:
        return explicit
    return model_round_timeout(getattr(ctx, "model_spec", None))
