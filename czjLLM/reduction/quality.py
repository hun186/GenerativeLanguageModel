"""Narrow task-specific final quality/coverage hook contract for ReductionStage."""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re
from types import MappingProxyType
from typing import Any, Mapping, Protocol, Tuple

from czjLLM.reduction.execution import ExecutionContext, ExecutionError


MAX_QUALITY_METRICS = 64
MAX_QUALITY_WARNINGS = 32
_METRIC_KEY = re.compile(r"[a-z][a-z0-9_.-]{0,63}")
_WARNING_CODE = re.compile(r"[a-z][a-z0-9_.:-]{0,95}")


@dataclass(frozen=True)
class QualityAssessment:
    """Payload-free result of one task-specific final quality check."""

    accepted: bool
    metrics: Mapping[str, bool | int | float] = field(default_factory=dict)
    warnings: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.accepted) is not bool:
            raise TypeError("quality assessment accepted must be bool")
        if not isinstance(self.metrics, Mapping):
            raise TypeError("quality assessment metrics must be a mapping")
        if len(self.metrics) > MAX_QUALITY_METRICS:
            raise ValueError(f"quality assessment metrics exceed {MAX_QUALITY_METRICS} entries")
        safe_metrics: dict[str, bool | int | float] = {}
        for key, value in self.metrics.items():
            if not isinstance(key, str) or not _METRIC_KEY.fullmatch(key):
                raise ValueError("quality metric keys must be safe lowercase identifiers")
            if type(value) not in {bool, int, float}:
                raise TypeError("quality metric values must be bool/int/float")
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("quality metric floats must be finite")
            safe_metrics[key] = value
        if not isinstance(self.warnings, tuple):
            raise TypeError("quality warnings must be a tuple")
        if len(self.warnings) > MAX_QUALITY_WARNINGS:
            raise ValueError(f"quality warnings exceed {MAX_QUALITY_WARNINGS} entries")
        if any(
            not isinstance(code, str) or not _WARNING_CODE.fullmatch(code)
            for code in self.warnings
        ):
            raise ValueError("quality warnings must be safe lowercase codes")
        object.__setattr__(self, "metrics", MappingProxyType(safe_metrics))


class QualityHook(Protocol):
    """One caller-supplied final-result policy; not a generic scorer registry."""

    contract_version: str

    def evaluate(
        self,
        *,
        payload: Any,
        context: ExecutionContext,
        metrics: Mapping[str, Any],
        provenance: Mapping[str, Any],
    ) -> QualityAssessment:
        ...

    def fingerprint_metadata(self, context: ExecutionContext) -> Mapping[str, Any]:
        ...


class QualityCheckError(ExecutionError):
    """A configured quality hook could not be evaluated safely."""

    reason = "quality_check_error"


class QualityCheckRejectedError(ExecutionError):
    """The final result failed the caller-supplied task-specific quality policy."""

    reason = "quality_check_rejected"

    def __init__(self, assessment: QualityAssessment) -> None:
        self.assessment = assessment
        super().__init__("quality check rejected final reduction result")
