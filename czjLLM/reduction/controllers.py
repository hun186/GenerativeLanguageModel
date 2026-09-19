"""Deterministic policies for completed hierarchical reduction rounds."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Protocol


STOP_TARGET_REACHED = "target_reached"
STOP_FIXED_ROUNDS_COMPLETE = "fixed_rounds_complete"
STOP_MAX_ROUNDS = "max_rounds"
STOP_STALLED = "stalled"


@dataclass(frozen=True)
class ControllerState:
    round_index: int
    output_chars: int
    previous_output_chars: Optional[int] = None
    reduction_ratio: Optional[float] = None


@dataclass(frozen=True)
class ControllerDecision:
    continue_reduction: bool
    stop_reason: Optional[str] = None


class ReductionController(Protocol):
    name: str

    def decide(self, state: ControllerState) -> ControllerDecision: ...

    def policy_data(self) -> Mapping[str, Any]: ...


@dataclass(frozen=True)
class FixedRoundsController:
    rounds: int
    name: str = "fixed_rounds"

    def __post_init__(self) -> None:
        if type(self.rounds) is not int or self.rounds <= 0:
            raise ValueError("fixed rounds must be a positive integer")

    def decide(self, state: ControllerState) -> ControllerDecision:
        if state.round_index >= self.rounds:
            return ControllerDecision(False, STOP_FIXED_ROUNDS_COMPLETE)
        return ControllerDecision(True)

    def policy_data(self) -> Mapping[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdaptiveHierarchicalController:
    target_max_chars: int
    max_rounds: int
    min_reduction_ratio: float
    name: str = "adaptive_hierarchical"

    def __post_init__(self) -> None:
        if type(self.target_max_chars) is not int or self.target_max_chars < 0:
            raise ValueError("target_max_chars must be a non-negative integer")
        if type(self.max_rounds) is not int or self.max_rounds <= 0:
            raise ValueError("max_rounds must be a positive integer")
        if isinstance(self.min_reduction_ratio, bool) or not isinstance(
            self.min_reduction_ratio, (int, float)
        ):
            raise ValueError("min_reduction_ratio must be numeric")

    def decide(self, state: ControllerState) -> ControllerDecision:
        # Precedence is contractual: target, hard guard, then aggregate stall.
        if state.output_chars <= self.target_max_chars:
            return ControllerDecision(False, STOP_TARGET_REACHED)
        if state.round_index >= self.max_rounds:
            return ControllerDecision(False, STOP_MAX_ROUNDS)
        if (
            state.previous_output_chars is not None
            and state.reduction_ratio is not None
            and state.reduction_ratio < self.min_reduction_ratio
        ):
            return ControllerDecision(False, STOP_STALLED)
        return ControllerDecision(True)

    def policy_data(self) -> Mapping[str, Any]:
        return asdict(self)
