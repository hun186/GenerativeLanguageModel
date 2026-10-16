from __future__ import annotations
from pathlib import Path

import os
import json
from opencc import OpenCC
import shutil
import re
import hashlib
from typing import List, Dict, Any, Tuple, Optional
try:
    from utils.utilities_path import OSWALK
    from utils.utilities_path import MKDIR
    from utils.utilities_path import getPathFromFN
    from utils.utilities_path import DirReplace
    from utils.utilities import flattenList
    from utils.MP_utils import MPlogger
except Exception as ex:
    print(ex)

from json_repair import repair_json
from czjLLM.utilities.json_text_utils import strip_markdown_code_fence
from czjLLM.utilities.fs_safe import (
    path_diagnostic,
    safe_atomic_write_text,
    safe_mkdir,
    safe_read_text,
    safe_rmtree,
)

import re

from czjLLM.utilities.json_combining import (
    clean_and_merge_json_lists,
    combine_json_return,
    robust_merge_json_lists,
    split_json_arrays,
    split_json_arrays_safe,
)
from czjLLM.utilities.slice_merge import (
    merge_dict_slices,
    merge_dict_slices_audited,
    is_multidim_event_slice_merge,
    should_merge_slices,
)
from czjLLM.reduction.config import ReductionConfig, parse_reduction_config
from czjLLM.reduction.engine import reduce_single_pass
from czjLLM.reduction.runtime_semantic import SemanticLLMRuntimeAdapter
from czjLLM.reduction.hierarchical import reduce_hierarchical_text
from czjLLM.reduction.runtime_text import TextRoundRuntimeAdapter
from czjLLM.reduction.production_control import (
    ensure_production_observer,
    finish_legacy_merge_item,
    mark_legacy_merge_item_materialized,
    raise_if_execution_cancelled,
)
from czjLLM.reduction.retention import (
    cleanup_completed_transient_runtime,
    parse_reduction_retention_policy,
)

def _p(s):
    """接受 str / Path / 任何 PathLike。空字串或 None 則回傳 None。"""
    if s is None:
        return None
    try:
        s_str = os.fspath(s)  # 可處理 PathLike
    except TypeError:
        s_str = str(s)
    s_str = str(s_str)
    return Path(s_str) if s_str.strip() else None

def _safe_task_suffix(task: str, max_len: int = 96) -> str:
    """
    產生可安全放入檔名的任務後綴：
    - 移除 Windows/一般檔名非法字元
    - 將空白與換行壓成底線
    - 過長時截斷並加 hash，避免路徑過長
    """
    cleaned = re.sub(r'[\\/:*?"<>|]+', "_", str(task or "")).strip()
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._") or "result"
    if len(cleaned) <= max_len:
        return cleaned
    digest = hashlib.sha1(cleaned.encode("utf-8")).hexdigest()[:10]
    head_len = max(16, max_len - 11)  # 保留 "_" + 10 碼 hash
    return f"{cleaned[:head_len]}_{digest}"


def _resolve_task_suffix_for_filename(ctx) -> str:
    """
    依執行模式決定輸出檔名的任務後綴長度：
    - SQL 模式預設較短（避免 CT_name 過長造成路徑冗長）
    - 其餘模式維持較寬鬆長度
    - 可用 ctx.task_filename_max_len 覆蓋
    """
    mode = str(getattr(ctx, "mode", "") or "").strip().lower()
    default_max_len = 32 if mode == "sql" else 96
    try:
        max_len = int(getattr(ctx, "task_filename_max_len", default_max_len) or default_max_len)
    except Exception:
        max_len = default_max_len
    max_len = max(16, min(max_len, 128))
    return _safe_task_suffix(getattr(ctx, "task", "result"), max_len=max_len)




def _should_parse_as_json_task(task_text: str) -> bool:
    """
    判斷任務是否應視為 JSON 任務。

    避免把「禁止輸出 JSON」這類文字誤判為 JSON 任務。
    """
    normalized = str(task_text or "").strip().lower()
    if not normalized:
        return False

    negative_hints = (
        "禁止輸出 json",
        "不要輸出 json",
        "do not output json",
        "without json",
    )
    if any(h in normalized for h in negative_hints):
        return False

    positive_hints = (
        "to json format",
        "json 回覆",
        "json回复",
        "請回傳：[",
        "请回传：[",
        "請回傳json",
        "請輸出json",
        "output json",
        "return json",
    )
    return any(h in normalized for h in positive_hints)

def _truthy_debug_flag(value) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "debug"}


def _combine_step_debug_enabled(ctx) -> bool:
    """Return whether verbose [combine-step] checkpoint logs should be printed."""
    env_value = os.getenv("CZJLLM_COMBINE_DEBUG")
    if env_value is not None:
        return _truthy_debug_flag(env_value)
    return _truthy_debug_flag(getattr(ctx, "combine_debug", False))


def combine_api_finished_item(item: str, ctx) -> str:
    import json
    import os
    import threading
    import time
    import traceback
    from pathlib import Path

    call_id = (
        f"{os.getpid()}-"
        f"{threading.get_ident()}-"
        f"{time.time_ns()}"
    )

    stage = "entry"
    item_p = Path(item)
    suc_dir = item_p / "Success"
    out_path = None

    combine_step_debug = _combine_step_debug_enabled(ctx)

    def checkpoint(name: str, **values) -> None:
        if not combine_step_debug:
            return

        details = ", ".join(
            f"{key}={value!r}"
            for key, value in values.items()
        )

        print(
            f"[combine-step] "
            f"id={call_id}, "
            f"stage={name}"
            + (f", {details}" if details else ""),
            flush=True,
        )

    def path_len(path) -> int:
        try:
            return len(os.path.abspath(os.fspath(path)))
        except Exception:
            return -1

    try:
        checkpoint(
            "entry",
            module_file=__file__,
            function_file=(
                combine_api_finished_item.__code__.co_filename
            ),
            function_line=(
                combine_api_finished_item.__code__.co_firstlineno
            ),
            pid=os.getpid(),
            thread=threading.current_thread().name,
            item=str(item_p),
            item_length=path_len(item_p),
        )

        # -------------------------------------------------
        # 1. 任務模式
        # -------------------------------------------------
        stage = "resolve-task-mode"

        task_text = str(getattr(ctx, "task", ""))
        raw_reduction = getattr(ctx, "reduction", None)
        reduction_config = (
            raw_reduction
            if isinstance(raw_reduction, ReductionConfig)
            else parse_reduction_config(
                raw_reduction,
                merge_slices=should_merge_slices(ctx),
            )
        )

        checkpoint(
            "before-detect-json-mode",
            task=task_text,
        )

        json_mode = _should_parse_as_json_task(task_text)
        reduction_json_mode = reduction_config.enabled and reduction_config.profile in {
            "concat_json_list",
            "legacy_json_deep_merge",
        }
        parse_as_json = reduction_json_mode or (
            not reduction_config.enabled and json_mode
        )

        checkpoint(
            "after-detect-json-mode",
            json_mode=json_mode,
        )

        text_chunks: list[str] = []
        json_rows: list[dict] = []
        json_slice_count = 0

        # -------------------------------------------------
        # 2. 列出 Success 檔案
        # -------------------------------------------------
        stage = "list-success-files"

        checkpoint(
            "before-oswalk",
            success_dir=str(suc_dir),
            success_dir_length=path_len(suc_dir),
            success_dir_exists=suc_dir.exists(),
        )

        success_files = sorted(OSWALK(str(suc_dir)))

        checkpoint(
            "after-oswalk",
            count=len(success_files),
            files=success_files,
        )

        # 每次函式只建立一次 converter，避免每個分片重建。
        stage = "create-opencc"

        checkpoint("before-opencc-create")

        converter = OpenCC("s2twp")

        checkpoint("after-opencc-create")

        # -------------------------------------------------
        # 3. 讀取並解析 Success 分片
        # -------------------------------------------------
        for index, fp in enumerate(success_files):
            p = Path(fp)

            stage = f"read-success-file-{index}"

            checkpoint(
                "before-read",
                index=index,
                path=str(p),
                path_length=path_len(p),
                exists=p.exists(),
            )

            text = safe_read_text(
                p,
                encoding="utf-8",
                logger=print,
            )

            checkpoint(
                "after-read",
                index=index,
                chars=len(text),
            )

            if not text or not text.strip():
                checkpoint(
                    "skip-empty-file",
                    index=index,
                )
                continue

            # 暫時保留 OpenCC，但明確印出前後位置。
            stage = f"opencc-convert-{index}"

            checkpoint(
                "before-opencc-convert",
                index=index,
            )

            converted_prefix = converter.convert(
                text.lstrip()
            )

            checkpoint(
                "after-opencc-convert",
                index=index,
                converted_chars=len(converted_prefix),
            )

            if converted_prefix.startswith(
                "無主題相關內容"
            ):
                checkpoint(
                    "skip-no-topic",
                    index=index,
                )
                continue

            if parse_as_json:
                stage = f"parse-json-{index}"

                checkpoint(
                    "before-json-loads",
                    index=index,
                )

                try:
                    obj = json.loads(text)

                    checkpoint(
                        "after-json-loads",
                        index=index,
                        obj_type=type(obj).__name__,
                    )

                    if isinstance(obj, dict):
                        json_rows.append(obj)
                        json_slice_count += 1
                        continue

                    if isinstance(obj, list):
                        dict_rows = [
                            row
                            for row in obj
                            if isinstance(row, dict)
                        ]

                        json_rows.extend(dict_rows)

                        if dict_rows:
                            json_slice_count += 1

                        continue

                    raise ValueError(
                        "不支援的 JSON 結構："
                        f"{type(obj).__name__}"
                    )

                except Exception as ex:
                    has_multistage = False

                    try:
                        stages = getattr(ctx, "stages", None)
                        has_multistage = (
                            isinstance(stages, list)
                            and len(stages) > 1
                        )
                    except Exception:
                        has_multistage = False

                    if has_multistage:
                        print(
                            "⚠️ JSON 解析失敗"
                            "（multistage 將改由 stage 輸出寫回，"
                            "可忽略）："
                            f"{p}，錯誤：{ex}",
                            flush=True,
                        )
                    else:
                        print(
                            "❌ 解析 JSON 失敗"
                            "（將以純文字串接回退）："
                            f"{p}，錯誤：{ex}",
                            flush=True,
                        )

            text_chunks.append(
                text if text.endswith("\n")
                else text + "\n"
            )

        # -------------------------------------------------
        # 4. 合併分片
        # -------------------------------------------------
        stage = "merge-slices"

        checkpoint(
            "before-merge-slices",
            json_mode=json_mode,
            json_rows=len(json_rows),
            json_slice_count=json_slice_count,
            text_chunks=len(text_chunks),
            merge_slices=should_merge_slices(ctx),
        )

        if reduction_config.enabled:
            print(
                "[reduction] enabled=true "
                f"controller={reduction_config.controller} "
                f"profile={reduction_config.profile}",
                flush=True,
            )
            if reduction_config.profile == "concat_text":
                reduction_items = text_chunks
            else:
                if not json_rows and text_chunks:
                    fallback_text = "".join(text_chunks)
                    fixed, _repair_error = combine_json_return(
                        fallback_text,
                        dictListForced=True,
                    )
                    try:
                        repaired_payload = json.loads(fixed)
                    except Exception as ex:
                        raise ValueError(
                            "Explicit JSON reduction could not repair fallback text "
                            "into valid dictionary items"
                        ) from ex

                    if isinstance(repaired_payload, dict):
                        json_rows = [repaired_payload]
                    elif isinstance(repaired_payload, list):
                        json_rows = [
                            row
                            for row in repaired_payload
                            if isinstance(row, dict)
                        ]

                    if not json_rows:
                        raise ValueError(
                            "Explicit JSON reduction repair produced no valid "
                            "dictionary items"
                        )
                reduction_items = json_rows
            if reduction_config.controller == "single_pass":
                raise_if_execution_cancelled(ctx)
                reducer_context = {"combine_item": str(item_p)}
                if reduction_config.contains_semantic_llm():
                    reducer_context["semantic_runtime"] = SemanticLLMRuntimeAdapter(ctx=ctx)
                reduction_result = reduce_single_pass(
                    reduction_items,
                    reduction_config,
                    context=reducer_context,
                )
                raise_if_execution_cancelled(ctx)
            else:
                adapter = TextRoundRuntimeAdapter(
                    ctx=ctx,
                    item_workspace=item_p,
                    round_task=reduction_config.runtime["round_task"],
                )
                reduction_result = reduce_hierarchical_text(
                    reduction_items,
                    profile="concat_text",
                    controller=reduction_config.build_controller(),
                    next_round_items=adapter.next_round_items,
                    context={"combine_item": str(item_p)},
                    checkpoint_root=item_p / ".reduction" / "checkpoints",
                    execution_fingerprint=adapter.execution_fingerprint(),
                    cancellation_check=lambda: raise_if_execution_cancelled(ctx),
                )
                raise_if_execution_cancelled(ctx)
            payload = reduction_result.payload
            combined_text = (
                payload
                if isinstance(payload, str)
                else json.dumps(payload, ensure_ascii=False, indent=2)
            )
        elif json_mode and json_rows:
            if (
                should_merge_slices(ctx)
                and json_slice_count > 1
            ):
                checkpoint(
                    "before-audited-dict-merge",
                )

                merged_obj, _report = (
                    merge_dict_slices_audited(
                        json_rows,
                        conflict_policy=str(
                            getattr(
                                ctx,
                                "merge_conflict_policy",
                                "prefer_left",
                            )
                        ),
                        dedup_lists=bool(
                            getattr(
                                ctx,
                                "merge_dedup_lists",
                                True,
                            )
                        ),
                        audit=bool(
                            getattr(
                                ctx,
                                "merge_log_changes",
                                True,
                            )
                        ),
                        logger=(
                            print
                            if bool(
                                getattr(
                                    ctx,
                                    "merge_log_changes",
                                    True,
                                )
                            )
                            else None
                        ),
                        max_log=int(
                            getattr(
                                ctx,
                                "merge_max_log",
                                10,
                            )
                        ),
                        multidim_event=is_multidim_event_slice_merge(ctx),
                    )
                )

                checkpoint(
                    "after-audited-dict-merge",
                )

                combined_text = json.dumps(
                    merged_obj,
                    ensure_ascii=False,
                    indent=2,
                )

            else:
                combined_text = json.dumps(
                    json_rows,
                    ensure_ascii=False,
                    indent=2,
                )

        else:
            combined_text = "".join(text_chunks)

            if json_mode and not combined_text.strip():
                combined_text = "[]"

        checkpoint(
            "after-merge-slices",
            combined_chars=len(combined_text),
        )

        # -------------------------------------------------
        # 5. 決定輸出位置
        # -------------------------------------------------
        stage = "resolve-output-root"

        checkpoint("before-resolve-output-root")

        base_out = (
            _p(
                getattr(
                    ctx,
                    "temp_txt_finished_dir",
                    None,
                )
            )
            or _p(
                getattr(
                    ctx,
                    "llm_source_finished_dir",
                    None,
                )
            )
            or _p(
                getattr(
                    ctx,
                    "llm_source_dir",
                    None,
                )
            )
            or item_p.parent
        )

        base_out = Path(base_out)

        checkpoint(
            "after-resolve-output-root",
            base_out=str(base_out),
            base_out_length=path_len(base_out),
        )

        stage = "resolve-relative-output-path"

        prompt_dir_value = getattr(
            ctx,
            "prompt_dir",
            "",
        )

        checkpoint(
            "before-resolve-prompt-root",
            prompt_dir=str(prompt_dir_value),
        )

        prompt_root = Path(
            prompt_dir_value
        ).resolve()

        try:
            rel = item_p.resolve().relative_to(
                prompt_root
            )
            mirror_parent = rel.parent
        except Exception as ex:
            checkpoint(
                "relative-path-fallback",
                error=repr(ex),
            )
            mirror_parent = Path("")

        mp_parts = list(mirror_parent.parts)

        if (
            mp_parts
            and base_out.name.lower()
            == mp_parts[0].lower()
        ):
            mp_parts = mp_parts[1:]

        dest_dir = base_out / Path(*mp_parts)

        checkpoint(
            "resolved-dest-dir",
            mirror_parent=str(mirror_parent),
            dest_dir=str(dest_dir),
            dest_dir_length=path_len(dest_dir),
        )

        # -------------------------------------------------
        # 6. 建立輸出目錄
        # -------------------------------------------------
        stage = "create-output-directory"

        checkpoint(
            "before-safe-mkdir",
            dest_dir=str(dest_dir),
        )

        safe_mkdir(
            dest_dir,
            logger=print,
        )

        checkpoint(
            "after-safe-mkdir",
            dest_dir_exists=dest_dir.exists(),
        )

        # -------------------------------------------------
        # 7. 組合輸出檔名
        # -------------------------------------------------
        stage = "resolve-output-file"

        main_name = item_p.name
        task_name = _resolve_task_suffix_for_filename(
            ctx
        )

        out_path = (
            dest_dir
            / f"{main_name}_{task_name}.txt"
        )

        checkpoint(
            "resolved-output-file",
            main_name=main_name,
            task_name=task_name,
            out_path=str(out_path),
            out_path_length=path_len(out_path),
        )

        # -------------------------------------------------
        # 8. JSON 回退修補
        # -------------------------------------------------
        stage = "repair-json-output"

        if (
            not reduction_config.enabled
            and "to json format" in task_text.lower()
            and not (json_mode and json_rows)
        ):
            checkpoint(
                "before-combine-json-return",
            )

            fixed, err = combine_json_return(
                combined_text,
                dictListForced=True,
            )

            combined_text = fixed

            checkpoint(
                "after-combine-json-return",
                has_error=bool(err),
                combined_chars=len(combined_text),
            )

            if err:
                logs_dir = (
                    Path(
                        getattr(
                            ctx,
                            "PGMSubDir",
                            "",
                        )
                    )
                    / "logs"
                )

                safe_mkdir(
                    logs_dir,
                    logger=print,
                )

                MPlogger(
                    str(logs_dir),
                    logFile=(
                        "FailToCombineJsonResult.log"
                    ),
                ).logW(
                    MES=(
                        f"When combining {out_path} "
                        "json format, the following "
                        f"error occurs:\n{err}\n"
                    )
                )

        # -------------------------------------------------
        # 9. 寫出正式結果
        # -------------------------------------------------
        stage = "write-output"

        checkpoint(
            "before-atomic-write",
            out_path=str(out_path),
            out_path_length=path_len(out_path),
            combined_chars=len(combined_text),
        )

        safe_atomic_write_text(
            out_path,
            combined_text,
            encoding="utf-8",
            logger=print,
        )

        checkpoint(
            "after-atomic-write",
            out_path_exists=out_path.exists(),
        )

        # Retention is best-effort maintenance and runs only after the final
        # output is durable.  A cleanup error must not invalidate that result.
        if reduction_config.enabled and reduction_config.controller in {
            "fixed_rounds", "adaptive_hierarchical"
        }:
            raw_retention = getattr(ctx, "reduction_retention", None)
            if raw_retention is None and isinstance(getattr(ctx, "cfg", None), dict):
                raw_retention = ctx.cfg.get("reduction_retention")
            try:
                retention_policy = parse_reduction_retention_policy(raw_retention)
                if retention_policy.enabled:
                    cleanup_completed_transient_runtime(
                        item_p,
                        retention_policy,
                        observer=ensure_production_observer(ctx),
                    )
            except Exception as retention_error:
                try:
                    ensure_production_observer(ctx).emit(
                        "reduction_retention_failed", {"error_type": type(retention_error).__name__}
                    )
                except Exception:
                    pass
                print("⚠️ Reduction retention maintenance failed; final output is preserved.", flush=True)

        # -------------------------------------------------
        # 10. 清除工作目錄
        # -------------------------------------------------
        stage = "cleanup-work-directory"

        debug_enabled = bool(
            getattr(ctx, "debug", False)
        )
        hierarchical_resume_workspace = (
            reduction_config.enabled
            and reduction_config.controller
            in {"fixed_rounds", "adaptive_hierarchical"}
        )

        checkpoint(
            "before-cleanup-check",
            debug=debug_enabled,
            item_is_dir=item_p.is_dir(),
            hierarchical_resume_workspace=hierarchical_resume_workspace,
        )

        if (
            not debug_enabled
            and item_p.is_dir()
            and not hierarchical_resume_workspace
        ):
            checkpoint(
                "before-safe-rmtree",
                item=str(item_p),
                item_length=path_len(item_p),
            )

            cleanup_ok = safe_rmtree(
                item_p,
                logger=print,
                raise_on_failure=False,
            )

            checkpoint(
                "after-safe-rmtree",
                cleanup_ok=cleanup_ok,
                item_exists=item_p.exists(),
            )

            if not cleanup_ok:
                print(
                    "⚠️ 輸出已成功寫入，但工作目錄"
                    "暫時無法刪除："
                    f"{item_p}",
                    flush=True,
                )

        stage = "finished"

        checkpoint(
            "finished",
            out_path=str(out_path),
        )

        print(
            "CombBackFN",
            out_path,
            flush=True,
        )

        return str(out_path)

    except BaseException as ex:
        print(
            "\n[COMBINE-FATAL]\n"
            f"id={call_id}\n"
            f"stage={stage}\n"
            f"pid={os.getpid()}\n"
            f"thread="
            f"{threading.current_thread().name}\n"
            f"type={type(ex).__module__}."
            f"{type(ex).__qualname__}\n"
            f"repr={ex!r}\n"
            f"item={str(item_p)!r}\n"
            f"out_path="
            f"{str(out_path) if out_path else None!r}\n"
            f"traceback:\n"
            f"{traceback.format_exc()}",
            flush=True,
        )

        raise
        
def combine_api_finished_item_0717(item: str, ctx) -> str:
    import inspect
    import os
    import threading

    print(
        "\n[COMBINE-CODE-LOCATION]\n"
        f"module_file={__file__!r}\n"
        f"function_file={combine_api_finished_item.__code__.co_filename!r}\n"
        f"function_line={combine_api_finished_item.__code__.co_firstlineno}\n"
        f"pid={os.getpid()}\n"
        f"thread={threading.current_thread().name}",
        flush=True,
    )

    print(
        f"{item} is finished calling API, "
        "start to combine returned result.",
        flush=True,
    )
    
    item_p = Path(item)
    suc_dir = item_p / "Success"

    task_text = str(getattr(ctx, "task", ""))
    json_mode = _should_parse_as_json_task(task_text)
    text_chunks: list[str] = []
    json_rows: list[dict] = []
    json_slice_count = 0

    for fp in sorted(OSWALK(str(suc_dir))):
        p = Path(fp)
        #text = p.read_text(encoding="utf-8")
        text = safe_read_text(
            p,
            encoding="utf-8",
            logger=print,
        )
        if not text or not text.strip():
            # 有些 provider/重試流程會留下空白成功檔，避免誤判成 JSON 壞檔
            continue
        if OpenCC("s2twp").convert(text.lstrip()).startswith("無主題相關內容"):
            continue

        if json_mode:
            try:
                obj = json.loads(text)
                if isinstance(obj, dict):
                    json_rows.append(obj)
                    json_slice_count += 1
                    continue
                if isinstance(obj, list):
                    dict_rows = [x for x in obj if isinstance(x, dict)]
                    json_rows.extend(dict_rows)
                    if dict_rows:
                        json_slice_count += 1
                    continue
                raise ValueError("不支援的 JSON 結構")
            except Exception as e:
                has_multistage = False
                try:
                    stages = getattr(ctx, "stages", None)
                    has_multistage = isinstance(stages, list) and len(stages) > 1
                except Exception:
                    has_multistage = False
                if has_multistage:
                    print(f"⚠️ JSON 解析失敗（multistage 將改由 stage 輸出寫回，可忽略）：{p}，錯誤：{e}")
                else:
                    print(f"❌ 解析 JSON 失敗（將以純文字串接回退）：{p}，錯誤：{e}")
        text_chunks.append(text if text.endswith("\n") else text + "\n")

    if json_mode and json_rows:
        if should_merge_slices(ctx) and json_slice_count > 1:
            merged_obj, _report = merge_dict_slices_audited(
                json_rows,
                conflict_policy=str(getattr(ctx, "merge_conflict_policy", "prefer_left")),
                dedup_lists=bool(getattr(ctx, "merge_dedup_lists", True)),
                audit=bool(getattr(ctx, "merge_log_changes", True)),
                logger=print if bool(getattr(ctx, "merge_log_changes", True)) else None,
                max_log=int(getattr(ctx, "merge_max_log", 10)),
                multidim_event=is_multidim_event_slice_merge(ctx),
            )
            combined_text = json.dumps(merged_obj, ensure_ascii=False, indent=2)
        else:
            combined_text = json.dumps(json_rows, ensure_ascii=False, indent=2)
    else:
        combined_text = "".join(text_chunks)
        if json_mode and not combined_text.strip():
            # JSON 任務在全部分片都空白時，輸出合法空陣列，避免後續寫回/flatten 解析失敗
            combined_text = "[]"

    # === 安全地決定輸出目錄（不要出現前導斜線） ===
    # 優先 llm_source_finished_dir，其次 llm_source_dir；都沒有就用 item 的上層
    #'''
    
    #print('getattr(ctx,"temp_txt_finished_dir")',getattr(ctx,"temp_txt_finished_dir",""))
    #print("ctx.llm_source_finished_dir",ctx.llm_source_finished_dir)
    #print("ctx.llm_source_dir",ctx.llm_source_dir)
    #print("types:",
    #      type(getattr(ctx, "llm_source_finished_dir", None)),
    #      type(getattr(ctx, "llm_source_dir", None)),
    #      type(getattr(ctx, "prompt_dir", None)))
    '''
    # 1) 先決定 Finished 根
    base_out = (
        _p(getattr(ctx, "temp_txt_finished_dir", None))
        or _p(getattr(ctx, "llm_source_finished_dir", None))
        or _p(getattr(ctx, "llm_source_dir", None))
        or item_p.parent
    )
    
    # 2) 用 prompt 根去計算 item 的「相對子路徑」
    prompt_root = _p(getattr(ctx, "prompt_dir", None)).resolve()
    rel = item_p.resolve().relative_to(prompt_root)  # e.g. "2/test_merge"
    mirror_parent = rel.parent                       # e.g. "2"
    
    # 3) 最終輸出資料夾：Finished根 / 相對子目錄(parent)
    dest_dir = base_out / mirror_parent              # → .../LLMSourcePool_Finished/test long/2
    dest_dir.mkdir(parents=True, exist_ok=True)
    
    # 4) 檔名仍用 item 名稱 + 任務名
    main_name = item_p.name
    task_name = str(getattr(ctx, "task", "result")).replace(os.sep, "_")
    out_path = dest_dir / f"{main_name}_{task_name}.txt"
    '''
    # 1) 先決定 Finished 根
    base_out = (
        _p(getattr(ctx, "temp_txt_finished_dir", None))
        or _p(getattr(ctx, "llm_source_finished_dir", None))
        or _p(getattr(ctx, "llm_source_dir", None))
        or Path(item).parent
    )
    # 確保是 Path
    base_out = Path(base_out)
    
    # 2) 用 prompt 根去計算 item 的「相對子路徑」
    prompt_root = Path(getattr(ctx, "prompt_dir", "")).resolve()
    try:
        rel = Path(item).resolve().relative_to(prompt_root)  # e.g. "cache/excel_input_45_90233bc9"
        mirror_parent = rel.parent                           # e.g. "cache"
    except Exception:
        mirror_parent = Path("")
    
    # 3) 如果 base_out 的最後一段與 mirror_parent 的第一段相同，就把 mirror_parent 的第一段去掉，避免重複
    mp_parts = list(mirror_parent.parts)
    if mp_parts and base_out.name.lower() == mp_parts[0].lower():
        mp_parts = mp_parts[1:]
    
    dest_dir = base_out / Path(*mp_parts)
    #dest_dir.mkdir(parents=True, exist_ok=True)
    safe_mkdir(
        dest_dir,
        logger=print,
    )
    
    # 4) 檔名
    main_name = Path(item).name
    task_name = _resolve_task_suffix_for_filename(ctx)
    out_path = dest_dir / f"{main_name}_{task_name}.txt"
    # JSON 合併修補（如有指定 to json format，且目前仍為字串拼接型態）
    if "to json format" in str(getattr(ctx, "task", "")).lower() and not (json_mode and json_rows):
        fixed, err = combine_json_return(combined_text, dictListForced=True)
        combined_text = fixed
        if err:
            logs_dir = Path(getattr(ctx, "PGMSubDir", "")) / "logs"
            logs_dir.mkdir(parents=True, exist_ok=True)
            MPlogger(str(logs_dir), logFile="FailToCombineJsonResult.log").logW(
                MES=f"When combining {out_path} json format, the following error occurs:\n{err}\n"
            )

    #out_path.write_text(combined_text, encoding="utf-8")
    safe_atomic_write_text(
        out_path,
        combined_text,
        encoding="utf-8",
        logger=print,
    )
    #print("item_p",item_p)
    #print("base_out",base_out)
    #print("out_path",out_path)
    if not getattr(ctx, "debug", False) and item_p.is_dir():
        #shutil.rmtree(item_p)
        cleanup_ok = safe_rmtree(
            item_p,
            logger=print,
            raise_on_failure=False,
        )
        
        if not cleanup_ok:
            print(
                "⚠️ 輸出已成功寫入，但工作目錄暫時無法刪除："
                f"{item_p}",
                flush=True,
            )
    print("CombBackFN", out_path)
    return str(out_path)
    
def _publish_combined_path_to_registry(registry, job_dir: str, out_path: str) -> bool:
    """Publish the actual combined artifact for a still-registered row.

    Returns True when no live registry row needs the handoff or when the path is
    verifiably published. A failed handoff keeps fallback ownership retryable
    instead of marking an undiscoverable artifact as completed.
    """
    if registry is None:
        return True

    item_present = None
    current = None
    getter = getattr(registry, "get", None)
    if callable(getter):
        try:
            current = getter(job_dir)
            item_present = current is not None
        except Exception:
            pass
    if item_present is None:
        lister = getattr(registry, "list_items", None)
        if callable(lister):
            try:
                items = lister() or {}
                current = items.get(job_dir)
                item_present = job_dir in items
            except Exception:
                pass
    if item_present is False:
        return True

    # Preserve an already-published authoritative artifact. This can be the
    # multistage scheduler's final combined result; fallback output must never
    # replace it merely because the row is still waiting on a slow sink.
    if isinstance(current, dict):
        existing = str(current.get("CombBackFN", "") or "")
        if existing and os.path.isfile(existing):
            return True

    published = False
    updater = getattr(registry, "update", None)
    if callable(updater):
        try:
            updater(job_dir, CombBackFN=str(out_path))
            published = True
        except Exception:
            published = False
    if not published:
        for fn in ("update_item_meta", "set_item_meta", "update_item"):
            method = getattr(registry, fn, None)
            if not callable(method):
                continue
            try:
                method(job_dir, {"CombBackFN": str(out_path)})
                published = True
            except Exception:
                published = False
            if published:
                break
    if not published:
        return False

    # Verify when the registry offers a readable view. This prevents a no-op
    # updater from converting a still-live row into a permanently completed
    # but undiscoverable fallback claim.
    getter = getattr(registry, "get", None)
    if callable(getter):
        try:
            meta = getter(job_dir)
            if meta is not None:
                return str(meta.get("CombBackFN", "")) == str(out_path)
        except Exception:
            return False
    lister = getattr(registry, "list_items", None)
    if callable(lister):
        try:
            items = lister() or {}
            if job_dir in items:
                return str(items[job_dir].get("CombBackFN", "")) == str(out_path)
        except Exception:
            return False
    return True


def run_merge_for(ctx, job_dir: str, registry=None) -> bool:
    finished_root = (
        getattr(ctx, "temp_txt_finished_dir", None)
        or getattr(ctx, "llm_source_finished_dir", None)
        or getattr(ctx, "llm_source_dir", None)
    )
    class _CtxOverlay:
        def __init__(self, base, **kw):
            self.__dict__.update(getattr(base, "__dict__", {}))
            self.__dict__.update(kw)

    overlay = _CtxOverlay(ctx, debug=True, temp_txt_finished_dir=finished_root)
    out_path = combine_api_finished_item(job_dir, overlay)

    ok = bool(out_path and os.path.isfile(out_path))
    if not ok:
        return False

    materialized = False
    if should_merge_slices(ctx):
        # Make the ownership handoff visible before publishing CombBackFN so
        # Row Merger can never observe the artifact while the shared claim is
        # still owned by fallback as an opaque "active" operation.
        materialized = mark_legacy_merge_item_materialized(ctx, job_dir)

    published = _publish_combined_path_to_registry(
        registry, job_dir, str(out_path)
    )
    if not published and materialized:
        finish_legacy_merge_item(ctx, job_dir, success=False)
    return published
'''
def run_merge_for(ctx, job_dir: str) -> bool:
    finished_root = (
        getattr(ctx, "temp_txt_finished_dir", None)
        or getattr(ctx, "llm_source_finished_dir", None)
        or getattr(ctx, "llm_source_dir", None)
    )
    class _CtxOverlay:
        def __init__(self, base, **kw):
            self.__dict__.update(getattr(base, "__dict__", {}))
            self.__dict__.update(kw)

    overlay = _CtxOverlay(ctx, debug=True, temp_txt_finished_dir=finished_root)
    out_path = combine_api_finished_item(job_dir, overlay)
    return bool(out_path and os.path.isfile(out_path))
'''
def run_merge_for_OLD(ctx, job_dir: str) -> bool:
    """
    專做「該 job_dir 的切片合併」；不負責寫回 ES/SQL（那是 row_merger_watchdog_generic 的職責）。
    觸發條件：TODO 與 RUNNING 皆空，且 Success 有內容時才進行合併。
    關鍵：以 debug=True 的 overlay ctx 呼叫 combine_api_finished_item，避免先把 item 目錄刪掉，
          讓 row_merger 能在下一輪掃描到合併產物並完成 sink.write_main() 與 registry.remove()。
    回傳：True=有執行且產出合併檔；False=不需要或失敗。
    """
    try:
        todo_cnt    = len(OSWALK(os.path.join(job_dir, "TODO")))
        running_cnt = len(OSWALK(os.path.join(job_dir, "RUNNING")))
        success_cnt = len(OSWALK(os.path.join(job_dir, "Success")))
    except Exception:
        todo_cnt = running_cnt = success_cnt = 0

    # 沒切片可合併，或仍在處理中 → 不動
    if success_cnt <= 0:
        return False
    if (todo_cnt > 0) or (running_cnt > 0):
        return False

    # 建立 overlay ctx：指定輸出根目錄、最重要的是 debug=True（避免 combine 後刪 item 夾）
    class _CtxOverlay:
        def __init__(self, base, **kw):
            self.__dict__.update(getattr(base, "__dict__", {}))
            self.__dict__.update(kw)

    target_finished_root = (
        getattr(ctx, "temp_txt_finished_dir", None)
        or getattr(ctx, "llm_source_finished_dir", None)
        or getattr(ctx, "llm_source_dir", None)
    )

    overlay = _CtxOverlay(
        ctx,
        debug=True,  # <<< 關鍵：讓 combine 不刪 job_dir，保證 row_merger 能接手寫回 sink
        temp_txt_finished_dir=target_finished_root,
    )

    try:
        out_path = combine_api_finished_item(job_dir, overlay)
        if out_path and os.path.isfile(out_path):
            try:
                tlog(f"🧩 run_merge_for：合併完成 → {out_path}")
            except Exception:
                print(f"run_merge_for merged: {out_path}")
            # （可選）若日後想加速 row_merger 取檔，可在 registry meta 記 CombBackFN。
            # 目前 watchdog 的 _resolve_combined_path() 已能藉 get_combined_result_path() 找到成品，故非必要。
            return True
        else:
            try:
                tlog_warn(f"⚠️ run_merge_for：combine 未產出檔案（{job_dir}）")
            except Exception:
                print(f"run_merge_for WARN: no output for {job_dir}")
            return False
    except Exception as e:
        try:
            tlog_warn(f"⚠️ run_merge_for 失敗（{job_dir}）：{e}")
        except Exception:
            print(f"run_merge_for ERROR for {job_dir}: {e}")
        return False
