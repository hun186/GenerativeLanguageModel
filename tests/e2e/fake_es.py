"""Minimal deterministic storage boundary for adapter scan and sink bulk."""

from __future__ import annotations

from copy import deepcopy


def extract(source, path):
    value = source
    for part in path.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def merge(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = deepcopy(value)


class _Indices:
    def __init__(self, store): self.store = store
    def exists(self, index): return index in self.store
    def refresh(self, index): return None
    def get_mapping(self, index): return {index: {"mappings": {"properties": {}}}}


class InMemoryES:
    def __init__(self, store):
        self.store = store
        self.indices = _Indices(store)

    def search(self, index, body, **_kwargs):
        hits = [{"_id": key, "_source": deepcopy(value)} for key, value in self.store.get(index, {}).items()]
        return {"hits": {"hits": hits[: body.get("size", len(hits))]}}

    def mget(self, index, body=None, ids=None, **_kwargs):
        requested = ids or (body or {}).get("ids", [])
        docs = []
        for key in requested:
            found = str(key) in self.store.get(index, {})
            docs.append({"_id": str(key), "found": found, "_source": deepcopy(self.store.get(index, {}).get(str(key), {}))})
        return {"docs": docs}


def scan(store, *, index, **_kwargs):
    for key, value in store.get(index, {}).items():
        yield {"_id": key, "_source": deepcopy(value)}


def bulk(store, actions):
    actions = list(actions)
    for action in actions:
        document = store.setdefault(action["_index"], {}).setdefault(action["_id"], {})
        merge(document, action["doc"])
    return len(actions), []
