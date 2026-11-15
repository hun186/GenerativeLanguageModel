"""Offline-only, immutable Quality repair decision contract (Issue #313).

THIS IS NOT A DURABLE LEDGER OR RUNTIME ES RETRY GATE.
All transitions require an externally verified output quality decision. A real
adapter must provide durable, cross-process atomic compare-and-swap, source and
pipeline identity verification, authorization, audit, and crash reconciliation
before these transitions can control dispatch. Nothing here reads/writes ES,
the Queue, files, SQL, LLMs, or operator configuration.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from enum import Enum
import re
from uuid import UUID


class StateTransitionError(ValueError):
    """Invalid or unauthorized offline transition; safe fixed text only."""


class StaleRevision(StateTransitionError):
    """An observed immutable state revision no longer matches the caller."""


class Phase(str, Enum):
    UNASSESSED = "UNASSESSED"
    READY = "READY"
    IN_FLIGHT = "IN_FLIGHT"
    UNCERTAIN = "UNCERTAIN"
    COMPLETE = "COMPLETE"
    NEEDS_REVIEW = "NEEDS_REVIEW"


class QualityResult(str, Enum):
    ACCEPTED = "ACCEPTED"
    ACCEPTED_UNKNOWN_DATE = "ACCEPTED_UNKNOWN_DATE"
    REJECTED = "REJECTED"
    PROVEN_NO_RESULT = "PROVEN_NO_RESULT"
    UNCERTAIN = "UNCERTAIN"


class NextAction(str, Enum):
    DISABLED = "DISABLED"
    INITIAL_VALIDATION_NEEDED = "INITIAL_VALIDATION_NEEDED"
    ELIGIBLE_QUALITY_REPAIR = "ELIGIBLE_QUALITY_REPAIR"
    IN_FLIGHT_UNVERIFIED = "IN_FLIGHT_UNVERIFIED"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    COMPLETED_VALID = "COMPLETED_VALID"
    QUALITY_RETRY_EXHAUSTED = "QUALITY_RETRY_EXHAUSTED"


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,95}\Z")
_VERSION = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,95}\Z")
_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z")


def _uuid4(value: str) -> None:
    if not isinstance(value, str):
        raise StateTransitionError("verified unique operation id required")
    try:
        parsed = UUID(value)
    except ValueError:
        raise StateTransitionError("verified unique operation id required") from None
    if parsed.version != 4 or str(parsed) != value:
        raise StateTransitionError("verified unique operation id required")


@dataclass(frozen=True)
class RetryIdentity:
    """Private full source ID; no truncation, hashing shortcut or repr leakage.

    'verified' fingerprint is a *caller obligation*. A hex shape cannot prove
    that the exact executable pipeline/source was authenticated.
    """
    source_document_id: str = field(repr=False)
    output_col: str
    verified_pipeline_sha256: str = field(repr=False)
    quality_rule_version: str

    def __post_init__(self) -> None:
        if (not isinstance(self.source_document_id, str)
                or not (1 <= len(self.source_document_id) <= 4096)):
            raise StateTransitionError("invalid verified source identity")
        if not isinstance(self.output_col, str) or not _FIELD.fullmatch(self.output_col):
            raise StateTransitionError("invalid output column")
        if (not isinstance(self.verified_pipeline_sha256, str)
                or not _SHA256.fullmatch(self.verified_pipeline_sha256)):
            raise StateTransitionError("verified pipeline SHA256 required")
        if (not isinstance(self.quality_rule_version, str)
                or not _VERSION.fullmatch(self.quality_rule_version)):
            raise StateTransitionError("quality-rule version required")


@dataclass(frozen=True)
class RetryPolicy:
    """Opt-in OFF; maximum of two completed, explicitly rejected repairs."""
    enabled: bool = False
    max_failed_repairs: int = 2

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise StateTransitionError("invalid opt-in")
        if type(self.max_failed_repairs) is not int or not 1 <= self.max_failed_repairs <= 2:
            raise StateTransitionError("repair budget must be one or two")


@dataclass(frozen=True)
class RetryState:
    identity: RetryIdentity = field(repr=False)
    phase: Phase = Phase.UNASSESSED
    failed_repairs: int = 0
    revision: int = 0
    active_attempt_id: str | None = field(default=None, repr=False)
    last_quality_failure_code: str | None = None
    manual_reset_generation: int = 0
    last_manual_reset_id: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.identity, RetryIdentity) or not isinstance(self.phase, Phase):
            raise StateTransitionError("invalid retry state")
        for name in ("failed_repairs", "revision", "manual_reset_generation"):
            value = getattr(self, name)
            if type(value) is not int or value < 0:
                raise StateTransitionError("invalid retry state counter")
        in_flight = self.phase in (Phase.IN_FLIGHT, Phase.UNCERTAIN)
        if in_flight != (self.active_attempt_id is not None):
            raise StateTransitionError("invalid outstanding repair state")
        if self.active_attempt_id is not None:
            _uuid4(self.active_attempt_id)
        if self.last_quality_failure_code is not None:
            if (not isinstance(self.last_quality_failure_code, str)
                    or not _CODE.fullmatch(self.last_quality_failure_code)):
                raise StateTransitionError("invalid quality failure code")
        if self.last_manual_reset_id is not None:
            _uuid4(self.last_manual_reset_id)


def next_action(state: RetryState, policy: RetryPolicy) -> NextAction:
    """Informational only: MUST NOT be used as an unguarded dispatch claim."""
    if state.phase == Phase.COMPLETE:
        return NextAction.COMPLETED_VALID
    if state.phase == Phase.NEEDS_REVIEW or state.failed_repairs >= policy.max_failed_repairs:
        return NextAction.QUALITY_RETRY_EXHAUSTED
    if state.phase == Phase.UNCERTAIN:
        return NextAction.RECONCILIATION_REQUIRED
    if state.phase == Phase.IN_FLIGHT:
        return NextAction.IN_FLIGHT_UNVERIFIED
    if not policy.enabled:
        return NextAction.DISABLED
    if state.phase == Phase.UNASSESSED:
        return NextAction.INITIAL_VALIDATION_NEEDED
    return NextAction.ELIGIBLE_QUALITY_REPAIR


def _revision(state: RetryState, expected_revision: int) -> None:
    if type(expected_revision) is not int or state.revision != expected_revision:
        raise StaleRevision("stale offline revision; durable CAS required")


def _outcome(outcome: QualityResult, failure_code: str | None) -> None:
    if not isinstance(outcome, QualityResult):
        raise StateTransitionError("invalid verified quality result")
    if outcome == QualityResult.REJECTED:
        if not isinstance(failure_code, str) or not _CODE.fullmatch(failure_code):
            raise StateTransitionError("fixed validator failure code required")
    elif failure_code is not None:
        raise StateTransitionError("unexpected validator failure code")


def observe_initial(
    state: RetryState, result: QualityResult, *,
    expected_revision: int, failure_code: str | None = None,
) -> RetryState:
    """First extraction is never one of the two *failed repair* attempts.

    ACCEPTED_UNKNOWN_DATE must come from real profile validation, not from a
    guessed absence of Event_Timeline.date or an unchecked null.
    """
    _revision(state, expected_revision)
    if state.phase != Phase.UNASSESSED:
        raise StateTransitionError("initial observation already evaluated")
    if result not in (
        QualityResult.ACCEPTED, QualityResult.ACCEPTED_UNKNOWN_DATE,
        QualityResult.REJECTED,
    ):
        raise StateTransitionError("initial observation lacks verified output")
    _outcome(result, failure_code)
    if result == QualityResult.REJECTED:
        return replace(state, revision=state.revision + 1, phase=Phase.READY,
                       last_quality_failure_code=failure_code)
    return replace(state, revision=state.revision + 1, phase=Phase.COMPLETE)


def claim_quality_repair(
    state: RetryState, policy: RetryPolicy, *, expected_revision: int,
    verified_attempt_id: str,
) -> RetryState:
    """A pure claim *proposal*. Real multi-producer dispatch needs atomic CAS."""
    _revision(state, expected_revision)
    _uuid4(verified_attempt_id)
    if next_action(state, policy) != NextAction.ELIGIBLE_QUALITY_REPAIR:
        raise StateTransitionError("quality repair not authorized by offline policy")
    return replace(state, revision=state.revision + 1, phase=Phase.IN_FLIGHT,
                   active_attempt_id=verified_attempt_id)


def _settle(
    state: RetryState, policy: RetryPolicy, *,
    result: QualityResult, failure_code: str | None,
) -> RetryState:
    _outcome(result, failure_code)
    updated = dict(active_attempt_id=None, revision=state.revision + 1)
    if result == QualityResult.REJECTED:
        count = state.failed_repairs + 1
        updated.update(
            failed_repairs=count, last_quality_failure_code=failure_code,
            phase=(Phase.NEEDS_REVIEW if count >= policy.max_failed_repairs
                   else Phase.READY),
        )
    elif result in (QualityResult.ACCEPTED, QualityResult.ACCEPTED_UNKNOWN_DATE):
        updated["phase"] = Phase.COMPLETE
    elif result == QualityResult.PROVEN_NO_RESULT:
        updated["phase"] = Phase.READY
    else:
        updated.update(phase=Phase.UNCERTAIN,
                       active_attempt_id=state.active_attempt_id)
    return replace(state, **updated)


def finalize_quality_repair(
    state: RetryState, policy: RetryPolicy, *, expected_revision: int,
    verified_attempt_id: str, result: QualityResult,
    failure_code: str | None = None,
) -> RetryState:
    _revision(state, expected_revision)
    _uuid4(verified_attempt_id)
    if (state.phase != Phase.IN_FLIGHT
            or state.active_attempt_id != verified_attempt_id):
        raise StateTransitionError("repair claim identity mismatch")
    return _settle(state, policy, result=result, failure_code=failure_code)


def reconcile_uncertain(
    state: RetryState, policy: RetryPolicy, *, expected_revision: int,
    verified_attempt_id: str, verified_evidence: bool,
    result: QualityResult, failure_code: str | None = None,
) -> RetryState:
    """Offline modeling only: verified reconciliation must come from real sink.

    An unverified timeout/crash/ACK gap is NOT permission to issue another
    repair; the original attempt stays blocked until operator-controlled proof.
    """
    _revision(state, expected_revision)
    _uuid4(verified_attempt_id)
    if (state.phase != Phase.UNCERTAIN
            or state.active_attempt_id != verified_attempt_id
            or verified_evidence is not True or result == QualityResult.UNCERTAIN):
        raise StateTransitionError("uncertain attempt needs verified reconciliation")
    return _settle(state, policy, result=result, failure_code=failure_code)


def authorized_manual_reset(
    state: RetryState, *, expected_revision: int,
    operator_authorized: bool, unique_operator_action_id: str,
) -> RetryState:
    """Simulates an externally authorized reset; neither authorizes nor audits.

    Production requires durable, access-controlled operator approval plus an
    append-only audit record in the same atomic transaction as budget reset.
    Do not reset an in-flight or unreconciled claim, or rewrite existing ES.
    """
    _revision(state, expected_revision)
    _uuid4(unique_operator_action_id)
    if operator_authorized is not True or state.phase != Phase.NEEDS_REVIEW:
        raise StateTransitionError("manual reset requires authorized review state")
    if state.last_manual_reset_id == unique_operator_action_id:
        raise StateTransitionError("replayed operator reset ID")
    return replace(
        state, revision=state.revision + 1, phase=Phase.READY,
        failed_repairs=0, manual_reset_generation=state.manual_reset_generation + 1,
        last_manual_reset_id=unique_operator_action_id,
    )
