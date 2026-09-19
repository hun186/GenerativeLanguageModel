"""Source-agnostic contracts for Reduction Engine reducers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Optional, Protocol, Tuple


@dataclass(frozen=True)
class ReducerResult:
    """The payload and stable metadata returned by a reducer.

    ``changed`` is reducer-local observational metadata.  Controllers must use
    their own deterministic metrics rather than treating it as convergence.
    """

    payload: Any
    profile: str
    contract_version: str
    changed: bool
    warnings: Tuple[str, ...] = ()
    audit: Mapping[str, Any] = field(default_factory=dict)
    provenance: Mapping[str, Any] = field(default_factory=dict)
    metrics: Mapping[str, Any] = field(default_factory=dict)


class Reducer(Protocol):
    """Minimal boundary implemented by source-independent reducers."""

    profile: str
    contract_version: str
    requires_stable_order: bool
    preserves_order: bool

    def reduce(
        self,
        items: Iterable[Any],
        context: Optional[Mapping[str, Any]] = None,
    ) -> ReducerResult:
        ...
