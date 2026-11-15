"""Issue #313: synthetic, pure state-machine regression; no real ES/LLM/Queue."""
from dataclasses import FrozenInstanceError, replace
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from czjLLM.es_mode.quality_retry_contract import (
    NextAction, Phase, QualityResult, RetryIdentity, RetryPolicy, RetryState,
    StaleRevision, StateTransitionError, authorized_manual_reset,
    claim_quality_repair, finalize_quality_repair, next_action,
    observe_initial, reconcile_uncertain,
)

ATTEMPT_A = "12345678-1234-4234-8234-1234567890a1"
ATTEMPT_B = "12345678-1234-4234-8234-1234567890a2"
OPERATOR_A = "12345678-1234-4234-8234-1234567890a3"
OPERATOR_B = "12345678-1234-4234-8234-1234567890a4"
ON = RetryPolicy(enabled=True)
OFF = RetryPolicy()


def new_state(**overrides):
    return RetryState(RetryIdentity(
        "PRIVATE_ACTUAL_ES_SOURCE_DOCUMENT_ID",
        "multidim_event_json",
        "a" * 64,
        "multidim_event_profile_v1",
    ), **overrides)


def rejected_initial():
    return observe_initial(
        new_state(), QualityResult.REJECTED,
        expected_revision=0, failure_code="SCHEMA_EVENT_REFERENCE",
    )


def take(state, token):
    return claim_quality_repair(
        state, ON, expected_revision=state.revision,
        verified_attempt_id=token,
    )


def settle(state, token, result=QualityResult.REJECTED,
           reason="SCHEMA_TIME_PRECISION"):
    return finalize_quality_repair(
        state, ON, expected_revision=state.revision,
        verified_attempt_id=token, result=result,
        failure_code=reason if result == QualityResult.REJECTED else None,
    )


def test_default_opt_in_off_does_not_schedule_or_consume_initial_reject():
    s = rejected_initial()
    assert s.failed_repairs == 0
    assert s.phase == Phase.READY
    assert next_action(s, OFF) == NextAction.DISABLED
    with pytest.raises(StateTransitionError):
        claim_quality_repair(
            s, OFF, expected_revision=1, verified_attempt_id=ATTEMPT_A
        )
    assert next_action(s, ON) == NextAction.ELIGIBLE_QUALITY_REPAIR


@pytest.mark.parametrize("result", [
    QualityResult.ACCEPTED, QualityResult.ACCEPTED_UNKNOWN_DATE,
])
def test_accepted_first_output_including_legitimate_unknown_never_repairs(result):
    s = observe_initial(new_state(), result, expected_revision=0)
    assert s.phase == Phase.COMPLETE
    assert s.failed_repairs == 0
    assert next_action(s, ON) == NextAction.COMPLETED_VALID
    with pytest.raises(StateTransitionError):
        take(s, ATTEMPT_A)


def test_two_completed_explicit_quality_failures_exhaust_not_fresh_completed():
    s = rejected_initial()
    for idx, token in enumerate((ATTEMPT_A, ATTEMPT_B), start=1):
        claimed = take(s, token)
        assert claimed.failed_repairs == idx - 1
        assert claimed.phase == Phase.IN_FLIGHT
        assert next_action(claimed, ON) == NextAction.IN_FLIGHT_UNVERIFIED
        s = settle(claimed, token)
        assert s.failed_repairs == idx
    assert s.phase == Phase.NEEDS_REVIEW
    assert next_action(s, ON) == NextAction.QUALITY_RETRY_EXHAUSTED
    assert s.last_quality_failure_code == "SCHEMA_TIME_PRECISION"
    with pytest.raises(StateTransitionError):
        take(s, ATTEMPT_A)


def test_first_repair_quality_success_is_complete_no_failure_charge():
    s = take(rejected_initial(), ATTEMPT_A)
    done = settle(s, ATTEMPT_A, result=QualityResult.ACCEPTED, reason=None)
    assert done.phase == Phase.COMPLETE
    assert done.failed_repairs == 0


def test_first_repair_valid_unknown_is_complete_not_forced_timeline():
    s = take(rejected_initial(), ATTEMPT_A)
    done = settle(
        s, ATTEMPT_A, result=QualityResult.ACCEPTED_UNKNOWN_DATE, reason=None
    )
    assert done.phase == Phase.COMPLETE
    assert done.failed_repairs == 0


def test_proven_no_result_transport_timeout_does_not_consume_attempt():
    s = take(rejected_initial(), ATTEMPT_A)
    cleared = settle(s, ATTEMPT_A, result=QualityResult.PROVEN_NO_RESULT,
                     reason=None)
    assert cleared.phase == Phase.READY
    assert cleared.failed_repairs == 0
    assert next_action(cleared, ON) == NextAction.ELIGIBLE_QUALITY_REPAIR
    again = take(cleared, ATTEMPT_B)
    assert again.failed_repairs == 0


def test_crash_or_sink_ack_uncertain_blocks_restart_until_verified_reconciliation():
    claimed = take(rejected_initial(), ATTEMPT_A)
    # Merely reconstructing a new in-memory object after process restart
    # never clears the outstanding claim. This is NOT durable persistence.
    restarted_snapshot = replace(claimed)
    assert next_action(restarted_snapshot, ON) == NextAction.IN_FLIGHT_UNVERIFIED
    with pytest.raises(StateTransitionError):
        take(restarted_snapshot, ATTEMPT_B)
    uncertain = settle(
        restarted_snapshot, ATTEMPT_A, result=QualityResult.UNCERTAIN,
        reason=None,
    )
    assert next_action(uncertain, ON) == NextAction.RECONCILIATION_REQUIRED
    with pytest.raises(StateTransitionError):
        take(uncertain, ATTEMPT_B)
    with pytest.raises(StateTransitionError):
        reconcile_uncertain(
            uncertain, ON, expected_revision=uncertain.revision,
            verified_attempt_id=ATTEMPT_A, verified_evidence=False,
            result=QualityResult.PROVEN_NO_RESULT,
        )
    reconciled = reconcile_uncertain(
        uncertain, ON, expected_revision=uncertain.revision,
        verified_attempt_id=ATTEMPT_A, verified_evidence=True,
        result=QualityResult.REJECTED,
        failure_code="SCHEMA_EVENT_REFERENCE",
    )
    assert reconciled.failed_repairs == 1
    assert reconciled.phase == Phase.READY
    assert next_action(reconciled, ON) == NextAction.ELIGIBLE_QUALITY_REPAIR


def test_verified_no_result_reconciliation_is_unbilled():
    s = settle(
        take(rejected_initial(), ATTEMPT_A), ATTEMPT_A,
        result=QualityResult.UNCERTAIN, reason=None,
    )
    restored = reconcile_uncertain(
        s, ON, expected_revision=s.revision,
        verified_attempt_id=ATTEMPT_A, verified_evidence=True,
        result=QualityResult.PROVEN_NO_RESULT,
    )
    assert restored.failed_repairs == 0
    assert restored.phase == Phase.READY


def test_duplicate_finalize_wrong_attempt_and_stale_revision_fail_closed():
    in_flight = take(rejected_initial(), ATTEMPT_A)
    with pytest.raises(StateTransitionError):
        settle(in_flight, ATTEMPT_B)
    settled = settle(in_flight, ATTEMPT_A)
    with pytest.raises(StaleRevision):
        finalize_quality_repair(
            settled, ON, expected_revision=in_flight.revision,
            verified_attempt_id=ATTEMPT_A, result=QualityResult.REJECTED,
            failure_code="SCHEMA_OTHER",
        )
    assert settled.failed_repairs == 1


def test_invalid_quality_code_never_consumes_budget():
    in_flight = take(rejected_initial(), ATTEMPT_A)
    with pytest.raises(StateTransitionError):
        settle(in_flight, ATTEMPT_A, reason="PRIVATE raw error string")
    assert in_flight.failed_repairs == 0


def test_explicit_authorized_manual_reset_requires_exhaustion_and_new_action():
    exhausted = settle(
        take(settle(take(rejected_initial(), ATTEMPT_A), ATTEMPT_A), ATTEMPT_B),
        ATTEMPT_B,
    )
    assert exhausted.phase == Phase.NEEDS_REVIEW
    with pytest.raises(StateTransitionError):
        authorized_manual_reset(
            exhausted, expected_revision=exhausted.revision,
            operator_authorized=False, unique_operator_action_id=OPERATOR_A,
        )
    reset = authorized_manual_reset(
        exhausted, expected_revision=exhausted.revision,
        operator_authorized=True, unique_operator_action_id=OPERATOR_A,
    )
    assert reset.failed_repairs == 0
    assert reset.phase == Phase.READY
    assert reset.manual_reset_generation == 1
    assert reset.last_quality_failure_code == "SCHEMA_TIME_PRECISION"
    with pytest.raises(StateTransitionError):
        authorized_manual_reset(
            reset, expected_revision=reset.revision,
            operator_authorized=True, unique_operator_action_id=OPERATOR_A,
        )
    assert next_action(reset, OFF) == NextAction.DISABLED


def test_reset_cannot_requeue_crashed_inflight_or_uncertain():
    in_flight = take(rejected_initial(), ATTEMPT_A)
    for s in (
        in_flight,
        settle(in_flight, ATTEMPT_A, result=QualityResult.UNCERTAIN, reason=None),
    ):
        with pytest.raises(StateTransitionError):
            authorized_manual_reset(
                s, expected_revision=s.revision,
                operator_authorized=True, unique_operator_action_id=OPERATOR_B,
            )


def test_quality_identity_is_scoped_to_verified_pipeline_and_rules():
    first = rejected_initial()
    newer_pipeline = replace(
        first.identity, verified_pipeline_sha256="b" * 64,
    )
    newer_rule = replace(first.identity, quality_rule_version="rules_v2")
    assert first.identity != newer_pipeline
    assert first.identity != newer_rule
    assert RetryState(newer_pipeline).phase == Phase.UNASSESSED
    assert RetryState(newer_rule).phase == Phase.UNASSESSED
    assert first.failed_repairs == 0
    assert first.identity.output_col == "multidim_event_json"


@pytest.mark.parametrize("changes", [
    {"source_document_id": ""},
    {"output_col": "../private"},
    {"verified_pipeline_sha256": "not-sha"},
    {"quality_rule_version": "a/b"},
])
def test_bad_identity_is_rejected(changes):
    base = dict(
        source_document_id="PRIVATE_SOURCE",
        output_col="multidim_event_json",
        verified_pipeline_sha256="a" * 64,
        quality_rule_version="v1",
    )
    base.update(changes)
    with pytest.raises(StateTransitionError):
        RetryIdentity(**base)


def test_no_private_source_ids_or_attempt_tokens_in_repr_and_immutable_state():
    s = take(rejected_initial(), ATTEMPT_A)
    shown = repr(s)
    assert "PRIVATE_ACTUAL_ES_SOURCE_DOCUMENT_ID" not in shown
    assert ATTEMPT_A not in shown
    assert "a" * 64 not in shown
    with pytest.raises(FrozenInstanceError):
        s.failed_repairs = 99


def test_two_producer_proposals_require_external_atomic_cas_not_local_revision():
    initial = rejected_initial()
    # Both immutable branches *could* propose from the same revision.
    # Only a real durable CAS adapter can publish one; this local fixture
    # models the contract, and must not be sold as cross-machine safety.
    accepted = [initial]
    guard = threading.Lock()

    def try_claim(token):
        with guard:
            observed = accepted[0]
        proposal = claim_quality_repair(
            observed, ON, expected_revision=observed.revision,
            verified_attempt_id=token,
        )
        with guard:
            if accepted[0].revision != observed.revision:
                return False
            accepted[0] = proposal
            return True

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(try_claim, (ATTEMPT_A, ATTEMPT_B)))
    assert results.count(True) == 1
    assert results.count(False) == 1
    assert accepted[0].phase == Phase.IN_FLIGHT
    assert accepted[0].failed_repairs == 0


def test_opt_in_budget_cannot_exceed_two():
    with pytest.raises(StateTransitionError):
        RetryPolicy(enabled=True, max_failed_repairs=3)
    assert RetryPolicy().enabled is False
