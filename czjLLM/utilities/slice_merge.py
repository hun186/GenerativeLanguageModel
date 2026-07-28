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
