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
