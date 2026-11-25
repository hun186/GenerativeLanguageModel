"""Combine the actual profile and required-output rule on one candidate.

This local observation is not a verified attempt result, retry permission,
provider receipt, source identity or ES acknowledgment.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import hashlib
import json
import re

from czjLLM.common.required_output_guard import evaluate_required_output_checks
from .quality_output_profile_observation import (
    ProfileOutcome, _observe_normalized_profile,
)
from .quality_required_output_observation import _resolve_required_output_rule

_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_-]{0,95}\Z")


class CandidateObservationUnavailable(ValueError):
    """Payload-free local error."""


class CandidateOutcome(str, Enum):
    STRUCTURALLY_ACCEPTED = "STRUCTURALLY_ACCEPTED"
    PROFILE_REJECTED = "PROFILE_REJECTED"
    REQUIRED_OUTPUT_REJECTED = "REQUIRED_OUTPUT_REJECTED"


@dataclass(frozen=True)
class CandidateObservation:
    quality_rule_version: str
    outcome: CandidateOutcome


def _require(ok):
    if not ok:
        raise CandidateObservationUnavailable("quality candidate observation unavailable")


def _scope(sink, adapter, output_col):
    _require(type(output_col) is str and _FIELD.fullmatch(output_col))
    _require(adapter.es is not None and adapter.es is sink.es)
    _require(getattr(sink.ctx, "_es_adapter", None) is adapter)
    cfg = adapter.cfg
    _require(cfg.get("src_index") == cfg.get("tgt_index") == sink.index)
    _require(type(sink.index) is str and bool(sink.index))
    _require(sink.output_col == output_col)
    for raw in (cfg.get("output_col"), cfg.get("output_cols")):
        if raw is not None:
            _require((type(raw) is str and raw == output_col)
                     or (type(raw) in (list, tuple) and list(raw) == [output_col]))
    _require(adapter._resolve_output_cols() == [output_col])
    _require(not cfg.get("es_writeback_rules") and not cfg.get("stage_output_cols"))
    # The current sink can add writeback timestamps inside a candidate after
    # normalization. Do not claim parity with a post-mutation output here.
    _require(not getattr(sink.ctx, "update_time_inside_output", False))


def observe_candidate(sink, adapter, payload, output_col):
    """Use one normalized candidate, one effective rule snapshot, no ES I/O.

    Restrict to the same connected adapter, same single primary field and
    output-local checks. No return of normalized content or exception text.
    Both rule components participate even when the profile rejects.
    """
    try:
        _scope(sink, adapter, output_col)
        required_version, checks = _resolve_required_output_rule(adapter, output_col)
        profile, normalized = _observe_normalized_profile(sink, payload, output_col)
        if profile.outcome is ProfileOutcome.STRUCTURALLY_REJECTED:
            outcome = CandidateOutcome.PROFILE_REJECTED
        else:
            passed, _ = evaluate_required_output_checks({output_col: normalized}, checks)
            _require(type(passed) is bool)
            outcome = (CandidateOutcome.STRUCTURALLY_ACCEPTED if passed else
                       CandidateOutcome.REQUIRED_OUTPUT_REJECTED)
        _scope(sink, adapter, output_col)
        # A changed effective rule during local validation is unavailable.
        _require(_resolve_required_output_rule(adapter, output_col) ==
                 (required_version, checks))
        canonical = json.dumps(["quality-candidate-v1", profile.profile_version,
                                required_version], ensure_ascii=True,
                               separators=(",", ":"))
        version = "quality-v1-" + hashlib.sha256(canonical.encode("ascii")).hexdigest()
        return CandidateObservation(version, outcome)
    except CandidateObservationUnavailable:
        raise
    except Exception:
        raise CandidateObservationUnavailable("quality candidate observation unavailable") from None
