"""Safe, source-independent pending/freshness diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping


@dataclass(frozen=True)
class PendingDecision:
    pending: bool
    reason: str
    diagnostics: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.reason, str) or not self.reason:
            raise ValueError("PendingDecision.reason must be non-empty")
        object.__setattr__(self, "diagnostics", MappingProxyType(dict(self.diagnostics)))

