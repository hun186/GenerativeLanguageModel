"""Strategies for merging dictionary results produced by document slices."""

import json
from typing import Any, Dict, List, Optional, Tuple


def should_merge_slices(ctx) -> bool:
    """
    只有在 ctx.merge_slices=True（或等價設定）時才啟用切片合併。
    """
    # 你也可以支援多種開關名稱，方便相容既有設定：
    return bool(
        getattr(ctx, "merge_slices", False) or
        getattr(ctx, "enable_slice_merge", False) or
        (getattr(ctx, "merge_strategy", "").lower() in {"dict_deep", "slice_merge", "on"})
    )

def is_multidim_event_slice_merge(ctx, output_col=None) -> bool:
    """Resolve the profile of the ACTUAL selected output, not any other rule.

    A multi-field job may have generic JSON alongside multidim_event_json.
    Never rewrite generic Event values merely because another field happens
    to opt into the strict multidimensional-event profile.
    """
    profile_aliases = {"multidim_event", "multi_dim_event", "multidim", "event"}
    default_col = str(getattr(ctx, "output_col", "") or "").strip()
    selected = str(output_col or "").strip()
    rules = []
    for key in ("es_writeback_rules", "sql_writeback_rules"):
        group = getattr(ctx, key, None) or []
        if isinstance(group, list):
            rules.extend(rule for rule in group if isinstance(rule, dict))
    names = {
        str(rule.get("output_col", "") or "").strip()
        for rule in rules if str(rule.get("output_col", "") or "").strip()
    }
    if not selected:
        # A single explicit writeback rule overrides a generic primary column.
        # Ambiguous multi-rule setups must select a REAL destination rather
        # than globally upgrading an unrelated source field.
        selected = next(iter(names)) if len(names) == 1 else default_col
        if len(names) > 1 and selected not in names:
            return False
    if not selected:
        return False

    matching = [
        rule for rule in rules
        if str(rule.get("output_col", "") or "").strip() == selected
    ]
    profile = (
        matching[0].get("output_profile", getattr(ctx, "output_profile", None))
        if matching else getattr(ctx, "output_profile", None)
    )
    profile_name = str(profile or "auto").strip().lower().replace("-", "_")
    return (
        profile_name in profile_aliases
        or (profile_name in {"auto", "default"}
            and selected.lower() == "multidim_event_json")
    )


def _reconcile_multidim_event_slice_ids(items: List[dict]) -> List[dict]:
    """Assign globally unique IDs before concatenating independently named events.

    LLM slices independently start numbering E1/E2. Never remap a collision
    without also changing the SAME slice's event_ids references. Existing
    event labels, future-slice labels, and first occurrence are preserved.
    A duplicate ID *inside* one slice is ambiguous and must fail closed.
    """
    from copy import deepcopy

    linked_fields = (
        "Person", "Involved_Parties", "Impact", "Event_Timeline", "evidence_snippets",
    )
    reserved = set()

    def reserve_references(value):
        if isinstance(value, list):
            for entry in value:
                reserve_references(entry)
        elif isinstance(value, dict):
            ids = value.get("event_ids")
            if isinstance(ids, list):
                reserved.update(eid.strip() for eid in ids if isinstance(eid, str)
                                and eid.strip())
            for key, entry in value.items():
                if key != "event_ids":
                    reserve_references(entry)

    for item in items:
        events = item.get("Event")
        if isinstance(events, list):
            for event in events:
                if isinstance(event, dict) and isinstance(event.get("event_id"), str):
                    reserved.add(event["event_id"].strip())
        for name in linked_fields:
            if name in item:
                reserve_references(item[name])

    # The strict article profile never permits an event_ids link to an event
    # defined only by another chunk. Validate each chunk independently BEFORE
    # any rename, otherwise a dangling reference may accidentally resolve
    # to an unrelated event from a later chunk.
    def check_linked_ids(value, declared, slice_index, field):
        if isinstance(value, list):
            for entry in value:
                check_linked_ids(entry, declared, slice_index, field)
        elif isinstance(value, dict):
            ids = value.get("event_ids")
            if isinstance(ids, list):
                for event_id in ids:
                    if (isinstance(event_id, str) and event_id.strip()
                            and event_id.strip() not in declared):
                        raise ValueError(
                            f"multidim slice {slice_index} {field} references "
                            f"missing local Event.event_id {event_id.strip()!r}"
                        )
            for key, entry in value.items():
                if key != "event_ids":
                    check_linked_ids(entry, declared, slice_index, field)

    for slice_index, item in enumerate(items):
        declared = {
            event["event_id"].strip()
            for event in (item.get("Event") if isinstance(item.get("Event"), list) else [])
            if isinstance(event, dict) and isinstance(event.get("event_id"), str)
            and event["event_id"].strip()
        }
        for name in linked_fields:
            if name in item:
                check_linked_ids(item[name], declared, slice_index, name)

    assigned = set()
    next_id = 1
    out = []

    for index, original in enumerate(items):
        item = deepcopy(original)
        events = item.get("Event")
        replacements = {}
        within_slice = set()
        if isinstance(events, list):
            for event in events:
                if not isinstance(event, dict):
                    continue  # The strict output profile rejects malformed Event rows.
                old = event.get("event_id")
                if not isinstance(old, str) or not old.strip():
                    continue  # Do not manufacture missing IDs.
                old = old.strip()
                if old in within_slice:
                    raise ValueError(
                        f"multidim Event duplicate event_id {old!r} inside slice {index}"
                    )
                within_slice.add(old)
                if old in assigned:
                    while f"E{next_id}" in reserved or f"E{next_id}" in assigned:
                        next_id += 1
                    new = f"E{next_id}"
                    next_id += 1
                    replacements[old] = new
                    event["event_id"] = new
                    assigned.add(new)
                else:
                    event["event_id"] = old
                    assigned.add(old)

        if replacements:
            def update_refs(value):
                if isinstance(value, list):
                    for entry in value:
                        update_refs(entry)
                elif isinstance(value, dict):
                    ids = value.get("event_ids")
                    if isinstance(ids, list):
                        value["event_ids"] = [
                            replacements.get(eid.strip(), eid.strip())
                            if isinstance(eid, str) else eid
                            for eid in ids
                        ]
                    for key, entry in value.items():
                        if key != "event_ids":
                            update_refs(entry)

            for name in linked_fields:
                if name in item:
                    update_refs(item[name])
        out.append(item)
    return out


def merge_dict_slices(dict_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """將多個切片（list[dict]）深度合併成單一 dict。
    規則：
      - list + list：串接（如需去重，自行改成 dict.fromkeys）
      - dict + dict：遞迴合併
      - 標量衝突：保留左側（第一個非空），若要改為以右側覆蓋可自行調整
    """
    def _merge(a, b):
        if a is None: return b
        if b is None: return a
        if isinstance(a, list) and isinstance(b, list):
            return a + b
        if isinstance(a, dict) and isinstance(b, dict):
            out = dict(a)
            for k, v in b.items():
                out[k] = _merge(out.get(k), v)
            return out
        # 標量衝突：保留 a（若 a 為空字串/None，改採 b）
        return a if a not in ("", None) else b

    agg: Dict[str, Any] = {}
    for d in dict_list:
        if isinstance(d, dict):
            agg = _merge(agg, d)
    return agg


def merge_dict_slices_audited(
    dict_list: List[dict],
    *,
    conflict_policy: str = "prefer_left",        # "prefer_left" | "prefer_right" | "longer_str" | "non_empty"
    dedup_lists: bool = False,                   # True 時，list 會去重（以 JSON 字串為 key）
    audit: bool = True,                          # 回傳 report
    #logger: Optional[callable] = None,           # 例如 tlog_warn
    logger: Optional[callable] = print,
    max_log: int = 10,                           # 最多列出幾筆細節
    multidim_event: bool = False,                # ES article Event/event_ids reconciliation
) -> Tuple[dict, Dict[str, Any]]:
    """
    與 merge_dict_slices 規則相同，但產出審計報告：
      - 記錄 list 串接、list 去重、型別不一致、標量衝突 等事件
      - 依 conflict_policy 決定標量衝突時的取捨
    report：
      {
        "changed": bool,
        "counts": {"list_concat": int, "list_dedup_removed": int, "scalar_conflict": int, "type_mismatch": int},
        "samples": [ { "action": str, "path": "a.b.c", "chosen": "left|right|other", "left_short": str, "right_short": str } ... ],
      }
    """

    counts = {"list_concat": 0, "list_dedup_removed": 0, "scalar_conflict": 0, "type_mismatch": 0}
    samples: List[Dict[str, Any]] = []
    def _shorten(x, n=160):
        try:
            s = x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)
        except Exception:
            s = str(x)
        return s if len(s) <= n else s[:n] + f"...(+{len(s)-n} chars)"

    def _choose_scalar(a, b):
        if conflict_policy == "prefer_right": return b
        if conflict_policy == "longer_str":
            sa = len(str(a)) if a is not None else -1
            sb = len(str(b)) if b is not None else -1
            return a if sa >= sb else b
        if conflict_policy == "non_empty":
            if a not in ("", None): return a
            return b
        # default: prefer_left
        return a if a not in ("", None) else b

    def _log_sample(action, path, chosen, left, right):
        if len(samples) < max_log:
            samples.append({
                "action": action,
                "path": path,
                "chosen": chosen,
                "left_short": _shorten(left),
                "right_short": _shorten(right),
            })

    def _merge(a, b, path: List[str]):
        if a is None: return b
        if b is None: return a

        # list + list
        if isinstance(a, list) and isinstance(b, list):
            counts["list_concat"] += 1
            merged = a + b
            if dedup_lists:
                seen = set()
                deduped = []
                removed = 0
                for it in merged:
                    try:
                        key = json.dumps(it, ensure_ascii=False, sort_keys=True)
                    except Exception:
                        key = str(it)
                    if key in seen:
                        removed += 1
                        continue
                    seen.add(key)
                    deduped.append(it)
                if removed:
                    counts["list_dedup_removed"] += removed
                    _log_sample("list_dedup", ".".join(path), "other", f"{len(merged)} items", f"-{removed} dup")
                return deduped
            return merged

        # dict + dict
        if isinstance(a, dict) and isinstance(b, dict):
            out = dict(a)
            for k, v in b.items():
                out[k] = _merge(out.get(k), v, path + [k])
            return out

        # 型別不一致
        if type(a) is not type(b):
            counts["type_mismatch"] += 1
            _log_sample("type_mismatch", ".".join(path), "left", a, b)
            return a  # 與原規則一致（保留左）；如需覆蓋改為 return b

        # 標量衝突
        if a != b:
            counts["scalar_conflict"] += 1
            chosen = _choose_scalar(a, b)
            _log_sample("scalar_conflict", ".".join(path),
                        "left" if chosen is a else ("right" if chosen is b else "other"),
                        a, b)
            return chosen

        return a  # 相等

    # --- 自動解析字串 ---
    if isinstance(dict_list, str):
        try:
            dict_list = json.loads(dict_list)
        except Exception:
            if logger:
                logger("[merge] 輸入是字串且非合法 JSON，回傳空合併。")
            return ({}, {"changed": False, "counts": {}, "samples": []})
    # --- 型別檢查 ---
    if not (isinstance(dict_list, list) and all(isinstance(x, dict) for x in dict_list)):
        if logger:
            logger("[merge] 輸入不是 list[dict]，回傳空合併。")
        return ({}, {"changed": False, "counts": {}, "samples": []})

    #print("input dict_list in merge_dict_slices_audited",dict_list)

    if multidim_event:
        dict_list = _reconcile_multidim_event_slice_ids(dict_list)

    agg: Dict[str, Any] = {}
    for d in dict_list:
        if isinstance(d, dict):
            agg = _merge(agg, d, [])

    changed = any(v > 0 for v in counts.values())
    report = {"changed": changed, "counts": counts, "samples": samples}

    # 可選：總結性 log
    if logger and changed:
        logger(f"[merge] 變更摘要 counts={counts}（samples 顯示至多 {max_log} 筆）")
        for s in samples:
            logger(f"[merge] {s['action']} @{s['path']} → {s['chosen']} | L={s['left_short']} | R={s['right_short']}")
    #print("returned agg in merge_dict_slices_audited",agg)
    #print("report",report)
    return (agg, report) if audit else (agg, {})
