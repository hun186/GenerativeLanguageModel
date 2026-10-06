"""Run-scoped, in-memory semantic-call memoization for Reduction v1.1."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import threading
from types import MappingProxyType
from typing import Any, Callable, Mapping

from czjLLM.reduction.artifacts import normalized_fingerprint
from czjLLM.reduction.reducers.semantic import SemanticCallResult
from czjLLM.reduction.runtime_task import ProductionTaskRuntime


SEMANTIC_CACHE_KEY_CONTRACT_VERSION = "reduction-transient-semantic-cache-key-v1"


@dataclass(frozen=True)
class ReductionTransientCachePolicy:
    """Operational cache policy. It never participates in semantic identity."""

    enabled: bool = False
    max_entries: int = 128
    max_output_characters: int = 200_000
    max_total_output_characters: int = 2_000_000

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise TypeError("reduction_transient_cache.enabled must be bool")
        for name in ("max_entries", "max_output_characters", "max_total_output_characters"):
            value = getattr(self, name)
            if type(value) is not int or value <= 0:
                raise ValueError(f"reduction_transient_cache.{name} must be a positive integer")
        if self.max_output_characters > self.max_total_output_characters:
            raise ValueError(
                "reduction_transient_cache.max_output_characters must be <= "
                "max_total_output_characters"
            )


@dataclass
class _SemanticCacheFlight:
    """One per-key owner/waiter rendezvous. Never persisted or logged."""

    event: threading.Event = field(default_factory=threading.Event)
    result: SemanticCallResult | None = None
    waiters: int = 0


_POLICY_KEYS = frozenset(ReductionTransientCachePolicy.__dataclass_fields__)


def parse_reduction_transient_cache_policy(value: Any) -> ReductionTransientCachePolicy:
    if value is None:
        return ReductionTransientCachePolicy()
    if isinstance(value, ReductionTransientCachePolicy):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("reduction_transient_cache must be a mapping")
    unknown = set(value) - _POLICY_KEYS
    if unknown:
        raise ValueError(f"unknown reduction_transient_cache keys: {sorted(unknown)!r}")
    return ReductionTransientCachePolicy(**dict(value))


def project_reduction_transient_cache_policy(
    ctx: Any, get_param: Callable[[str, Any], Any]
) -> ReductionTransientCachePolicy:
    """Project the root YAML policy once before production scheduling."""
    policy = parse_reduction_transient_cache_policy(
        get_param("reduction_transient_cache", None)
    )
    ctx.reduction_transient_cache = policy
    return policy


class RunScopedSemanticCache:
    """Bounded LRU plus per-key single-flight for one root run context."""

    def __init__(self, policy: ReductionTransientCachePolicy) -> None:
        if not isinstance(policy, ReductionTransientCachePolicy) or not policy.enabled:
            raise ValueError("RunScopedSemanticCache requires an enabled policy")
        self.policy = policy
        self._lock = threading.RLock()
        self._entries: OrderedDict[str, SemanticCallResult] = OrderedDict()
        self._inflight: dict[str, _SemanticCacheFlight] = {}
        self._output_characters = 0

    @staticmethod
    def _validate_key(key: str) -> None:
        if not isinstance(key, str) or not key:
            raise ValueError("semantic cache key must be non-blank")

    @staticmethod
    def _shared_result(result: SemanticCallResult) -> SemanticCallResult | None:
        if not isinstance(result, SemanticCallResult):
            raise TypeError("semantic cache values must be SemanticCallResult")
        if not result.ok or not isinstance(result.output, str) or not result.output.strip():
            return None
        return SemanticCallResult(
            output=result.output,
            cost_twd=0.0,
            model_name=str(result.model_name or ""),
            ok=True,
        )

    def _get_locked(self, key: str) -> SemanticCallResult | None:
        result = self._entries.pop(key, None)
        if result is None:
            return None
        self._entries[key] = result
        return self._shared_result(result)

    def get(self, key: str) -> SemanticCallResult | None:
        self._validate_key(key)
        with self._lock:
            return self._get_locked(key)

    def _store_locked(self, key: str, result: SemanticCallResult) -> bool:
        shared = self._shared_result(result)
        if shared is None:
            return False
        size = len(shared.output)
        if size > self.policy.max_output_characters or size > self.policy.max_total_output_characters:
            return False
        previous = self._entries.pop(key, None)
        if previous is not None:
            self._output_characters -= len(previous.output)
        self._entries[key] = shared
        self._output_characters += size
        while (
            len(self._entries) > self.policy.max_entries
            or self._output_characters > self.policy.max_total_output_characters
        ):
            _old_key, old = self._entries.popitem(last=False)
            self._output_characters -= len(old.output)
        return True

    def put(self, key: str, result: SemanticCallResult) -> bool:
        self._validate_key(key)
        with self._lock:
            return self._store_locked(key, result)

    def reserve(
        self, key: str
    ) -> tuple[SemanticCallResult | None, bool, _SemanticCacheFlight | None]:
        """Return cached result, owner reservation, or an existing flight to await."""
        self._validate_key(key)
        with self._lock:
            cached = self._get_locked(key)
            if cached is not None:
                return cached, False, None
            flight = self._inflight.get(key)
            if flight is None:
                flight = _SemanticCacheFlight()
                self._inflight[key] = flight
                return None, True, flight
            flight.waiters += 1
            return None, False, flight

    def wait_for_flight(
        self,
        flight: _SemanticCacheFlight,
        cancellation_check: Callable[[], None],
        *,
        poll_seconds: float = 0.05,
    ) -> SemanticCallResult | None:
        """Wait cooperatively; None means the owner failed and the caller may retry."""
        if not isinstance(flight, _SemanticCacheFlight):
            raise TypeError("flight must be a semantic cache reservation")
        if not callable(cancellation_check):
            raise TypeError("cancellation_check must be callable")
        if not isinstance(poll_seconds, (int, float)) or isinstance(poll_seconds, bool) or poll_seconds <= 0:
            raise ValueError("poll_seconds must be positive")
        try:
            cancellation_check()
            while not flight.event.wait(float(poll_seconds)):
                cancellation_check()
            cancellation_check()
            return flight.result
        finally:
            with self._lock:
                if flight.waiters > 0:
                    flight.waiters -= 1

    def complete(
        self, key: str, flight: _SemanticCacheFlight, result: SemanticCallResult
    ) -> bool:
        """Publish one successful owner result to current waiters and the bounded LRU."""
        self._validate_key(key)
        shared = self._shared_result(result)
        cached = False
        with self._lock:
            if self._inflight.get(key) is not flight:
                return False
            if shared is not None:
                cached = self._store_locked(key, result)
            flight.result = shared
            flight.event.set()
            self._inflight.pop(key, None)
        return cached

    def abort(self, key: str, flight: _SemanticCacheFlight) -> None:
        """Release waiters after owner failure; a waiter may reserve and retry."""
        self._validate_key(key)
        with self._lock:
            flight.result = None
            flight.event.set()
            if self._inflight.get(key) is flight:
                self._inflight.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._output_characters = 0
            flights = tuple(self._inflight.values())
            self._inflight.clear()
            for flight in flights:
                flight.result = None
                flight.event.set()

    def safe_snapshot(self) -> Mapping[str, int]:
        with self._lock:
            return MappingProxyType({
                "entries": len(self._entries),
                "output_characters": self._output_characters,
                "in_flight": len(self._inflight),
                "waiting": sum(flight.waiters for flight in self._inflight.values()),
            })


def semantic_call_cache_key(ctx: Any, rendered_prompt: str) -> str:
    """Hash prompt bytes plus the existing allowlisted production model semantics."""
    if not isinstance(rendered_prompt, str) or not rendered_prompt:
        raise ValueError("rendered_prompt must be non-blank")
    safe_runtime = ProductionTaskRuntime(ctx).fingerprint_metadata()
    return normalized_fingerprint({
        "contract_version": SEMANTIC_CACHE_KEY_CONTRACT_VERSION,
        "rendered_prompt_sha256": hashlib.sha256(
            rendered_prompt.encode("utf-8")
        ).hexdigest(),
        "runtime": dict(safe_runtime),
    })


def _root_context(ctx: Any) -> Any:
    seen: set[int] = set()
    current = ctx
    while id(current) not in seen:
        seen.add(id(current))
        base = getattr(current, "_base", None)
        if base is None:
            break
        current = base
    return current


def ensure_run_scoped_semantic_cache(ctx: Any) -> RunScopedSemanticCache | None:
    root = _root_context(ctx)
    policy = parse_reduction_transient_cache_policy(
        getattr(root, "reduction_transient_cache", None)
    )
    if not policy.enabled:
        return None
    cache = getattr(root, "_reduction_transient_semantic_cache", None)
    if not isinstance(cache, RunScopedSemanticCache) or cache.policy != policy:
        cache = RunScopedSemanticCache(policy)
        setattr(root, "_reduction_transient_semantic_cache", cache)
    return cache


def clear_run_scoped_semantic_cache(ctx: Any) -> None:
    root = _root_context(ctx)
    cache = getattr(root, "_reduction_transient_semantic_cache", None)
    if isinstance(cache, RunScopedSemanticCache):
        cache.clear()
    if hasattr(root, "_reduction_transient_semantic_cache"):
        delattr(root, "_reduction_transient_semantic_cache")
