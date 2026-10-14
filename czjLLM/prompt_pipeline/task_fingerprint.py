"""Deterministic, non-secret task identity for persisted extract provenance.

In particular, stringifying a task mapping that embeds a callable template
is unsafe: Python function reprs contain process-local memory addresses.
Never include a prompt's or response's raw content in the identity record.
"""
from __future__ import annotations

import functools
import hashlib
import inspect
import json
import textwrap
import types
from collections.abc import Mapping


def _code_signature(code: types.CodeType):
    return {
        "bytecode": code.co_code.hex(),
        "consts": [_stable(v) for v in code.co_consts],
        "names": list(code.co_names),
        "freevars": list(code.co_freevars),
    }


def _stable(value):
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, types.CodeType):
        return {"code": _code_signature(value)}
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("task mapping contains an unsupported key type")
        return {"mapping": [(key, _stable(value[key]))
                            for key in sorted(value)]}
    if isinstance(value, (list, tuple)):
        return {"sequence_type": type(value).__name__,
                "items": [_stable(v) for v in value]}
    if isinstance(value, functools.partial):
        return {"partial": _stable(value.func),
                "args": _stable(value.args),
                "keywords": _stable(value.keywords or {})}
    if inspect.ismethod(value):
        # A bound method may depend on its receiver state; do not claim
        # reusable provenance unless the receiver is stateless.
        if getattr(value.__self__, "__dict__", {}):
            raise ValueError("stateful bound task templates cannot be fingerprinted")
        return _stable(value.__func__)
    if inspect.isfunction(value):
        try:
            source = textwrap.dedent(inspect.getsource(value)).strip()
        except (OSError, TypeError):
            source = None
        closure = {}
        if value.__closure__:
            closure = {
                key: _stable(cell.cell_contents)
                for key, cell in zip(value.__code__.co_freevars, value.__closure__)
            }
        return {
            "function": f"{value.__module__}:{value.__qualname__}",
            "source": source,
            # Source introspection can return an entire assignment line for
            # multiple lambdas. Equal source/module/qualname does not imply
            # equal behavior; always bind the callable's actual bytecode,
            # nested constants and referenced names into the identity.
            "code": _code_signature(value.__code__),
            "defaults": _stable(value.__defaults__),
            "kwdefaults": _stable(value.__kwdefaults__),
            "closure": closure,
        }
    raise ValueError(f"unsupported task identity type: {type(value).__name__}")


def fingerprint_task(task) -> str:
    """Stable SHA-256 of semantic task components, independent of function repr.

    Unsupported dynamic components deliberately fail closed rather than
    silently enabling reuse of outputs from an unrecognized template.
    """
    value = json.dumps(_stable(task), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
