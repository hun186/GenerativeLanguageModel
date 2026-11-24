"""Integrated disposable-only read-only budget inspection for #313.

Real observation APIs and the existing local SQLite proof are composed here.
This is not a dispatch gate, authenticated receipt or production adapter.
No state transitions, automatic calls or provider requests.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from czjLLM.reduction.persisted_freshness import reobserve_computed_es_execution_fingerprint
from .quality_candidate_observation import CandidateObservation, observe_candidate
from .quality_retry_contract import NextAction, Phase, RetryIdentity, RetryPolicy, next_action
from .quality_retry_sqlite_proof import DisposableQualityLedger


class BudgetInspectionUnavailable(ValueError):
    """Redacted read-time observation failure."""


@dataclass(frozen=True)
class BudgetInspection:
    candidate: CandidateObservation
    phase: Phase
    failed_repairs: int
    revision: int
    offline_next_action: NextAction


def _require(ok):
    if not ok:
        raise BudgetInspectionUnavailable("disposable budget inspection unavailable")


def inspect_disposable_candidate_budget(sink, adapter, ledger, policy, *,
                                        logical_id, expected_input,
                                        expected_stage_inputs, payload, output_col):
    """Read one scoped budget without claiming, finalizing or resetting it.

    Caller values are not authenticated dispatch provenance. Re-observe
    source/rules/execution around the ledger read; matches still do not
    constitute a transaction across ES, local execution, and SQLite.
    """
    try:
        _require(type(ledger) is DisposableQualityLedger and type(policy) is RetryPolicy)
        _require(type(expected_input) is str and type(expected_stage_inputs) is dict)
        stages = deepcopy(expected_stage_inputs)
        candidate_payload = deepcopy(payload)
        ctx = sink.ctx
        fingerprint = reobserve_computed_es_execution_fingerprint(ctx, adapter)
        _require(fingerprint is not None)
        candidate = observe_candidate(sink, adapter, candidate_payload, output_col)
        source = adapter.observe_quality_retry_inputs(
            logical_id, expected_input=expected_input, expected_stage_inputs=stages)
        _require(source.source.concrete_index == sink.index)
        # Private identity for this disposable diagnostic only.
        identity = RetryIdentity(source.scoped_document_revision(), output_col,
                                 fingerprint, candidate.quality_rule_version)
        state = ledger.read(identity)
        _require(state.identity == identity)
        _require(adapter.observe_quality_retry_inputs(
            logical_id, expected_input=expected_input, expected_stage_inputs=stages) == source)
        _require(observe_candidate(sink, adapter, candidate_payload, output_col) == candidate)
        _require(sink.ctx is ctx
                 and reobserve_computed_es_execution_fingerprint(ctx, adapter) == fingerprint)
        return BudgetInspection(candidate, state.phase, state.failed_repairs,
                                state.revision, next_action(state, policy))
    except BudgetInspectionUnavailable:
        raise
    except Exception:
        raise BudgetInspectionUnavailable("disposable budget inspection unavailable") from None
