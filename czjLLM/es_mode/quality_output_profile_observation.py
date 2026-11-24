"""Narrow local structural profile observation for #313.

Not a provider receipt, source verification, quality retry permission,
writeback ACK or full execution attestation.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import Enum

from .output_profiles import get_default_registry
from .output_profiles.multidim_event import normalize_multidim_event_payload


# Must change when the observed built-in normalization or sink pre-processing
# semantics change. This is a contract label, not a hash of executable code.
_VERSION = "multidim-output-profile-v1"


class OutputProfileObservationUnavailable(ValueError):
    """Fixed diagnostic that never includes payload or private settings."""


class ProfileOutcome(str, Enum):
    STRUCTURALLY_ACCEPTED = "STRUCTURALLY_ACCEPTED"
    STRUCTURALLY_REJECTED = "STRUCTURALLY_REJECTED"


@dataclass(frozen=True)
class OutputProfileObservation:
    profile_version: str
    outcome: ProfileOutcome


def _require(ok):
    if not ok:
        raise OutputProfileObservationUnavailable("output profile observation unavailable")


def _supported(sink, output_col):
    _require(type(output_col) is str and output_col == sink.output_col)
    _require(sink.write_output is True and sink.flatten_json is False)
    _require(not getattr(sink.ctx, "es_writeback_rules", None)
             and not getattr(sink.ctx, "output_profile_plugins", None)
             and not getattr(sink.ctx, "output_profiles", None))
    profile = sink._profile_for_output_col(output_col)
    _require(profile == "multidim_event")
    _require(get_default_registry().get(profile) is normalize_multidim_event_payload)


def observe_output_profile(sink, payload, output_col):
    """Reuse single-field sink parsing and the exact known built-in validator.

    Unsupported routes and passthrough profiles have no structural verdict.
    Work on a copy; discard normalized content and raw exception details.
    Empty output is unavailable, not a valid or rejected repair result.
    """
    try:
        _supported(sink, output_col)
        raw = sink._unwrap_output_col_envelope(
            sink._maybe_parse_json(deepcopy(payload)), output_col)
        _require(sink._normalize_payload_for_es(raw) is not None)
        try:
            normalized = normalize_multidim_event_payload(
                raw, ctx=sink.ctx, output_col=output_col, sink=sink)
        except (TypeError, ValueError):
            outcome = ProfileOutcome.STRUCTURALLY_REJECTED
        else:
            _require(sink._normalize_payload_for_es(normalized) is not None)
            outcome = ProfileOutcome.STRUCTURALLY_ACCEPTED
        _supported(sink, output_col)
        return OutputProfileObservation(_VERSION, outcome)
    except OutputProfileObservationUnavailable:
        raise
    except Exception:
        raise OutputProfileObservationUnavailable("output profile observation unavailable") from None
