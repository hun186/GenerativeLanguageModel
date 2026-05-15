"""Registry for ES output profile payload transformers."""

from __future__ import annotations

from importlib import import_module
from typing import Any, Callable, Dict, Iterable, Mapping, Optional

Transformer = Callable[..., Any]


class OutputProfileRegistry:
    """Small registry that decouples profile names from transformer code."""

    def __init__(self) -> None:
        self._transformers: Dict[str, Transformer] = {}
        self._aliases: Dict[str, str] = {}

    @staticmethod
    def canonicalize(value: Any) -> str:
        if value is None:
            return "auto"
        return str(value).strip().lower().replace("-", "_").replace(" ", "_")

    def register(
        self,
        name: str,
        transformer: Transformer,
        *,
        aliases: Optional[Iterable[str]] = None,
    ) -> None:
        canonical_name = self.canonicalize(name)
        self._transformers[canonical_name] = transformer
        self._aliases[canonical_name] = canonical_name
        for alias in aliases or []:
            self._aliases[self.canonicalize(alias)] = canonical_name

    def normalize_name(self, value: Any) -> str:
        canonical = self.canonicalize(value)
        return self._aliases.get(canonical, canonical)

    def get(self, name: str) -> Optional[Transformer]:
        return self._transformers.get(self.normalize_name(name))

    def has(self, name: str) -> bool:
        return self.get(name) is not None

    def normalize_payload(self, name: str, payload: Any, **kwargs: Any) -> Any:
        transformer = self.get(name)
        if transformer is None:
            return payload
        return transformer(payload, **kwargs)


_DEFAULT_REGISTRY = OutputProfileRegistry()


def _passthrough(payload: Any, **_: Any) -> Any:
    return payload


def get_default_registry() -> OutputProfileRegistry:
    return _DEFAULT_REGISTRY


def register_output_profile(
    name: str,
    transformer: Transformer,
    *,
    aliases: Optional[Iterable[str]] = None,
) -> None:
    _DEFAULT_REGISTRY.register(name, transformer, aliases=aliases)


def _resolve_callable(path: str) -> Transformer:
    module_name, sep, attr_name = path.partition(":")
    if not sep:
        module_name, _, attr_name = path.rpartition(".")
    if not module_name or not attr_name:
        raise ValueError(f"Invalid output profile transformer path: {path!r}")
    module = import_module(module_name)
    transformer = getattr(module, attr_name)
    if not callable(transformer):
        raise TypeError(f"Output profile transformer is not callable: {path!r}")
    return transformer


def load_output_profile_plugins(plugins: Any, registry: Optional[OutputProfileRegistry] = None) -> None:
    """Load optional profile plugins declared by config/ctx.

    Supported entries:
    - "pkg.module" where module exposes register_output_profiles(registry) or register(registry)
    - {"module": "pkg.module"}
    - {"name": "profile", "transformer": "pkg.module:func", "aliases": [...]}
    """
    if not plugins:
        return
    if registry is None:
        registry = _DEFAULT_REGISTRY
    if isinstance(plugins, str):
        plugin_items = [plugins]
    elif isinstance(plugins, Mapping):
        if any(key in plugins for key in ("module", "transformer", "name", "profile")):
            plugin_items = [plugins]
        else:
            plugin_items = []
            for profile_name, declaration in plugins.items():
                if isinstance(declaration, Mapping):
                    merged = dict(declaration)
                    merged.setdefault("name", profile_name)
                    plugin_items.append(merged)
                else:
                    plugin_items.append({"name": profile_name, "transformer": declaration})
    else:
        plugin_items = list(plugins)

    for item in plugin_items:
        if isinstance(item, str):
            module = import_module(item)
            registrar = getattr(module, "register_output_profiles", None) or getattr(module, "register", None)
            if callable(registrar):
                registrar(registry)
            continue

        if not isinstance(item, Mapping):
            raise TypeError(f"Invalid output profile plugin declaration: {item!r}")

        if item.get("transformer"):
            name = item.get("name") or item.get("profile")
            if not name:
                raise ValueError(f"Output profile transformer declaration requires name/profile: {item!r}")
            registry.register(
                str(name),
                _resolve_callable(str(item["transformer"])),
                aliases=item.get("aliases") or (),
            )
            continue

        module_name = item.get("module")
        if not module_name:
            raise ValueError(f"Output profile plugin declaration requires module or transformer: {item!r}")
        module = import_module(str(module_name))
        registrar = getattr(module, "register_output_profiles", None) or getattr(module, "register", None)
        if callable(registrar):
            registrar(registry)


def _register_builtin_profiles() -> None:
    from .multidim_event import normalize_multidim_event_payload

    _DEFAULT_REGISTRY.register(
        "none",
        _passthrough,
        aliases=("", "generic", "raw", "plain", "passthrough"),
    )
    _DEFAULT_REGISTRY.register("json", _passthrough)
    _DEFAULT_REGISTRY.register("text", _passthrough)
    _DEFAULT_REGISTRY.register(
        "multidim_event",
        normalize_multidim_event_payload,
        aliases=("multi_dim_event", "multidim", "event"),
    )
    _DEFAULT_REGISTRY._aliases["default"] = "auto"


_register_builtin_profiles()
