"""Built-in ES output profile for multidimensional event payloads."""

from __future__ import annotations

import re
from typing import Any, Optional, Tuple


def normalize_date_value(value: str) -> Tuple[Optional[str], Optional[str]]:
    """Normalize YYYY-MM-DD / YYYY-MM / YYYY strings to ES-friendly dates."""
    if not isinstance(value, str):
        return (None, None)
    text = value.strip()
    if re.match(r"^\d{4}-\d{2}-\d{2}$", text):
        return (text, "day")
    if re.match(r"^\d{4}-\d{2}$", text):
        return (text + "-01", "month")
    if re.match(r"^\d{4}$", text):
        return (text + "-01-01", "year")
    return (None, None)


def _clean_list_of_objects(value: Any) -> list:
    """Return only object entries accepted by ES nested/object-array mappings."""
    if value is None:
        return []
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [entry for entry in value if isinstance(entry, dict)]


def _clean_object(value: Any) -> dict:
    return value if isinstance(value, dict) else {}

def normalize_multidim_event_payload(payload: Any, **_: Any) -> Any:
    """Normalize legacy multidimensional event payloads before ES writeback.

    Handles only the legacy list[dict] event schema:
    - Event.time -> Event.time_raw / Event.time_iso / Event.time_precision
    - date_range.start/end -> *_raw / *_precision and normalized start/end
    - Event_Timeline[].date -> date_raw / date_iso / date_precision
    """
    try:
        if not isinstance(payload, list):
            return payload

        out = []
        for item in payload:
            if not isinstance(item, dict):
                out.append(item)
                continue
            obj = dict(item)

            # ES mapping declares these fields as nested/object structures.  LLM
            # output may contain nulls or scalar placeholders; sending those values
            # causes document_parsing_exception even though the bulk request itself
            # is accepted.  Normalize invalid structural values before writeback.
            for key in ("Person", "Involved_Parties", "Impact", "Event_Timeline", "evidence_snippets"):
                if key in obj:
                    obj[key] = _clean_list_of_objects(obj.get(key))
            for key in ("Event", "importance", "date_range"):
                if key in obj:
                    obj[key] = _clean_object(obj.get(key))

            event = obj.get("Event")
            if isinstance(event, dict):
                time_value = event.get("time")
                if isinstance(time_value, str):
                    event.setdefault("time_raw", time_value)
                    iso, precision = normalize_date_value(time_value)
                    if iso:
                        event["time_iso"] = iso
                        event["time_precision"] = precision

            date_range = obj.get("date_range")
            if isinstance(date_range, dict):
                for key in ("start", "end"):
                    value = date_range.get(key)
                    if isinstance(value, str):
                        date_range.setdefault(f"{key}_raw", value)
                        iso, precision = normalize_date_value(value)
                        if iso:
                            date_range[key] = iso
                            date_range[f"{key}_precision"] = precision

            timeline = obj.get("Event_Timeline")
            if isinstance(timeline, list):
                new_timeline = []
                for step in timeline:
                    if isinstance(step, dict):
                        step = dict(step)
                        date_value = step.get("date")
                        if isinstance(date_value, str):
                            step.setdefault("date_raw", date_value)
                            iso, precision = normalize_date_value(date_value)
                            if iso:
                                step["date_iso"] = iso
                                step["date_precision"] = precision
                    new_timeline.append(step)
                obj["Event_Timeline"] = new_timeline

            out.append(obj)
        return out
    except Exception:
        return payload
