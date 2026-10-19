# sql_mode/runtime/row_merger_generic.py
import os, time, json, shutil
from datetime import datetime
from typing import Iterable, Tuple, Any, Optional, List, Dict

from czjLLM.prompt_pipeline.pending_central import mark_not_running, record_adjustment
from czjLLM.es_mode.output_profiles import OutputProfileValidationError
from czjLLM.job_manager.console_ui import tlog, tlog_warn
from czjLLM.utilities.combine_utils import merge_dict_slices
from czjLLM.utilities.combine_utils import merge_dict_slices_audited
from czjLLM.utilities.combine_utils import should_merge_slices
from czjLLM.utilities.slice_merge import (
    MultidimEventReferenceError, is_multidim_event_slice_merge,
    needs_per_output_slice_merge,
)
from utils.utilities_path import OSWALK, DirReplace, MKDIR, getPathFromFN
from utils.utilities_path import safe_move

from czjLLM.prompt_pipeline.pipeline_controller import (
    combine_api_finished_item, row_is_ready, meter_update
)
from czjLLM.utilities.path_utils import get_combined_result_path
from czjLLM.reduction.execution import ExecutionCancelled
from czjLLM.reduction.production_control import (
    ensure_production_observer, finish_legacy_merge_item,
    mark_legacy_merge_item_terminal, try_begin_legacy_merge_item,
    try_resume_materialized_legacy_merge_item,
)
from czjLLM.row_processors.flatten_utils import extract_json_list_for_flatten
from .multistage_writeback import resolve_writeback_payload
#from czjLLM.prompt_pipeline.pipeline_controller import meter_update  # 檔頭若尚未 import

DEFAULT_MAIN_SHEET_NAME = "LLM_result"
DEFAULT_OUTPUT_COL_NAME = "LLM_output"

'''
def _extract_json_list(result_text: str, allowed_fields: Optional[List[str]]) -> List[Dict[str, Any]]:
    # 與你 SQL 版一致：回傳「list[dict]」
    try:
        data = json.loads(result_text)
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list):
            return []
        out = []
        for obj in data:
            if not isinstance(obj, dict):
                continue
            if allowed_fields:
                out.append({k: obj.get(k) for k in allowed_fields if k in obj})
            else:
                out.append(obj)
        return out
    except Exception:
        return []
'''

def _counts(item_dir):
    todo = os.path.join(item_dir, "TODO")
    runn = os.path.join(item_dir, "RUNNING")
    succ = os.path.join(item_dir, "Success")
    return len(OSWALK(todo)), len(OSWALK(runn)), len(OSWALK(succ))



def _as_db_text(value):
    """資料庫主欄位一律寫入文字；dict/list 轉 JSON 字串。"""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    try:
        return json.dumps(value, ensure_ascii=False)
    except Exception:
        return str(value)


def _slice_merge_writeback_value(ctx, output_col: str, merged_payload: dict) -> str:
    """Serialize one field under its own output profile, never a sibling's."""
    is_multidim = is_multidim_event_slice_merge(ctx, output_col=output_col)
    return _as_db_text([merged_payload] if is_multidim else merged_payload)


def _apply_slice_merge_to_write_map(
    ctx,
    write_map: dict,
    source_text: str,
    merged_payload: dict,
    output_cols: Optional[Iterable[str]] = None,
    *,
    source_slices: Optional[list[dict]] = None,
    primary_multidim: bool = False,
) -> list[str]:
    """Merge every output column under its own semantic profile.

    Several output columns may consume the same source list yet require
    independent (generic vs Event-with-references) merge contracts. A single
    shared merged dict can neither safely feed both nor preserve all IDs.
    """
    allowed_cols = set(output_cols) if output_cols is not None else None
    cached_payloads = {primary_multidim: merged_payload}
    updated = []
    for output_col, value in list(write_map.items()):
        if allowed_cols is not None and output_col not in allowed_cols:
            continue
        if value != source_text:
            continue
        multidim = is_multidim_event_slice_merge(ctx, output_col=output_col)
        if source_slices is not None and multidim not in cached_payloads:
            candidate, _ = merge_dict_slices_audited(
                source_slices,
                conflict_policy=getattr(ctx, "merge_conflict_policy", "prefer_left"),
                dedup_lists=bool(getattr(ctx, "merge_dedup_lists", False)),
                audit=False,
                logger=None,
                multidim_event=multidim,
            )
            cached_payloads[multidim] = candidate
        output_payload = cached_payloads.get(multidim, merged_payload)
        write_map[output_col] = _slice_merge_writeback_value(
            ctx, output_col, output_payload,
        )
        updated.append(output_col)
    return updated


def _merge_deferred_writeback_sources(
    ctx, write_map: dict, write_sources: dict,
) -> list[str]:
    """Finish all deferred mixed-profile sources, not just the flatten source.

    The selected flatten field is historically merged earlier; other stage or
    combined sources may remain as unmerged chunk arrays. Group by resolved
    source identity AND actual source text so two unrelated stages cannot
    accidentally have their result records combined. Every destination gets
    its own profile-specific merge before the sink sees any update.
    """
    if not should_merge_slices(ctx):
        return []
    groups = {}
    for output_col, raw_text in list(write_map.items()):
        origin = str(write_sources.get(output_col, "") or "")
        source_kind = origin.split(":", 1)[0]
        if source_kind not in {"stage", "combined"}:
            continue
        if not needs_per_output_slice_merge(ctx, source=source_kind):
            continue
        groups.setdefault((origin, raw_text), []).append(output_col)

    changed = []
    for (_origin, source_text), output_cols in groups.items():
        try:
            rows = json.loads(source_text)
        except (TypeError, ValueError):
            continue
        if not (isinstance(rows, list) and len(rows) > 1
                and all(isinstance(row, dict) for row in rows)):
            continue
        first_col = output_cols[0]
        is_multidim = is_multidim_event_slice_merge(ctx, output_col=first_col)
        # Compute the first profile and derive the other destinations from
        # the SAME original rows, never from a previously remapped dict.
        merged, _ = merge_dict_slices_audited(
            rows,
            conflict_policy=getattr(ctx, "merge_conflict_policy", "prefer_left"),
            dedup_lists=bool(getattr(ctx, "merge_dedup_lists", False)),
            audit=False,
            logger=None,
            multidim_event=is_multidim,
        )
        changed.extend(_apply_slice_merge_to_write_map(
            ctx, write_map, source_text, merged,
            output_cols=output_cols, source_slices=rows,
            primary_multidim=is_multidim,
        ))
    return changed


def _apply_premerged_combined_slice_merge(ctx, write_map: dict, write_sources: dict) -> list[str]:
    """Apply the output contract to dicts already merged by the combiner.

    Only values resolved from the structured ``combined`` source qualify.  A
    stage-specific dict remains untouched so its output profile can reject an
    invalid top-level shape rather than having Row Merger silently repair it.
    """
    updated = []
    for output_col, source in write_sources.items():
        if source != "combined" or output_col not in write_map:
            continue
        source_text = write_map[output_col]
        try:
            payload = json.loads(source_text)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        updated.extend(
            _apply_slice_merge_to_write_map(
                ctx,
                write_map,
                source_text,
                payload,
                output_cols=[output_col],
            )
        )
    return updated



def _selected_slice_merge_output_col(ctx, write_map: dict, source_text: str) -> Optional[str]:
    """Match Row Merger's selected flatten input, including multi-rule order."""
    rules = getattr(ctx, "sql_writeback_rules", None)
    if isinstance(rules, list) and rules:
        index = int(getattr(ctx, "sql_flatten_writeback_rule", 0) or 0)
        if 0 <= index < len(rules) and isinstance(rules[index], dict):
            name = str(rules[index].get("output_col", "") or "").strip()
            if name and write_map.get(name) == source_text:
                return name
        # An invalid selector uses the raw combined fallback in
        # _build_writeback_values. No output profile can be inferred safely.
        return None
    name = str(getattr(ctx, "output_col", DEFAULT_OUTPUT_COL_NAME) or DEFAULT_OUTPUT_COL_NAME)
    return name if write_map.get(name) == source_text else None


def _build_writeback_values(ctx, comb_back_fn: str, combined_text: str):
    """回傳 (write_map, flatten_text, source_logs, write_sources)。"""
    rules = getattr(ctx, "sql_writeback_rules", None)
    write_map = {}
    source_logs = []
    write_sources = {}

    if isinstance(rules, list) and rules:
        flatten_idx = int(getattr(ctx, "sql_flatten_writeback_rule", 0) or 0)
        flatten_text = combined_text
        for idx, rule in enumerate(rules):
            if not isinstance(rule, dict):
                continue
            out_col = str(rule.get("output_col", "")).strip()
            if not out_col:
                continue
            mode = str(rule.get("source", rule.get("sql_writeback_source", "combined")) or "combined").strip().lower()
            stage = rule.get("stage", rule.get("sql_writeback_stage", None))

            class _RuleCtx:
                def __init__(self, base):
                    self.__dict__.update(getattr(base, "__dict__", {}))
            rule_ctx = _RuleCtx(ctx)
            rule_ctx.sql_writeback_source = mode
            rule_ctx.sql_writeback_stage = stage

            wb = resolve_writeback_payload(rule_ctx, comb_back_fn, combined_text)
            write_map[out_col] = _as_db_text(wb.main_payload)
            write_sources[out_col] = wb.source
            source_logs.append(f"{out_col}<-{wb.source}")
            if idx == flatten_idx:
                flatten_text = write_map[out_col]

        if write_map:
            return write_map, flatten_text, source_logs, write_sources

    wb = resolve_writeback_payload(ctx, comb_back_fn, combined_text)
    primary_col = str(getattr(ctx, "output_col", DEFAULT_OUTPUT_COL_NAME) or DEFAULT_OUTPUT_COL_NAME)
    write_map[primary_col] = _as_db_text(wb.main_payload)
    write_sources[primary_col] = wb.source
    source_logs.append(f"{primary_col}<-{wb.source}")
    return write_map, write_map[primary_col], source_logs, write_sources



def _expand_json_columns(ctx, source_text: str) -> dict:
    """依設定將 JSON 物件 key 展開為主表欄位（供資料庫查詢）。"""
    if not bool(getattr(ctx, "sql_expand_json_to_columns", False)):
        return {}
    try:
        data = json.loads(source_text)
    except Exception:
        return {}

    if isinstance(data, list):
        # 常見輸出為 list[dict]，先取第一筆代表（可配合 merge_slices 先整併）
        data = next((x for x in data if isinstance(x, dict)), {})
    if not isinstance(data, dict):
        return {}

    allow = getattr(ctx, "allowed_output_fields", None)
    if isinstance(allow, (list, tuple)) and allow:
        allow_set = {str(k).strip() for k in allow if str(k).strip()}
    else:
        allow_set = None

    prefix = str(getattr(ctx, "sql_expand_json_prefix", "") or "").strip()
    out = {}
    for k, v in data.items():
        key = str(k).strip()
        if not key:
            continue
        if allow_set is not None and key not in allow_set:
            continue
        col = f"{prefix}{key}" if prefix else key
        out[col] = _as_db_text(v)
    return out



def _build_flatten_subtable_name(ctx, output_col: str) -> str:
    normalized_output_col = str(output_col or "").strip() or DEFAULT_OUTPUT_COL_NAME

    target = str(getattr(ctx, "target_table", "") or "").strip()
    if not target:
        target = str(getattr(ctx, "target_sheet_name", "") or "").strip()
        if not target:
            target = DEFAULT_MAIN_SHEET_NAME
    if not target:
        # 最後才回退到主輸出欄名，避免把 LLM_result 當成跨情境的硬編碼預設。
        target = str(getattr(ctx, "output_col", "") or "").strip()

    if not target:
        return f"{normalized_output_col}_flattened"
    if normalized_output_col == target or normalized_output_col.startswith(f"{target}_"):
        return f"{normalized_output_col}_flattened"
    return f"{target}_{normalized_output_col}_flattened"

def _resolve_flatten_targets(ctx, write_map: dict, default_source_text: str) -> list[dict]:
    """
    回傳多來源 flatten 目標，每個元素包含：
      - output_col
      - source_text
      - allowed_fields
      - save_raw_input
      - subtable_name
    """
    if not bool(getattr(ctx, "flatten_json_output", False)):
        return []

    rules = getattr(ctx, "sql_writeback_rules", None) or []
    rule_output_cols = []
    for r in rules:
        if isinstance(r, dict):
            c = str(r.get("output_col", "")).strip()
            if c:
                rule_output_cols.append(c)

    cfg_targets = getattr(ctx, "sql_flatten_writeback_rules", None)
    targets = []

    if isinstance(cfg_targets, list) and cfg_targets:
        default_allowed_raw = getattr(ctx, "allowed_output_fields", None)
        if isinstance(default_allowed_raw, (list, tuple)):
            default_allowed_fields = [str(f).strip() for f in default_allowed_raw if str(f).strip()]
            if not default_allowed_fields:
                default_allowed_fields = None
        else:
            default_allowed_fields = None
        for item in cfg_targets:
            if not isinstance(item, dict):
                continue
            if not bool(item.get("enabled", True)):
                continue
            try:
                idx = int(item.get("writeback_rule", 0) or 0)
            except Exception:
                idx = 0
            if idx < 0:
                idx = 0
            out_col = rule_output_cols[idx] if idx < len(rule_output_cols) else str(getattr(ctx, "output_col", "") or "")
            source_text = write_map.get(out_col, default_source_text)
            allowed = item.get("allowed_output_fields", None)
            if isinstance(allowed, (list, tuple)):
                allowed_fields = [str(f).strip() for f in allowed if str(f).strip()]
                if not allowed_fields:
                    allowed_fields = None
            else:
                # 相容舊行為：若未在 rule 內指定，沿用全域 allowed_output_fields
                allowed_fields = default_allowed_fields
            save_raw = item.get(
                "save_raw_input_when_flatten",
                item.get(
                    "flatten_store_input_col",
                    item.get("save_input_col_when_flatten", getattr(ctx, "save_raw_input_when_flatten", False)),
                ),
            )
            targets.append(
                {
                    "output_col": out_col,
                    "source_text": source_text,
                    "allowed_fields": allowed_fields,
                    "save_raw_input": bool(save_raw),
                    "subtable_name": _build_flatten_subtable_name(ctx, out_col),
                }
            )
        # 若明確提供新參數，回傳其結果（可為空，代表全部關閉）
        return targets

    # backward-compatible：單一來源
    raw_fields = getattr(ctx, "allowed_output_fields", None)
    if isinstance(raw_fields, (list, tuple)):
        allowed_fields = [str(f).strip() for f in raw_fields if f is not None and str(f).strip() != ""]
        if not allowed_fields:
            allowed_fields = None
    else:
        allowed_fields = None

    out_col = str(getattr(ctx, "output_col", DEFAULT_OUTPUT_COL_NAME) or DEFAULT_OUTPUT_COL_NAME)
    return [
        {
            "output_col": out_col,
            "source_text": default_source_text,
            "allowed_fields": allowed_fields,
            "save_raw_input": bool(getattr(ctx, "save_raw_input_when_flatten", False)),
            "subtable_name": _build_flatten_subtable_name(ctx, out_col),
        }
    ]


def _process_flatten_target(ctx, sink, pk, ft: dict) -> bool:
    """
    單一 flatten target 寫回流程。
    回傳 True 代表有成功寫入展平列；False 代表僅完成 schema 或略過寫入。
    """
    old_ctx = sink.ctx

    class _FlattenCtx:
        def __init__(self, base, **overrides):
            self.__dict__.update(getattr(base, "__dict__", {}))
            self.__dict__.update(overrides)

    sink.ctx = _FlattenCtx(
        old_ctx,
        output_col=ft["output_col"],
        subtable_name=ft["subtable_name"],
        allowed_output_fields=ft["allowed_fields"] or [],
        save_raw_input_when_flatten=ft["save_raw_input"],
    )
    try:
        # 即使沒有可展平列，也先建立對應子表，避免「rule 啟用但子表不存在」。
        sink.ensure_flatten_schema(ft["allowed_fields"])
        # Excel 會在 ensure_flatten_schema 內做 sheet 名 sanitize；後續寫入需使用同名。
        ft["subtable_name"] = getattr(sink.ctx, "subtable_name", ft["subtable_name"])
    finally:
        sink.ctx = old_ctx

    try:
        result_list = extract_json_list_for_flatten(ft["source_text"], ft["allowed_fields"])
    except Exception as ex:
        tlog_warn(f"⚠️ 解析展平欄位失敗（pk={pk}, col={ft['output_col']}）：{ex}")
        result_list = None

    if not result_list:
        return False

    sink.ctx = _FlattenCtx(
        old_ctx,
        output_col=ft["output_col"],
        subtable_name=ft["subtable_name"],
        allowed_output_fields=ft["allowed_fields"] or [],
        save_raw_input_when_flatten=ft["save_raw_input"],
    )
    try:
        wants_raw = bool(ft["save_raw_input"])
        input_col_name = getattr(ctx, "input_col", None)
        has_input_col = isinstance(input_col_name, str) and bool(input_col_name.strip())
        needs_raw_input = (
            wants_raw
            and has_input_col
            and (getattr(ctx, "primary_key", None) != input_col_name)
        )
        sub_input_col = input_col_name if needs_raw_input else None
        input_val = sink.fetch_input(pk) if needs_raw_input else None
        sink.write_flatten(
            pk,
            result_list,
            save_raw_input=needs_raw_input,
            input_col=sub_input_col,
            input_value=input_val,
        )
        return True
    except Exception as ex:
        tlog_warn(f"⚠️ 子表寫回失敗（pk={pk}, col={ft['output_col']}）：{ex}")
        return False
    finally:
        sink.ctx = old_ctx

def _all_slices_done(item_dir, meta=None):
    t, r, s = _counts(item_dir)
    # 若能從 meta 帶入期望切片數（例如 produce_rows 時存的 chunks），再加一道保險
    expected = None
    try:
        expected = int(meta.get("chunks") or meta.get("slice_count") or 0) or None
    except Exception:
        expected = None
    # 全部完成的嚴格條件
    cond = (t == 0) and (r == 0) and (s > 0)
    if expected is not None:
        cond = cond and (s >= expected)
    return cond


def _is_terminal_schema_writeback_error(exc: Exception) -> bool:
    """Return whether retrying the unchanged result cannot make it valid.

    Keep this deliberately narrow: transport/ES availability errors must stay
    retryable, while an output-profile unknown-field rejection is a property of
    the completed LLM payload and will be identical on every watchdog scan.
    """
    return isinstance(exc, (OutputProfileValidationError, MultidimEventReferenceError)) or (
        # Compatibility for sinks/plugins that still raise the former error.
        isinstance(exc, ValueError)
        and "contains fields not present in the current schema" in str(exc)
    )


def row_merger_watchdog_generic(ctx, registry, meter_fn, stop_event, sink,
                                scan_interval=0.5, done_q=None):
    # 只在 TODO/Success 計數有變化時才印一次
    if not hasattr(row_merger_watchdog_generic, "_last_state"):
        row_merger_watchdog_generic._last_state = {}
    if not hasattr(row_merger_watchdog_generic, "_stage_wait_logged"):
        row_merger_watchdog_generic._stage_wait_logged = set()
    # A completed result that deterministically fails schema validation is
    # revisited on every watchdog scan.  Keep retry semantics (an operator may
    # repair the file), but do not print the identical error several times per
    # second.  A periodic reminder preserves observability for long runs.
    failure_log_state = {}
    # Slice conflicts describe the completed artifact, not a writeback attempt.
    # If a retryable sink error keeps this item in the registry, recompute the
    # merge as needed but do not print the same audit block on every scan.
    merge_log_emitted_items = set()
    legacy_merge_telemetry_state = {}
    observer = ensure_production_observer(ctx)

    def _legacy_merge_begin(item_dir):
        if not should_merge_slices(ctx):
            return False
        if legacy_merge_telemetry_state.get(item_dir) == "completed":
            return False
        if legacy_merge_telemetry_state.get(item_dir) == "started":
            return True
        if try_begin_legacy_merge_item(ctx, item_dir):
            observer.emit("legacy_merge_started", {})
            legacy_merge_telemetry_state[item_dir] = "started"
            return True
        if try_resume_materialized_legacy_merge_item(ctx, item_dir):
            # Fallback already emitted the single started event. Adopt its
            # materialized artifact without double-counting the attempt.
            legacy_merge_telemetry_state[item_dir] = "started"
            return True
        return False

    def _legacy_merge_finish(item_dir, *, success, reason="execution_error", error_type=None):
        if legacy_merge_telemetry_state.get(item_dir) != "started":
            return
        if not success and error_type == MultidimEventReferenceError.__name__:
            # A deterministic source-slice FK failure cannot be repaired by
            # retrying the same Success files. Keep the shared merge claim
            # terminal BEFORE the outer handler removes the registry item:
            # otherwise fallback can reclaim it and count this failure twice.
            mark_legacy_merge_item_terminal(ctx, item_dir)
        finish_legacy_merge_item(ctx, item_dir, success=success)
        if success:
            observer.emit("legacy_merge_completed", {})
            legacy_merge_telemetry_state[item_dir] = "completed"
        else:
            fields = {"reason": reason}
            if error_type:
                fields["error_type"] = error_type
            observer.emit("legacy_merge_failed", fields)
            legacy_merge_telemetry_state.pop(item_dir, None)

    failure_log_interval = max(
        1.0, float(getattr(ctx, "row_merger_failure_log_interval", 60.0) or 60.0)
    )

    def _release_terminal_schema_failure(item_dir, pk, exc, combined_path):
        """Fail completed invalid article once; preserve Success and ES pending."""
        if isinstance(exc, MultidimEventReferenceError):
            mark_legacy_merge_item_terminal(ctx, item_dir)
        msg = str(exc)
        try:
            mark_not_running(ctx, pk, state="writeback_failed_schema")
        except Exception as ex:
            tlog_warn(f"⚠️ schema 失敗狀態釋放異常（pk={pk}）：{ex}")
        schema_log_path = None
        try:
            schema_log_path = record_adjustment(
                ctx, "writeback_failed_schema_release", pk=pk,
                error=msg,
                output_col=getattr(ctx, "output_col", None),
                output_profile=getattr(ctx, "output_profile", None),
                combined_result_path=combined_path,
            )
        except Exception as ex:
            tlog_warn(f"⚠️ schema 失敗稽核紀錄寫入異常（pk={pk}）：{ex}")
        log_hint = (
            f"；錯誤紀錄已保存於 {schema_log_path}"
            if schema_log_path is not None
            else "；未啟用或未能寫入 schema 失敗稽核紀錄"
        )
        tlog_warn(
            f"Row Merger 略過本輪寫回 pk={pk}: {exc}；"
            "已釋放執行狀態，資料保持 pending，下一次執行會重新拉取並分析"
            f"{log_hint}。"
        )
        registry.remove(item_dir)
        merge_log_emitted_items.discard(item_dir)
        if done_q is not None:
            try:
                done_q.put_nowait(1)
            except Exception:
                pass
        try:
            meter_update(
                meter_fn,
                lambda d, _pk=pk: d["rows"].setdefault(_pk, {}).update(
                    {"status": "writeback_failed_schema"}
                ),
            )
            meter_update(
                meter_fn,
                lambda d: d.setdefault("progress", {}).update(
                    {"last_progress_ts": time.time()}
                ),
            )
        except Exception:
            pass

    def _log_state_once(item_dir):
        todo_dir = os.path.join(item_dir, "TODO")
        succ_dir = os.path.join(item_dir, "Success")
        state = (len(OSWALK(todo_dir)), len(OSWALK(succ_dir)))
        last = row_merger_watchdog_generic._last_state.get(item_dir)
        if last != state:
            tlog(f"🧩 merge check: {os.path.basename(item_dir)} TODO={state[0]}, Success={state[1]}")
            row_merger_watchdog_generic._last_state[item_dir] = state
        return state

    def _resolve_combined_path_old_1027(item_dir, meta, ctx, temp_txt):
        # 1) registry 內的 per-row 路徑（優先）
        p = meta.get("CombBackFN")
        if p and os.path.isfile(p):
            return p

        # 2) 退一步，用共享 ctx 推導（有些 combine 會寫到這）
        try:
            alt = get_combined_result_path(temp_txt, ctx)
            if alt and os.path.isfile(alt):
                return alt
        except Exception:
            pass

        # 3) 最後才嘗試合併（要有 Success 才做，避免洗版）
        succ_dir = os.path.join(item_dir, "Success")
        if len(OSWALK(succ_dir)) > 0:
            try:
                out = combine_api_finished_item(item_dir, ctx)  # 若你的實作會回傳路徑
                if out and os.path.isfile(out):
                    return out
            except ExecutionCancelled:
                raise
            except Exception as e:
                tlog_warn(f"ℹ️ 合併提示（pk={meta.get('pk')}）：{e}")
        return None
    def _resolve_combined_path(item_dir, meta, ctx, temp_txt):
        # 1) registry 內的 per-row 路徑（優先）
        p = meta.get("CombBackFN")
        if p and os.path.isfile(p):
            return p
    
        # 2) 退一步，用共享 ctx 推導（有些 combine 會寫到這）
        try:
            alt = get_combined_result_path(temp_txt, ctx)
            if alt and os.path.isfile(alt):
                return alt
        except Exception:
            alt = None  # 讓後面還能用
    
        # 3) 最後才嘗試合併：用「預期輸出資料夾」覆寫 per-row finished 目錄後再合併
        if not _all_slices_done(item_dir, meta):
            return None
        succ_dir = os.path.join(item_dir, "Success")
        if len(OSWALK(succ_dir)) > 0:
            try:
                target_dir = os.path.dirname(p or alt or get_combined_result_path(temp_txt, ctx))
    
                class _CtxOverlay:
                    def __init__(self, base, **kw):
                        # 複製原 ctx 的屬性，再覆寫
                        self.__dict__.update(getattr(base, "__dict__", {}))
                        self.__dict__.update(kw)
    
                overlay = _CtxOverlay(ctx, temp_txt_finished_dir=target_dir)
                legacy_claimed = _legacy_merge_begin(item_dir)
                if should_merge_slices(ctx) and not legacy_claimed:
                    # Another live path owns this legacy merge, or it already
                    # completed. Wait for the shared artifact instead of
                    # running the same merge twice.
                    return None
                out = combine_api_finished_item(item_dir, overlay)
                if out and os.path.isfile(out):
                    # Materializing the combined artifact is not necessarily
                    # the legacy slice merge itself. Non-JSON-mode list[dict]
                    # payloads are merged later in the writeback path, so keep
                    # the shared claim active until that semantic merge finishes.
                    return out
                _legacy_merge_finish(item_dir, success=False, reason="no_output")
            except ExecutionCancelled:
                raise
            except MultidimEventReferenceError:
                # Deterministic local Event FK failures must reach the
                # terminal-schema handler. Repeated attempts on unchanged
                # Success artifacts flood the console and waste a hot loop.
                _legacy_merge_finish(
                    item_dir, success=False,
                    error_type=MultidimEventReferenceError.__name__,
                )
                raise
            except Exception as e:
                _legacy_merge_finish(
                    item_dir, success=False, error_type=type(e).__name__
                )
                tlog_warn(f"ℹ️ 合併提示（pk={meta.get('pk')}）：{e}")
    
        return None

    sink.open()
    try:
        while True:
            items_map = registry.list_items()
            if not items_map and stop_event.is_set():
                break

            progressed = False
            for item_dir, meta in list(items_map.items()):
                pk = meta["pk"]; temp_txt = meta["temp_txt"]

                if isinstance(meta, dict) and meta.get("status") == "scheduling_multistage":
                    continue

                #if not row_is_ready(item_dir):
                #    _log_state_once(item_dir)
                #    continue

                #_log_state_once(item_dir)
                # 只記錄狀態；若已存在合併檔，優先直接寫回（避免多階段已完成但 TODO/Success 計數不同步造成卡住）
                _log_state_once(item_dir)
                comb_back_fn = meta.get("CombBackFN") if isinstance(meta, dict) else None
                if not (comb_back_fn and os.path.isfile(comb_back_fn)):
                    if not _all_slices_done(item_dir, meta):
                        continue
                    # ← 這裡不再一律呼叫 combine_api_finished_item，改用解析策略
                    try:
                        comb_back_fn = _resolve_combined_path(item_dir, meta, ctx, temp_txt)
                    except MultidimEventReferenceError as e:
                        _release_terminal_schema_failure(
                            item_dir, pk, e, comb_back_fn,
                        )
                        progressed = True
                        continue
                    except ExecutionCancelled:
                        # No incomplete writeback and no retry loop.  Preserve
                        # artifacts, release only this run's coordination.
                        try:
                            mark_not_running(ctx, pk, state="cancelled")
                            record_adjustment(ctx, "cancelled_release", pk=pk)
                        except Exception:
                            pass
                        registry.remove(item_dir)
                        merge_log_emitted_items.discard(item_dir)
                        try:
                            meter_update(
                                meter_fn,
                                lambda d, _pk=pk: d["rows"].setdefault(_pk, {}).update(
                                    {"status": "cancelled"}
                                ),
                            )
                        except Exception:
                            pass
                        progressed = True
                        continue
                if not comb_back_fn or not os.path.isfile(comb_back_fn):
                    continue  # 沒合併檔就等下一輪

                try:
                    with open(comb_back_fn, "r", encoding="utf-8") as fp:
                        result_text = fp.read()

                    write_map, flatten_source_text, source_logs, write_sources = _build_writeback_values(
                        ctx, comb_back_fn, result_text
                    )

                    try:
                        slice_source_text = flatten_source_text
                        data = json.loads(flatten_source_text)
                        if should_merge_slices(ctx) and isinstance(data, list) and all(isinstance(x, dict) for x in data):
                            _legacy_merge_begin(item_dir)
                            merge_logger = None
                            if (
                                getattr(ctx, "merge_log_changes", True)
                                and item_dir not in merge_log_emitted_items
                            ):
                                merge_logger = tlog
                            selected_col = _selected_slice_merge_output_col(
                                ctx, write_map, slice_source_text,
                            )
                            selected_multidim = (
                                is_multidim_event_slice_merge(
                                    ctx, output_col=selected_col,
                                ) if selected_col is not None else False
                            )
                            try:
                                merged_payload, report = merge_dict_slices_audited(
                                    data,
                                    conflict_policy=getattr(ctx, "merge_conflict_policy", "prefer_left"),
                                    dedup_lists=bool(getattr(ctx, "merge_dedup_lists", False)),
                                    audit=True,
                                    logger=merge_logger,
                                    max_log=int(getattr(ctx, "merge_max_log", 10)),
                                    multidim_event=selected_multidim,
                                )
                            except Exception as merge_error:
                                _legacy_merge_finish(
                                    item_dir,
                                    success=False,
                                    error_type=type(merge_error).__name__,
                                )
                                raise
                            try:
                                # A different stage can coincidentally have
                                # identical JSON text. Match its RESOLVED
                                # source identity as well as text, otherwise
                                # selecting one flatten rule would rewrite
                                # an unrelated source's output too early.
                                selected_origin = write_sources.get(selected_col)
                                primary_output_cols = [
                                    col for col, raw in write_map.items()
                                    if raw == slice_source_text
                                    and (selected_origin is None
                                         or write_sources.get(col) == selected_origin)
                                ]
                                merged_columns = _apply_slice_merge_to_write_map(
                                    ctx, write_map, slice_source_text, merged_payload,
                                    output_cols=primary_output_cols,
                                    source_slices=data,
                                    primary_multidim=selected_multidim,
                                )
                            except Exception as merge_error:
                                _legacy_merge_finish(
                                    item_dir, success=False,
                                    error_type=type(merge_error).__name__,
                                )
                                raise
                            _legacy_merge_finish(item_dir, success=True)
                            if merge_logger is not None:
                                merge_log_emitted_items.add(item_dir)
                            if merged_columns:
                                source_logs.append(f"slice_merge:{','.join(merged_columns)}")
                            flatten_source_text = _as_db_text(merged_payload)
                            if getattr(ctx, "merge_log_to_file", False) and report.get("changed"):
                                try:
                                    log_fn = getattr(ctx, "merge_log_file", "merge_dict_slices_audited.log")
                                    with open(log_fn, "at", encoding="utf-8") as fp:
                                        fp.write(f"[{datetime.now().isoformat(timespec='seconds')}] pk={pk} counts={report.get('counts')}\n")
                                        for s in report.get("samples", []):
                                            fp.write(f"  {s['action']} @{s['path']} → {s['chosen']} | L={s['left_short']} | R={s['right_short']}\n")
                                except Exception:
                                    pass
                        elif should_merge_slices(ctx) and isinstance(data, dict):
                            merged_columns = _apply_premerged_combined_slice_merge(
                                ctx, write_map, write_sources
                            )
                            if merged_columns:
                                # Stream multistage may have already performed
                                # the legacy slice merge before Row Merger sees
                                # CombBackFN. Account for that successful merge
                                # here through the same run-scoped ownership
                                # guard used by live/fallback merge paths.
                                if _legacy_merge_begin(item_dir):
                                    _legacy_merge_finish(item_dir, success=True)
                                source_logs.append(
                                    f"slice_merge_premerged:{','.join(merged_columns)}"
                                )
                            else:
                                # A fallback may have materialized this artifact
                                # before Row Merger knew whether the payload was
                                # semantically mergeable. Adopt that handoff only
                                # to close it as a failure; do not create a new
                                # attempt for unrelated dict writeback.
                                if (
                                    legacy_merge_telemetry_state.get(item_dir) != "started"
                                    and try_resume_materialized_legacy_merge_item(ctx, item_dir)
                                ):
                                    legacy_merge_telemetry_state[item_dir] = "started"
                                if legacy_merge_telemetry_state.get(item_dir) == "started":
                                    _legacy_merge_finish(
                                        item_dir, success=False, reason="unsupported_payload"
                                    )
                        else:
                            if (
                                should_merge_slices(ctx)
                                and legacy_merge_telemetry_state.get(item_dir) != "started"
                                and try_resume_materialized_legacy_merge_item(ctx, item_dir)
                            ):
                                legacy_merge_telemetry_state[item_dir] = "started"
                            if legacy_merge_telemetry_state.get(item_dir) == "started":
                                _legacy_merge_finish(
                                    item_dir, success=False, reason="unsupported_payload"
                                )
                    except Exception as merge_or_parse_error:
                        if legacy_merge_telemetry_state.get(item_dir) == "started":
                            _legacy_merge_finish(
                                item_dir,
                                success=False,
                                error_type=type(merge_or_parse_error).__name__,
                            )
                        if isinstance(merge_or_parse_error, MultidimEventReferenceError):
                            # Do not silently continue with unreconciled JSON.
                            raise
                        pass

                    # A job can defer one stage source while the flatten
                    # selector points to a different combined/stage source.
                    # Repair every unprocessed mixed-profile source BEFORE
                    # constructing any sink write document; errors fail
                    # closed rather than silently persisting chunk-local E1s.
                    deferred_cols = _merge_deferred_writeback_sources(
                        ctx, write_map, write_sources,
                    )
                    if deferred_cols:
                        source_logs.append(
                            f"slice_merge_deferred:{','.join(deferred_cols)}"
                        )

                    expanded_cols = _expand_json_columns(ctx, flatten_source_text)
                    if expanded_cols:
                        write_map.update(expanded_cols)
                        source_logs.append(f"expand_json:{len(expanded_cols)}cols")

                    update_time = (datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                   if ctx.record_update_time else None)
                    sink.write_main(pk, write_map, update_time)
                    tlog(f"📝 writeback source for pk={pk}: {'; '.join(source_logs)}")

                    flatten_targets = _resolve_flatten_targets(ctx, write_map, flatten_source_text)
                    for ft in flatten_targets:
                        _process_flatten_target(ctx, sink, pk, ft)

                    # 完成後收尾
                    try:
                        mark_not_running(ctx, pk, state="writeback_completed")
                        record_adjustment(ctx, "writeback_completed_release", pk=pk)
                    except Exception as ex:
                        tlog_warn(f"⚠️ pending running console 釋放失敗（pk={pk}）：{ex}")
                    registry.remove(item_dir)
                    merge_log_emitted_items.discard(item_dir)
                    if done_q is not None:
                        try: done_q.put_nowait(1)
                        except Exception: pass
                    try:
                        meter_update(meter_fn, lambda d, _pk=pk: d["rows"].setdefault(_pk, {}).update({"status":"merged"}))
                        meter_update(meter_fn, lambda d: d.setdefault("progress", {}).update({"last_progress_ts": time.time()}))
                    except Exception:
                        pass

                    # 備份原始 txt（慢 I/O 放最後）
                    try:
                        des = DirReplace(temp_txt, ctx.llm_source_dir, ctx.llm_source_backup_dir)
                        MKDIR(getPathFromFN(des)); safe_move(temp_txt, des)
                    except Exception as ex:
                        tlog_warn(f"⚠️ 備份原始 txt 失敗（pk={pk}）：{ex}")

                    # 清理此列 prompt 工作目錄，避免 cache/Success 殘留 0.txt
                    if bool(getattr(ctx, "cleanup_prompt_item_after_writeback", True)):
                        try:
                            shutil.rmtree(item_dir, ignore_errors=True)
                        except Exception as ex:
                            tlog_warn(f"⚠️ 清理 prompt cache 失敗（pk={pk}）：{ex}")

                    tlog(f"✅ 逐列合併並寫回完成：{pk}")
                    progressed = True

                except Exception as e:
                    msg = str(e)
                    if "stage 寫回模式找不到可用 stage 輸出" in msg:
                        wait_key = (item_dir, pk)
                        if wait_key not in row_merger_watchdog_generic._stage_wait_logged:
                            tlog(
                                f"⏳ Row Merger 等待 stage merged 輸出（pk={pk}，stage selector 尚未可用），"
                                "下一輪會自動重試。"
                            )
                            row_merger_watchdog_generic._stage_wait_logged.add(wait_key)
                        continue
                    row_merger_watchdog_generic._stage_wait_logged.discard((item_dir, pk))
                    if _is_terminal_schema_writeback_error(e):
                        _release_terminal_schema_failure(
                            item_dir, pk, e, comb_back_fn,
                        )
                        progressed = True
                        continue
                    now = time.monotonic()
                    failure_key = (item_dir, str(e))
                    last_logged = failure_log_state.get(failure_key)
                    if last_logged is None or now - last_logged >= failure_log_interval:
                        tlog_warn(
                            f"Row Merger 寫回失敗 pk={pk}: {e} "
                            f"（相同錯誤最多每 {failure_log_interval:g} 秒提示一次）"
                        )
                        failure_log_state[failure_key] = now
                    # 不要 raise；下一輪會再試
                    continue

            if not progressed:
                time.sleep(scan_interval)
    finally:
        try: sink.close()
        except Exception: pass
    

def row_merger_watchdog_generic_OLD_1027(ctx, registry, meter_fn, stop_event, sink,
                                scan_interval=0.2, done_q=None):
    """舊入口統一導向新實作，避免新舊路徑行為分岔。"""
    tlog("♻️ row_merger_watchdog_generic_OLD_1027 已導向新版本 row_merger_watchdog_generic")
    return row_merger_watchdog_generic(
        ctx=ctx,
        registry=registry,
        meter_fn=meter_fn,
        stop_event=stop_event,
        sink=sink,
        scan_interval=scan_interval,
        done_q=done_q,
    )
