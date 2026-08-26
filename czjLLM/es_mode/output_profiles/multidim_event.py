"""ES output profile for the current multidimensional-event schema only.

Responsibilities:
- preserve the current Event[] / event_id / event_ids structure;
- perform format-only normalization for already-resolved ISO time strings;
- validate schema relationships before Elasticsearch writeback.

It intentionally does NOT infer semantic dates/times from time_raw and does NOT
support the legacy single-object Event or Event_Timeline.date* schema.
"""

from __future__ import annotations

from datetime import date, datetime
import re
from typing import Any, Dict, List, Mapping, Optional

_TIME_PRECISIONS = {"second", "minute", "hour", "day", "month", "year", "unknown"}
_ARTICLE_DATE_PRECISIONS = {"day", "month", "year", "unknown"}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?$"
)

_TOP_LEVEL_FIELDS = {
    "unique_key", "article_date_iso", "article_date_precision", "article_title",
    "Event_Summary", "facet", "core_entities", "locations", "date_range",
    "Event", "Person", "Involved_Parties", "Impact", "Event_Timeline",
    "evidence_snippets", "importance", "update_time_ai",
}
_EVENT_FIELDS = {
    "event_id", "subject", "object", "aspect", "medium", "action",
    "time_iso", "time_raw", "time_precision", "location",
    "consequence", "relation", "source",
}
_LINKED_FIELDS = {
    "Person": {"event_ids", "name", "role", "action", "quote", "stance", "relation"},
    "Involved_Parties": {"event_ids", "party_name", "party_role"},
    "Impact": {"event_ids", "impact_description"},
    "Event_Timeline": {"event_ids", "time_iso", "time_raw", "time_precision", "description"},
    "evidence_snippets": {
        "event_ids", "text", "source_id", "char_start", "char_end",
        "paragraph_id", "sentence_index", "confidence",
    },
}
_IMPORTANCE_FIELDS = {"coverage", "novelty", "impact", "credibility", "importance_score"}
_DATE_RANGE_FIELDS = {"start", "end"}


def _require_list(value: Any, path: str) -> List[Any]:
    if not isinstance(value, list):
        raise TypeError(f"{path} must be a JSON array; got {type(value).__name__}")
    return value


def _require_object(value: Any, path: str) -> Dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{path} must be a JSON object; got {type(value).__name__}")
    return value


def _reject_unknown_fields(obj: Mapping[str, Any], allowed: set[str], path: str) -> None:
    extra = sorted(set(obj.keys()) - allowed)
    if extra:
        raise ValueError(f"{path} contains fields not present in the current schema: {extra}")


def _validate_optional_string(value: Any, path: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{path} must be a string or null; got {type(value).__name__}")
    return value


def _validate_string_list(value: Any, path: str) -> List[str]:
    rows = _require_list(value, path)
    out: List[str] = []
    for i, raw in enumerate(rows):
        if not isinstance(raw, str):
            raise TypeError(f"{path}[{i}] must be a string; got {type(raw).__name__}")
        out.append(raw)
    return out


def _normalize_date_only(value: Any, path: str) -> Optional[str]:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{path} must be YYYY-MM-DD or null")
    s = value.strip()
    if not _DATE_RE.fullmatch(s):
        raise ValueError(f"{path} must use YYYY-MM-DD; got {value!r}")
    try:
        date.fromisoformat(s)
    except ValueError as exc:
        raise ValueError(f"{path} is not a valid calendar date: {value!r}") from exc
    return s


def _normalize_time_iso(value: Any, path: str) -> Optional[str]:
    """Format-only normalization; never infer a missing date or timezone.

    Accepted:
    - YYYY-MM-DD
    - YYYY-MM-DDTHH:MM:SS[.fraction][Z|+HH:MM|-HH:MM]
    - same datetime with one ASCII space instead of T; this is safely normalized to T.
    """
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(f"{path} must be an ISO date/datetime string or null")
    s = value.strip()
    if _DATE_RE.fullmatch(s):
        return _normalize_date_only(s, path)
    if not _DATETIME_RE.fullmatch(s):
        raise ValueError(f"{path} is not a supported ISO date/datetime: {value!r}")
    if s[10] == " ":
        s = s[:10] + "T" + s[11:]
    try:
        datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{path} is not a valid ISO datetime: {value!r}") from exc
    return s


def _validate_time_fields(obj: Dict[str, Any], path: str) -> None:
    for field in ("time_raw", "time_iso", "time_precision"):
        if field not in obj:
            raise ValueError(f"{path}.{field} is required by the current schema")

    obj["time_raw"] = _validate_optional_string(obj.get("time_raw"), f"{path}.time_raw")
    obj["time_iso"] = _normalize_time_iso(obj.get("time_iso"), f"{path}.time_iso")

    precision = obj.get("time_precision")
    if not isinstance(precision, str) or precision not in _TIME_PRECISIONS:
        raise ValueError(
            f"{path}.time_precision must be one of {sorted(_TIME_PRECISIONS)}; got {precision!r}"
        )

    time_iso = obj.get("time_iso")
    if time_iso is None:
        # This is valid for e.g. time_raw='0504', precision='minute' when no safe date exists.
        return

    is_datetime = "T" in time_iso
    if precision in {"second", "minute", "hour"} and not is_datetime:
        raise ValueError(f"{path}: precision={precision!r} requires a datetime time_iso")
    if precision in {"day", "month", "year"} and is_datetime:
        raise ValueError(f"{path}: precision={precision!r} requires a date-only time_iso")
    if precision == "unknown":
        raise ValueError(f"{path}: time_iso must be null when time_precision='unknown'")

    if is_datetime:
        parsed = datetime.fromisoformat(time_iso.replace("Z", "+00:00"))
        if precision == "hour" and (parsed.minute != 0 or parsed.second != 0 or parsed.microsecond != 0):
            raise ValueError(f"{path}: hour precision requires MM:SS = 00:00")
        if precision == "minute" and (parsed.second != 0 or parsed.microsecond != 0):
            raise ValueError(f"{path}: minute precision requires seconds = 00")
    else:
        parsed_date = date.fromisoformat(time_iso)
        if precision == "month" and parsed_date.day != 1:
            raise ValueError(f"{path}: month precision requires normalized day 01")
        if precision == "year" and (parsed_date.month != 1 or parsed_date.day != 1):
            raise ValueError(f"{path}: year precision requires normalized date YYYY-01-01")


def _validate_article_date(item: Dict[str, Any], path: str) -> None:
    if "article_date_iso" not in item or "article_date_precision" not in item:
        raise ValueError(f"{path}.article_date_iso and article_date_precision are required")
    item["article_date_iso"] = _normalize_date_only(item.get("article_date_iso"), f"{path}.article_date_iso")
    precision = item.get("article_date_precision")
    if not isinstance(precision, str) or precision not in _ARTICLE_DATE_PRECISIONS:
        raise ValueError(
            f"{path}.article_date_precision must be one of {sorted(_ARTICLE_DATE_PRECISIONS)}; got {precision!r}"
        )
    value = item.get("article_date_iso")
    if value is None:
        if precision != "unknown":
            raise ValueError(f"{path}: null article_date_iso requires article_date_precision='unknown'")
        return
    if precision == "unknown":
        raise ValueError(f"{path}: non-null article_date_iso cannot use precision='unknown'")
    parsed = date.fromisoformat(value)
    if precision == "month" and parsed.day != 1:
        raise ValueError(f"{path}: month article precision requires day 01")
    if precision == "year" and (parsed.month != 1 or parsed.day != 1):
        raise ValueError(f"{path}: year article precision requires YYYY-01-01")


def _validate_event_ids(value: Any, *, valid_ids: set[str], path: str) -> List[str]:
    ids = _require_list(value, path)
    out: List[str] = []
    seen: set[str] = set()
    for i, raw in enumerate(ids):
        if not isinstance(raw, str) or not raw.strip():
            raise TypeError(f"{path}[{i}] must be a non-empty string")
        event_id = raw.strip()
        if event_id in seen:
            raise ValueError(f"{path} contains duplicate event_id {event_id!r}")
        if event_id not in valid_ids:
            raise ValueError(f"{path} references missing Event.event_id {event_id!r}")
        seen.add(event_id)
        out.append(event_id)
    return out


def _validate_object_list(value: Any, *, path: str) -> List[Dict[str, Any]]:
    rows = _require_list(value, path)
    return [dict(_require_object(row, f"{path}[{i}]")) for i, row in enumerate(rows)]


def normalize_multidim_event_payload(payload: Any, **_: Any) -> Any:
    items = _require_list(payload, "multidim_event_json")
    out: List[Dict[str, Any]] = []

    for block_index, raw_item in enumerate(items):
        path = f"multidim_event_json[{block_index}]"
        item = dict(_require_object(raw_item, path))
        _reject_unknown_fields(item, _TOP_LEVEL_FIELDS, path)
        _validate_article_date(item, path)

        for field in ("facet", "core_entities", "locations"):
            if field in item:
                item[field] = _validate_string_list(item[field], f"{path}.{field}")

        if "Event" not in item:
            raise ValueError(f"{path}.Event is required by the current schema")
        events = _validate_object_list(item["Event"], path=f"{path}.Event")

        valid_event_ids: set[str] = set()
        normalized_events: List[Dict[str, Any]] = []
        for event_index, event in enumerate(events):
            epath = f"{path}.Event[{event_index}]"
            _reject_unknown_fields(event, _EVENT_FIELDS, epath)
            event_id = event.get("event_id")
            if not isinstance(event_id, str) or not event_id.strip():
                raise ValueError(f"{epath}.event_id must be a non-empty string")
            event_id = event_id.strip()
            if event_id in valid_event_ids:
                raise ValueError(f"{path}.Event contains duplicate event_id {event_id!r}")
            valid_event_ids.add(event_id)
            event["event_id"] = event_id
            _validate_time_fields(event, epath)
            # The ES contract maps consequence as text.  Validate it at the
            # profile boundary so an LLM that accidentally emits an Impact-like
            # object is reported as a schema-adherence failure before bulk I/O.
            if "consequence" in event:
                event["consequence"] = _validate_optional_string(
                    event.get("consequence"), f"{epath}.consequence"
                )
            normalized_events.append(event)
        item["Event"] = normalized_events

        for field_name, allowed_fields in _LINKED_FIELDS.items():
            rows = _validate_object_list(item.get(field_name, []), path=f"{path}.{field_name}")
            normalized_rows: List[Dict[str, Any]] = []
            for row_index, row in enumerate(rows):
                rpath = f"{path}.{field_name}[{row_index}]"
                _reject_unknown_fields(row, allowed_fields, rpath)
                if "event_ids" not in row:
                    raise ValueError(f"{rpath}.event_ids is required by the current schema")
                row["event_ids"] = _validate_event_ids(
                    row.get("event_ids"), valid_ids=valid_event_ids, path=f"{rpath}.event_ids"
                )
                if field_name == "Event_Timeline":
                    _validate_time_fields(row, rpath)
                normalized_rows.append(row)
            item[field_name] = normalized_rows

        if "importance" in item:
            importance = dict(_require_object(item["importance"], f"{path}.importance"))
            _reject_unknown_fields(importance, _IMPORTANCE_FIELDS, f"{path}.importance")
            for key, value in importance.items():
                if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
                    raise TypeError(f"{path}.importance.{key} must be integer or null")
            item["importance"] = importance

        if "date_range" in item:
            date_range = dict(_require_object(item["date_range"], f"{path}.date_range"))
            _reject_unknown_fields(date_range, _DATE_RANGE_FIELDS, f"{path}.date_range")
            for key in ("start", "end"):
                if key in date_range:
                    date_range[key] = _normalize_date_only(date_range.get(key), f"{path}.date_range.{key}")
            item["date_range"] = date_range

        out.append(item)

    return out
