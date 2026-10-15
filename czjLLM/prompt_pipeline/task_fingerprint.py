"""Deterministic, non-secret task identity for persisted extract provenance.

Callable signatures include referenced globals and helper functions, not just
their names. Only SHA-256 digests enter provenance manifests; transient values
serialized for hashing are never persisted, printed, or executed.
"""
from __future__ import annotations

import builtins
import dis
import functools
import hashlib
import inspect
import json
import textwrap
import types
from collections.abc import Mapping


def _code_signature(code: types.CodeType, active):
    return {
        "bytecode": code.co_code.hex(),
        "consts": [_stable(v, active) for v in code.co_consts],
        "names": list(code.co_names),
        "freevars": list(code.co_freevars),
        "cellvars": list(code.co_cellvars),
        "varnames": list(code.co_varnames),
        "argcount": code.co_argcount,
        "posonlyargcount": code.co_posonlyargcount,
        "kwonlyargcount": code.co_kwonlyargcount,
        "nlocals": code.co_nlocals,
        "flags": code.co_flags,
        "exceptiontable": getattr(code, "co_exceptiontable", b"").hex(),
    }


def _global_names(code: types.CodeType):
    """Find global loads, not attributes, including nested code objects."""
    names = set()
    for instruction in dis.get_instructions(code):
        if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME", "LOAD_FROM_DICT_OR_GLOBALS"}:
            names.add(instruction.argval)
    for const in code.co_consts:
        if isinstance(const, types.CodeType):
            names.update(_global_names(const))
    return names


def _stable(value, active=None):
    if active is None:
        active = set()
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, bytes):
        return {"bytes": value.hex()}
    if isinstance(value, types.CodeType):
        return {"code": _code_signature(value, active)}
    if isinstance(value, (Mapping, list, tuple, functools.partial)) or inspect.isfunction(value):
        if id(value) in active:
            if inspect.isfunction(value):
                # Back-edges in recursive helpers are stable by identity and
                # code. The first occurrence still hashes its dependencies.
                return {"recursive_function": f"{value.__module__}:{value.__qualname__}",
                        "code": _code_signature(value.__code__, active)}
            raise ValueError("cyclic task configuration cannot be fingerprinted")
        active.add(id(value))
        try:
            return _stable_composite(value, active)
        finally:
            active.remove(id(value))
    if inspect.ismethod(value):
        # A receiver may have mutable __slots__, class attributes, descriptors,
        # or external state even without an instance __dict__. Hashing just
        # __func__ silently reuses prompts after that state changes. Refuse
        # bound templates; callers can supply an explicit standalone function.
        raise ValueError("bound task templates cannot be fingerprinted safely")
    raise ValueError(f"unsupported task identity type: {type(value).__name__}")


def _stable_composite(value, active):
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("task mapping contains an unsupported key type")
        return {"mapping": [(key, _stable(value[key], active))
                            for key in sorted(value)]}
    if isinstance(value, (list, tuple)):
        return {"sequence_type": type(value).__name__,
                "items": [_stable(v, active) for v in value]}
    if isinstance(value, functools.partial):
        return {"partial": _stable(value.func, active),
                "args": _stable(value.args, active),
                "keywords": _stable(value.keywords or {}, active),
                "attributes": _stable(getattr(value, "__dict__", {}), active)}
    if inspect.isfunction(value):
        try:
            source = textwrap.dedent(inspect.getsource(value)).strip()
        except (OSError, TypeError):
            source = None
        closure = {}
        if value.__closure__:
            closure = {
                key: _stable(cell.cell_contents, active)
                for key, cell in zip(value.__code__.co_freevars, value.__closure__)
            }
        globals_used = {}
        for name in sorted(_global_names(value.__code__)):
            if name in value.__globals__:
                # Traverse ONLY referenced symbols, never the entire module
                # namespace. Unsupported dynamic globals fail closed.
                globals_used[name] = _stable(value.__globals__[name], active)
            elif name in {"globals", "locals", "vars", "eval", "exec", "__import__"}:
                # These builtins can resolve arbitrary namespace members not
                # visible in static LOAD_GLOBAL instructions. Reject reuse
                # rather than fingerprint a misleading incomplete dependency.
                raise ValueError(f"dynamic task template namespace access: {name}")
            elif hasattr(builtins, name):
                # Stable builtin identity; shadowing it with a module global
                # on a subsequent run will change the fingerprint.
                globals_used[name] = {"builtin": name}
            else:
                raise ValueError(f"unbound task template global: {name}")
        return {
            "function": f"{value.__module__}:{value.__qualname__}",
            "source": source,
            # Same-line lambdas may share source and qualname, but not code.
            "code": _code_signature(value.__code__, active),
            "defaults": _stable(value.__defaults__, active),
            "kwdefaults": _stable(value.__kwdefaults__, active),
            "closure": closure,
            "globals": globals_used,
            # Function objects can carry prompt-affecting mutable attributes.
            # Even a self-reference via template.prefix is covered: the
            # top-level function serializes __dict__, recursion uses a
            # stable back-edge and cannot suppress changed prefix values.
            "attributes": _stable(value.__dict__, active),
        }
    raise ValueError(f"unsupported task identity type: {type(value).__name__}")


def fingerprint_task(task) -> str:
    """SHA-256 of task semantics, without execution or persisted raw prompts.

    Unsupported dynamic values fail closed instead of reusing stale Success.
    """
    value = json.dumps(_stable(task), ensure_ascii=False, sort_keys=True,
                       separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
