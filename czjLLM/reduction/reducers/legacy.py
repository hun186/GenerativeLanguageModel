"""Source-agnostic adapters for the existing legacy combine semantics."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

from czjLLM.reduction.contracts import ReducerResult
from czjLLM.utilities.slice_merge import merge_dict_slices_audited


@dataclass(frozen=True)
class ConcatTextReducer:
    """Join already-prepared text items without filesystem preprocessing.

    Callers own discovery, filtering, ordering, and newline preparation.  This
    reducer preserves the supplied order and performs the legacy payload-level
    operation: an empty-string join.
    """

    profile: str = "concat_text"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = True

    def reduce(
        self,
        items: Iterable[Any],
        context: Optional[Mapping[str, Any]] = None,
    ) -> ReducerResult:
        del context
        prepared = list(items)
        if not all(isinstance(item, str) for item in prepared):
            raise TypeError("concat_text requires already-prepared string items")
        return ReducerResult(
            payload="".join(prepared),
            profile=self.profile,
            contract_version=self.contract_version,
            changed=len(prepared) > 1,
            metrics={"input_count": len(prepared)},
        )


@dataclass(frozen=True)
class ConcatJsonListReducer:
    """Collect dictionaries and first-level dictionary list members."""

    profile: str = "concat_json_list"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = True

    def reduce(
        self,
        items: Iterable[Any],
        context: Optional[Mapping[str, Any]] = None,
    ) -> ReducerResult:
        del context
        prepared = list(items)
        payload = []
        discarded_count = 0
        for item in prepared:
            if isinstance(item, dict):
                payload.append(item)
            elif isinstance(item, list):
                payload.extend(member for member in item if isinstance(member, dict))
                discarded_count += sum(not isinstance(member, dict) for member in item)
            else:
                discarded_count += 1
        return ReducerResult(
            payload=payload,
            profile=self.profile,
            contract_version=self.contract_version,
            changed=len(prepared) != 1 or (prepared and payload is not prepared[0]),
            metrics={
                "input_count": len(prepared),
                "output_count": len(payload),
                "discarded_count": discarded_count,
            },
        )


@dataclass(frozen=True)
class LegacyJsonDeepMergeReducer:
    """Delegate recursive dictionary merge behavior to the legacy utility."""

    conflict_policy: str = "prefer_left"
    dedup_lists: bool = False
    audit_enabled: bool = True
    max_audit_samples: int = 10
    profile: str = "legacy_json_deep_merge"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = True

    def reduce(
        self,
        items: Iterable[Any],
        context: Optional[Mapping[str, Any]] = None,
    ) -> ReducerResult:
        del context
        prepared = list(items)
        payload, report = merge_dict_slices_audited(
            prepared,
            conflict_policy=self.conflict_policy,
            dedup_lists=self.dedup_lists,
            audit=self.audit_enabled,
            logger=None,
            max_log=self.max_audit_samples,
        )
        return ReducerResult(
            payload=payload,
            profile=self.profile,
            contract_version=self.contract_version,
            changed=bool(report.get("changed")),
            audit=report,
            metrics={"input_count": len(prepared)},
        )
