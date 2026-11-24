"""Integrated disposable-only read-only budget inspection for #313.

Real observation APIs and the existing local SQLite proof are composed here.
This is not a dispatch gate, authenticated receipt or production adapter.
No state transitions, automatic calls or provider requests.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass

from czjLLM.reduction.persisted_freshness import reobserve_computed_es_execution_fingerprint
from .quality_candidate_observation import (
    CandidateObservation, observe_candidate, observe_candidate_rule_version,
)
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


@dataclass(frozen=True)
class PreDispatchBudgetInspection:
    quality_rule_version: str
    phase: Phase
    failed_repairs: int
    revision: int
    offline_next_action: NextAction


def _require(ok):
    if not ok:
        raise BudgetInspectionUnavailable("disposable budget inspection unavailable")


def _inspect(sink, adapter, ledger, policy, *, logical_id, expected_input,
             expected_stage_inputs, output_col, observe, version_of):
    """Shared private read-only observation boundary; never a transition."""
    _require(type(ledger) is DisposableQualityLedger and type(policy) is RetryPolicy)
    _require(type(expected_input) is str and type(expected_stage_inputs) is dict)
    stages = deepcopy(expected_stage_inputs)
    ctx = sink.ctx
    fingerprint = reobserve_computed_es_execution_fingerprint(ctx, adapter)
    _require(fingerprint is not None)
    observation = observe()
    version = version_of(observation)
    source = adapter.observe_quality_retry_inputs(
        logical_id, expected_input=expected_input, expected_stage_inputs=stages)
    _require(source.source.concrete_index == sink.index)
    identity = RetryIdentity(source.scoped_document_revision(), output_col,
                             fingerprint, version)
    state = ledger.read(identity)
    _require(state.identity == identity)
    _require(adapter.observe_quality_retry_inputs(
        logical_id, expected_input=expected_input, expected_stage_inputs=stages) == source)
    _require(observe() == observation)
    _require(sink.ctx is ctx
             and reobserve_computed_es_execution_fingerprint(ctx, adapter) == fingerprint)
    return observation, state, next_action(state, policy)


def inspect_disposable_pre_dispatch_budget(sink, adapter, ledger, policy, *,
                                           logical_id, expected_input,
                                           expected_stage_inputs, output_col):
    """Read the same budget before a candidate exists; no LLM call or claim.

    An offline action projection is not permission to dispatch. This cannot
    prove immutable queued inputs or replace a future atomic claim.
    """
    try:
        version, state, action = _inspect(
            sink, adapter, ledger, policy, logical_id=logical_id,
            expected_input=expected_input, expected_stage_inputs=expected_stage_inputs,
            output_col=output_col,
            observe=lambda: observe_candidate_rule_version(sink, adapter, output_col),
            version_of=lambda version: version)
        return PreDispatchBudgetInspection(version, state.phase, state.failed_repairs,
                                           state.revision, action)
    except BudgetInspectionUnavailable:
        raise
    except Exception:
        raise BudgetInspectionUnavailable("disposable budget inspection unavailable") from None


def inspect_disposable_candidate_budget(sink, adapter, ledger, policy, *,
                                        logical_id, expected_input,
                                        expected_stage_inputs, payload, output_col):
    """Read one scoped budget without claiming, finalizing or resetting it.

    Caller values are not authenticated dispatch provenance. Re-observe
    source/rules/execution around the ledger read; matches still do not
    constitute a transaction across ES, local execution, and SQLite.
    """
    try:
        candidate_payload = deepcopy(payload)
        candidate, state, action = _inspect(
            sink, adapter, ledger, policy, logical_id=logical_id,
            expected_input=expected_input, expected_stage_inputs=expected_stage_inputs,
            output_col=output_col,
            observe=lambda: observe_candidate(sink, adapter, candidate_payload, output_col),
            version_of=lambda candidate: candidate.quality_rule_version)
        return BudgetInspection(candidate, state.phase, state.failed_repairs,
                                state.revision, action)
    except BudgetInspectionUnavailable:
        raise
    except Exception:
        raise BudgetInspectionUnavailable("disposable budget inspection unavailable") from None
