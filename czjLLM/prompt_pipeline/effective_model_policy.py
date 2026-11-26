"""Startup observation of the effective legacy LLM client policy.

Not a provider capability probe, admission receipt, or measured concurrency.
Only allowlisted numbers and fixed policy labels are returned; never URLs,
credentials, task text or the full model specification.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from czjLLM.prompt_pipeline.dispatch_parallelism import (
    configured_endpoint_concurrency_limit,
    configured_model_process_parallelism,
)
from czjLLM.prompt_pipeline.request_policy import (
    context_round_timeout, request_policy, reasoning_fingerprint_metadata,
)
from czjLLM.prompt_pipeline.round_runner import _round_timeout_from_jobs


def _endpoint_count(spec):
    urls = spec.get("base_url")
    if isinstance(urls, str):
        urls = [urls]
    if not isinstance(urls, (list, tuple)) or not urls:
        return None
    if any(not isinstance(url, str) or not url.strip() for url in urls):
        return None
    return len(set(urls))


def effective_model_startup_policy(ctx):
    """Read the final context before worker launch, without changing it."""
    spec = getattr(ctx, "model_spec", None)
    if not isinstance(spec, Mapping) or not spec:
        return None
    spec = dict(spec)
    read, retries, effort = request_policy(spec)
    configured_workers = configured_model_process_parallelism(spec)
    cap = configured_endpoint_concurrency_limit(spec)
    count = _endpoint_count(spec)
    actual = getattr(ctx, "n_process", None)
    actual = actual if type(actual) is int and actual > 0 else None
    round_timeout = _round_timeout_from_jobs((), context_round_timeout(ctx))
    if not math.isfinite(round_timeout):
        round_timeout = None
    return {
        "available_endpoint_count": count,
        "configured_worker_budget": configured_workers or None,
        "context_worker_budget": actual,
        "worker_budget_matches_profile": (
            actual == configured_workers if actual is not None and configured_workers else None
        ),
        "endpoint_lease_limit": cap,
        "http_read_inactivity_seconds": read,
        "round_deadline_seconds": round_timeout,
        "sdk_retry_count": retries,
        "reasoning_effort": effort,
        "reasoning_suffix_policy": reasoning_fingerprint_metadata(spec).get("reasoning_suffix_policy"),
    }


def format_effective_model_startup_policy(ctx):
    """Fixed labels, no raw model/endpoint strings and no guessed defaults."""
    try:
        state = effective_model_startup_policy(ctx)
    except Exception:
        return "[Effective Model Configuration] unavailable (invalid or unresolved policy)"
    if state is None:
        return "[Effective Model Configuration] unavailable (no model policy)"
    def show(value, missing="unknown"):
        return missing if value is None else str(value)
    mismatch = state["worker_budget_matches_profile"]
    match_label = "unknown" if mismatch is None else "yes" if mismatch else "NO"
    return (
        "[Effective Model Configuration] "
        f"endpoints={show(state['available_endpoint_count'])} | "
        f"profile_workers={show(state['configured_worker_budget'], 'auto')} | "
        f"context_workers={show(state['context_worker_budget'])} | "
        f"worker_budget_match={match_label} | "
        f"endpoint_lease_cap={show(state['endpoint_lease_limit'], 'legacy uncapped')} | "
        f"HTTP_read_inactivity_s={show(state['http_read_inactivity_seconds'], 'client default')} | "
        f"round_deadline_s={show(state['round_deadline_seconds'])} | "
        f"SDK_retries={show(state['sdk_retry_count'], 'SDK default')} | "
        f"reasoning_effort={show(state['reasoning_effort'], 'provider default')} | "
        f"reasoning_suffix={show(state['reasoning_suffix_policy'], 'legacy policy')} | "
        "scope=legacy_client_policy; provider_support=unverified"
    )
