"""Disposable-only integrated atomic claim proof for #313.

Never called by the runtime Consumer. Not dispatch authorization, authenticated
execution, source provenance or a production ledger.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .quality_candidate_observation import observe_candidate_rule_version
from .quality_retry_budget_inspection import _inspect
from .quality_retry_contract import NextAction, Phase, RetryIdentity


class DisposableClaimUnavailable(ValueError):
    """Fixed diagnostic; a failed return does not prove no commit."""


@dataclass(frozen=True)
class DisposableClaim:
    identity: RetryIdentity = field(repr=False)
    attempt_id: str = field(repr=False)
    revision: int
    failed_repairs: int


def claim_disposable_quality_repair(sink, adapter, ledger, policy, *,
                                    logical_id, expected_input, expected_stage_inputs,
                                    output_col, expected_revision, attempt_id):
    """Re-observe exact scope then CAS the existing disposable ledger.

    Only a READY record with a matching expected revision and enabled budget
    can be claimed. No provider, queue, sink write or automatic finalize.
    A lost/failed acknowledgement must be inspected, never retried blindly.
    The returned local receipt is not permission to execute a model.
    """
    try:
        if type(expected_revision) is not int or expected_revision < 1:
            raise DisposableClaimUnavailable("disposable claim unavailable")
        _, state, action = _inspect(
            sink, adapter, ledger, policy, logical_id=logical_id,
            expected_input=expected_input, expected_stage_inputs=expected_stage_inputs,
            output_col=output_col,
            observe=lambda: observe_candidate_rule_version(sink, adapter, output_col),
            version_of=lambda version: version)
        if (state.revision != expected_revision
                or action is not NextAction.ELIGIBLE_QUALITY_REPAIR):
            raise DisposableClaimUnavailable("disposable claim unavailable")
        claimed = ledger.transition(
            state.identity, expected_revision=expected_revision, operation="claim",
            policy=policy, verified_attempt_id=attempt_id)
        if (claimed.identity != state.identity
                or claimed.phase is not Phase.IN_FLIGHT
                or claimed.active_attempt_id != attempt_id
                or claimed.revision != expected_revision + 1
                or claimed.failed_repairs != state.failed_repairs):
            raise DisposableClaimUnavailable("disposable claim unavailable")
        return DisposableClaim(claimed.identity, attempt_id, claimed.revision,
                               claimed.failed_repairs)
    except DisposableClaimUnavailable:
        raise
    except Exception:
        raise DisposableClaimUnavailable("disposable claim unavailable") from None
