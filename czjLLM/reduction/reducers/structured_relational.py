"""Deterministic canonicalization of record-local relational identifiers."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Iterable, Optional

from czjLLM.reduction.contracts import ReducerResult
from czjLLM.reduction.reducers.deterministic import canonical_json, normalize_json_value, validate_path


class StructuredRelationalError(ValueError):
    """Raised when relational configuration or data violates the v1 contract."""


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise StructuredRelationalError(f"{label} must be a nonblank string without surrounding whitespace")
    return value


@dataclass(frozen=True)
class EntitySetSpec:
    name: str
    collection_path: str
    id_field: str
    canonical_prefix: str


@dataclass(frozen=True)
class ReferenceSpec:
    collection_path: str
    field: str
    target: str


def _spec_mapping(value: Any, keys: frozenset[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise StructuredRelationalError(f"{label} must contain exactly: {', '.join(sorted(keys))}")
    return value


def _generated_namespaces_overlap(left: str, right: str) -> bool:
    """Return whether ``prefix + positive-decimal`` languages intersect."""
    if left == right:
        return True
    for longer, shorter in ((left, right), (right, left)):
        if longer.startswith(shorter):
            suffix = longer[len(shorter):]
            if suffix and all(character in "0123456789" for character in suffix) and suffix[0] in "123456789":
                return True
    return False


def validate_structured_relational_options(options: Any) -> tuple[tuple[EntitySetSpec, ...], tuple[ReferenceSpec, ...]]:
    """Validate and detach the exact PR J options schema."""
    options = _spec_mapping(options, frozenset({"entity_sets", "references"}), "structured_relational options")
    raw_entities, raw_references = options["entity_sets"], options["references"]
    if isinstance(raw_entities, (str, bytes)) or not isinstance(raw_entities, (list, tuple)) or not raw_entities:
        raise StructuredRelationalError("entity_sets must be a non-empty sequence")
    if isinstance(raw_references, (str, bytes)) or not isinstance(raw_references, (list, tuple)):
        raise StructuredRelationalError("references must be a sequence")

    entities = []
    names, prefixes, entity_endpoints = set(), [], set()
    for index, raw in enumerate(raw_entities):
        raw = _spec_mapping(raw, frozenset({"name", "collection_path", "id_field", "canonical_prefix"}), f"entity_sets[{index}]")
        name = _text(raw["name"], f"entity_sets[{index}].name")
        path = _text(raw["collection_path"], f"entity_sets[{index}].collection_path")
        try:
            validate_path(path, f"entity_sets[{index}].collection_path")
        except ValueError as exc:
            raise StructuredRelationalError(str(exc)) from exc
        id_field = _text(raw["id_field"], f"entity_sets[{index}].id_field")
        prefix = _text(raw["canonical_prefix"], f"entity_sets[{index}].canonical_prefix")
        if name in names:
            raise StructuredRelationalError(f"duplicate entity-set name: {name!r}")
        conflicting_prefix = next(
            (existing for existing in prefixes if _generated_namespaces_overlap(prefix, existing)),
            None,
        )
        if conflicting_prefix is not None:
            raise StructuredRelationalError(
                "overlapping canonical prefix namespaces: "
                f"{conflicting_prefix!r} and {prefix!r}"
            )
        endpoint = (path, id_field)
        if endpoint in entity_endpoints:
            raise StructuredRelationalError(
                f"duplicate entity endpoint: ({path!r}, {id_field!r})"
            )
        names.add(name); prefixes.append(prefix); entity_endpoints.add(endpoint)
        entities.append(EntitySetSpec(name, path, id_field, prefix))

    references = []
    reference_endpoints = set()
    for index, raw in enumerate(raw_references):
        raw = _spec_mapping(raw, frozenset({"collection_path", "field", "target"}), f"references[{index}]")
        path = _text(raw["collection_path"], f"references[{index}].collection_path")
        try:
            validate_path(path, f"references[{index}].collection_path")
        except ValueError as exc:
            raise StructuredRelationalError(str(exc)) from exc
        field_name = _text(raw["field"], f"references[{index}].field")
        target = _text(raw["target"], f"references[{index}].target")
        if target not in names:
            raise StructuredRelationalError(f"unknown target entity set: {target!r}")
        endpoint = (path, field_name)
        if endpoint in reference_endpoints:
            raise StructuredRelationalError(
                f"duplicate reference endpoint: ({path!r}, {field_name!r})"
            )
        if endpoint in entity_endpoints:
            raise StructuredRelationalError(
                "entity/reference endpoint conflict: "
                f"({path!r}, {field_name!r})"
            )
        reference_endpoints.add(endpoint)
        references.append(ReferenceSpec(path, field_name, target))
    return tuple(entities), tuple(references)


def _collection(record: Mapping[str, Any], path: str, label: str) -> list[Any] | tuple[Any, ...]:
    current: Any = record
    parts = path.split(".")
    for part in parts:
        if not isinstance(current, Mapping):
            raise StructuredRelationalError(f"{label} path {path!r} traverses a non-mapping")
        if part not in current:
            raise StructuredRelationalError(f"missing {label} collection path {path!r}")
        current = current[part]
    if not isinstance(current, (list, tuple)):
        raise StructuredRelationalError(f"{label} collection {path!r} must be a list or tuple")
    return current


def _output_collection(record: dict[str, Any], path: str) -> list[Any]:
    current: Any = record
    for part in path.split("."):
        current = current[part]
    return current


@dataclass(frozen=True)
class StructuredRelationalReducer:
    entity_sets: tuple[EntitySetSpec, ...] = ()
    references: tuple[ReferenceSpec, ...] = ()
    profile: str = "structured_relational"
    contract_version: str = "1"
    requires_stable_order: bool = True
    preserves_order: bool = True
    _allow_unconfigured: bool = field(default=False, repr=False, compare=False)

    def __init__(self, entity_sets: Any = None, references: Any = None, *, _allow_unconfigured: bool = False):
        object.__setattr__(self, "_allow_unconfigured", _allow_unconfigured)
        if _allow_unconfigured and entity_sets is None and references is None:
            object.__setattr__(self, "entity_sets", ())
            object.__setattr__(self, "references", ())
            return
        entities, refs = validate_structured_relational_options({"entity_sets": entity_sets, "references": references})
        object.__setattr__(self, "entity_sets", entities)
        object.__setattr__(self, "references", refs)

    @classmethod
    def _registry_prototype(cls) -> "StructuredRelationalReducer":
        return cls(_allow_unconfigured=True)

    def reduce(self, items: Iterable[Any], context: Optional[Mapping[str, Any]] = None) -> ReducerResult:
        del context
        if not self.entity_sets:
            raise StructuredRelationalError("structured_relational reducer is not configured")
        materialized = list(items)
        records = []
        for input_index, item in enumerate(materialized):
            members = item if isinstance(item, (list, tuple)) else (item,)
            for member_index, member in enumerate(members):
                if not isinstance(member, Mapping):
                    raise StructuredRelationalError(
                        f"input {input_index} member {member_index} must be a mapping"
                    )
                records.append(member)

        remap: dict[tuple[int, str, str], str] = {}
        remap_records = []
        counters = {spec.name: 0 for spec in self.entity_sets}
        # Pass 1: validate all entity namespaces and assign stable canonical IDs.
        for record_index, record in enumerate(records):
            for spec in self.entity_sets:
                seen = set()
                for member_index, member in enumerate(_collection(record, spec.collection_path, "entity")):
                    if not isinstance(member, Mapping):
                        raise StructuredRelationalError(f"entity member {member_index} at {spec.collection_path!r} must be a mapping")
                    if spec.id_field not in member:
                        raise StructuredRelationalError(f"missing ID field {spec.id_field!r} in {spec.collection_path!r}")
                    local_id = _text(member[spec.id_field], f"local ID {spec.id_field!r}")
                    if local_id in seen:
                        raise StructuredRelationalError(f"duplicate local ID {local_id!r} in record {record_index}, entity set {spec.name!r}")
                    seen.add(local_id); counters[spec.name] += 1
                    canonical_id = f"{spec.canonical_prefix}{counters[spec.name]}"
                    remap[(record_index, spec.name, local_id)] = canonical_id
                    remap_records.append({"record_index": record_index, "entity_set": spec.name,
                                          "local_id": local_id, "canonical_id": canonical_id})

        output = [normalize_json_value(record, f"record[{index}]") for index, record in enumerate(records)]
        reference_count = remapped_reference_count = 0
        # Pass 2: validate and rewrite only explicitly configured fields.
        for record_index, (source, target_record) in enumerate(zip(records, output)):
            for spec in self.entity_sets:
                source_members = _collection(source, spec.collection_path, "entity")
                target_members = _output_collection(target_record, spec.collection_path)
                for source_member, target_member in zip(source_members, target_members):
                    target_member[spec.id_field] = remap[(record_index, spec.name, source_member[spec.id_field])]
            for spec in self.references:
                source_members = _collection(source, spec.collection_path, "reference")
                target_members = _output_collection(target_record, spec.collection_path)
                for member_index, (source_member, target_member) in enumerate(zip(source_members, target_members)):
                    if not isinstance(source_member, Mapping):
                        raise StructuredRelationalError(f"reference member {member_index} at {spec.collection_path!r} must be a mapping")
                    if spec.field not in source_member:
                        raise StructuredRelationalError(f"missing reference field {spec.field!r} in {spec.collection_path!r}")
                    values = source_member[spec.field]
                    if not isinstance(values, (list, tuple)):
                        raise StructuredRelationalError(f"reference field {spec.field!r} must be a list or tuple")
                    rewritten, seen = [], set()
                    for value in values:
                        local_id = _text(value, f"reference ID in {spec.field!r}")
                        if local_id in seen:
                            raise StructuredRelationalError(f"duplicate reference ID {local_id!r} in field {spec.field!r}")
                        seen.add(local_id)
                        key = (record_index, spec.target, local_id)
                        if key not in remap:
                            raise StructuredRelationalError(f"unknown local reference {local_id!r} for target {spec.target!r} in record {record_index}")
                        canonical_id = remap[key]
                        rewritten.append(canonical_id)
                        reference_count += 1
                        if canonical_id != local_id:
                            remapped_reference_count += 1
                    target_member[spec.field] = rewritten

        # Fail-closed reducer-wide integrity verification after rewriting.
        ids_by_set = {spec.name: set() for spec in self.entity_sets}
        all_ids = set()
        for record in output:
            for spec in self.entity_sets:
                for member in _output_collection(record, spec.collection_path):
                    canonical_id = member[spec.id_field]
                    if canonical_id in all_ids:
                        raise StructuredRelationalError(f"canonical ID collision: {canonical_id!r}")
                    all_ids.add(canonical_id); ids_by_set[spec.name].add(canonical_id)
            for spec in self.references:
                for member in _output_collection(record, spec.collection_path):
                    values = member[spec.field]
                    if len(values) != len(set(values)):
                        raise StructuredRelationalError(f"duplicate canonical reference in field {spec.field!r}")
                    if any(value not in ids_by_set[spec.target] for value in values):
                        raise StructuredRelationalError(f"post-remap reference integrity failure for {spec.target!r}")

        normalized_original = [normalize_json_value(record) for record in records]
        immutable_remap = tuple(MappingProxyType(dict(entry)) for entry in remap_records)
        fingerprint = hashlib.sha256(canonical_json(remap_records).encode("utf-8")).hexdigest()
        remapped_ids = sum(entry["local_id"] != entry["canonical_id"] for entry in remap_records)
        return ReducerResult(
            output, self.profile, self.contract_version, output != normalized_original,
            audit=MappingProxyType({"remap_count": len(remap_records), "remap_fingerprint": fingerprint,
                                    "entity_set_count": len(self.entity_sets), "reference_spec_count": len(self.references)}),
            provenance=MappingProxyType({"id_remap": immutable_remap}),
            metrics=MappingProxyType({"input_record_count": len(records), "output_record_count": len(output),
                                      "entity_count": len(remap_records), "reference_count": reference_count,
                                      "remapped_id_count": remapped_ids,
                                      "remapped_reference_count": remapped_reference_count}),
        )
