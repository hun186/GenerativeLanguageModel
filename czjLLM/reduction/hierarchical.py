"""Source-agnostic, text-only hierarchical reduction execution facade."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Tuple

from czjLLM.reduction.artifacts import (
    CheckpointStore,
    derive_run_key,
    normalized_fingerprint,
    text_fingerprint,
    text_sequence_fingerprint,
)
from czjLLM.reduction.controllers import (
    ControllerState,
    ReductionController,
    STOP_MAX_ROUNDS,
    STOP_STALLED,
)
from czjLLM.reduction.registry import ReducerRegistry, get_default_registry


class HierarchicalReductionError(RuntimeError):
    """Base error for hierarchical execution failures."""


class EmptyReductionResultError(HierarchicalReductionError):
    """A reducer returned empty or whitespace-only text."""


class ReducerExecutionError(HierarchicalReductionError):
    """The selected reducer failed during a round."""


@dataclass(frozen=True)
class RoundMetrics:
    round_index: int
    input_item_count: int
    input_character_count: int
    output_character_count: int
    previous_aggregate_output_character_count: Optional[int] = None
    reduction_ratio: Optional[float] = None


@dataclass(frozen=True)
class HierarchicalReductionResult:
    payload: str
    profile: str
    rounds_completed: int
    stop_reason: str
    round_metrics: Tuple[RoundMetrics, ...]
    warnings: Tuple[str, ...] = ()
    resumed_rounds: int = 0


def reduce_hierarchical_text(
    initial_items: Iterable[str],
    *,
    profile: str,
    controller: ReductionController,
    next_round_items: Callable[[str, int], Iterable[str]],
    registry: Optional[ReducerRegistry] = None,
    context: Optional[Mapping[str, object]] = None,
    checkpoint_root: Optional[str | Path] = None,
) -> HierarchicalReductionResult:
    """Reduce prepared text items over deterministic, checkpointed rounds."""

    prepared = list(initial_items)
    if not all(isinstance(item, str) for item in prepared):
        raise TypeError("hierarchical reduction requires prepared text items")
    selected_registry = registry or get_default_registry()
    canonical_profile = selected_registry.normalize_name(profile)
    if canonical_profile != "concat_text":
        raise ValueError("PR D1 hierarchical reduction supports concat_text only")
    reducer = selected_registry.get(canonical_profile)
    if reducer is None:
        raise ValueError(f"Unknown reduction profile: {profile!r}")

    initial_fingerprint = text_sequence_fingerprint(prepared)
    policy_data = {
        "controller": controller.name,
        "policy": dict(controller.policy_data()),
        "profile": canonical_profile,
        "reducer_contract_version": reducer.contract_version,
    }
    policy_fingerprint = normalized_fingerprint(policy_data)
    store = None
    resumed = None
    if checkpoint_root is not None:
        run_key = derive_run_key(initial_fingerprint, policy_fingerprint)
        store = CheckpointStore(
            checkpoint_root,
            run_key=run_key,
            controller=controller.name,
            profile=canonical_profile,
            reducer_contract_version=reducer.contract_version,
            policy_fingerprint=policy_fingerprint,
            initial_input_fingerprint=initial_fingerprint,
        )
        resumed = store.load_highest_completed()
        if resumed is not None and resumed.terminal_stop_reason is not None:
            warning = (
                (f"hierarchical reduction stopped safely: {resumed.terminal_stop_reason}",)
                if resumed.terminal_stop_reason in {STOP_MAX_ROUNDS, STOP_STALLED}
                else ()
            )
            return HierarchicalReductionResult(
                resumed.payload,
                canonical_profile,
                resumed.round_index,
                resumed.terminal_stop_reason,
                tuple(RoundMetrics(**item) for item in resumed.metrics),
                warning,
                resumed.round_index,
            )

    round_index = resumed.round_index if resumed else 0
    previous_payload = resumed.payload if resumed else None
    parent_fingerprint = resumed.output_fingerprint if resumed else None
    metrics_history = (
        [RoundMetrics(**item) for item in resumed.metrics] if resumed else []
    )
    while True:
        next_index = round_index + 1
        if previous_payload is not None:
            prepared = list(next_round_items(previous_payload, next_index))
        if not all(isinstance(item, str) for item in prepared):
            raise TypeError("next_round_items must return prepared text items")
        input_fingerprint = text_sequence_fingerprint(prepared)
        try:
            reducer_result = reducer.reduce(prepared, context=context)
        except Exception as exc:
            raise ReducerExecutionError(
                f"Reducer failed in hierarchical round {next_index}: {exc}"
            ) from exc
        payload = reducer_result.payload
        if not isinstance(payload, str):
            raise TypeError("hierarchical text reducer must return a text payload")
        if not payload.strip():
            raise EmptyReductionResultError(
                f"Reducer returned empty text in hierarchical round {next_index}"
            )

        previous_chars = len(previous_payload) if previous_payload is not None else None
        ratio = None
        if previous_chars is not None:
            ratio = (previous_chars - len(payload)) / previous_chars
        metrics = RoundMetrics(
            round_index=next_index,
            input_item_count=len(prepared),
            input_character_count=sum(len(item) for item in prepared),
            output_character_count=len(payload),
            previous_aggregate_output_character_count=previous_chars,
            reduction_ratio=ratio,
        )
        decision = controller.decide(
            ControllerState(next_index, len(payload), previous_chars, ratio)
        )
        if store is not None:
            store.commit_round(
                round_index=next_index,
                payload=payload,
                parent_output_fingerprint=parent_fingerprint,
                reducer_input_fingerprint=input_fingerprint,
                metrics=metrics.__dict__,
                terminal_stop_reason=decision.stop_reason,
            )
        metrics_history.append(metrics)
        round_index = next_index
        if not decision.continue_reduction:
            assert decision.stop_reason is not None
            warnings = (
                (f"hierarchical reduction stopped safely: {decision.stop_reason}",)
                if decision.stop_reason in {STOP_MAX_ROUNDS, STOP_STALLED}
                else ()
            )
            return HierarchicalReductionResult(
                payload,
                canonical_profile,
                round_index,
                decision.stop_reason,
                tuple(metrics_history),
                warnings,
                resumed.round_index if resumed else 0,
            )
        previous_payload = payload
        parent_fingerprint = text_fingerprint(payload)
