import json
import os
import time
from dataclasses import dataclass
from typing import Any, Optional
from czjLLM.utilities.json_text_utils import loads_json_flexible_deep


@dataclass
class WritebackPayload:
    main_payload: Any
    main_text: str
    flatten_text: str
    source: str

def _has_explicit_multistage(ctx: Any | None) -> bool:
    """判斷是否有明確配置多階段（stages>=2）。"""
    if ctx is None:
        return False
    stages = getattr(ctx, "stages", None)
    if isinstance(stages, list):
        return len(stages) > 1
    if isinstance(stages, dict):
        raw = stages.get("stages")
        return isinstance(raw, list) and len(raw) > 1
    task_cfg = getattr(ctx, "task_config", None)
    if isinstance(task_cfg, dict):
        raw = task_cfg.get("stages")
        return isinstance(raw, list) and len(raw) > 1
    return False


def _iter_manifest_candidates(combined_path: str, ctx: Any | None = None) -> list[str]:
    """嘗試在 finished/cache 區域附近尋找 multistage manifest。"""
    out: list[str] = []

    search_roots: list[str] = []

    def _add_root(path: str) -> None:
        p = str(path or "").strip()
        if not p:
            return
        abs_p = os.path.abspath(p)
        if abs_p not in search_roots:
            search_roots.append(abs_p)

    # 1) 由 combined 輸出檔一路向上找（維持原行為）
    base_dir = os.path.dirname(os.path.abspath(combined_path))
    cur = base_dir
    for _ in range(4):
        _add_root(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    # 2) 額外參考 ctx（SQL 多執行緒下 combined 與 stage_merge 可能不在同一樹）
    if ctx is not None:
        for key in ("temp_txt_finished_dir", "llm_source_finished_dir", "prompt_dir"):
            _add_root(getattr(ctx, key, ""))

    for root in search_roots:
        stage_root = os.path.join(root, "_stage_merges")
        if os.path.isdir(stage_root):
            for name in os.listdir(stage_root):
                cand = os.path.join(stage_root, name, "manifest.json")
                if os.path.isfile(cand):
                    out.append(cand)
    # 新到舊排序
    out.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return out


def _load_stage_defs(manifest_path: str) -> list[dict]:
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return []
    stage_defs = manifest.get("stages") if isinstance(manifest, dict) else None
    return stage_defs if isinstance(stage_defs, list) else []


def _manifest_source(manifest_path: str) -> str:
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return ""
    if isinstance(manifest, dict):
        return str(manifest.get("source", "") or "").strip()
    return ""


def _select_stage(stage_defs: list[dict], stage_selector: Any) -> Optional[dict]:
    if not stage_defs:
        return None
    if stage_selector is None or str(stage_selector).strip() == "":
        # 預設找最後一個 merged=true 的 stage
        merged = [s for s in stage_defs if bool(s.get("merged"))]
        return merged[-1] if merged else stage_defs[-1]

    token = str(stage_selector).strip()
    if token.isdigit():
        idx = int(token)
        if 1 <= idx <= len(stage_defs):
            return stage_defs[idx - 1]
    for s in stage_defs:
        if token in {str(s.get("name", "")).strip(), str(s.get("task_key", "")).strip()}:
            return s
    return None


def _read_stage_text(manifest_path: str, stage_info: dict) -> Optional[str]:
    merged_file = str(stage_info.get("merged_file", "") or "").strip()
    if not merged_file:
        return None
    stage_dir = os.path.dirname(os.path.abspath(manifest_path))
    path = os.path.join(stage_dir, merged_file)
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def _read_stage_snapshot_text(manifest_path: str, stage_info: dict, ctx: Any | None = None) -> Optional[str]:
    """
    當 stage 沒有 merged_file（例如 persist_output=final 但非最後一段）時，
    退回讀取 item/_stage_outputs/<stage>/ 內容，避免誤回退到 combined_text。
    """
    stage_name = str(stage_info.get("name", "") or "").strip()
    if not stage_name:
        return None

    source_name = _manifest_source(manifest_path)
    if not source_name:
        return None

    roots: list[str] = []
    for key in ("prompt_dir", "temp_txt_dir", "work_pool_root"):
        p = str(getattr(ctx, key, "") or "").strip() if ctx is not None else ""
        if p:
            roots.append(os.path.abspath(p))

    # 補充：由 manifest 推導 finished/cache，再對應到 workpool prompt/cache
    # .../LLMSourcePool_Finished/sql_cache/cache/_stage_merges/<source>/manifest.json
    # -> .../WorkPool_czjLLM/sql_cache/Prompt/cache/<source>/_stage_outputs/<stage>
    try:
        manifest_abs = os.path.abspath(manifest_path)
        parts = manifest_abs.replace("\\", "/").split("/")
        if "_stage_merges" in parts:
            idx = parts.index("_stage_merges")
            before = parts[:idx]  # .../<...>/cache
            if before and before[-1] == "cache":
                prompt_cache = before[:-1] + ["Prompt", "cache"]
                roots.append(os.path.abspath("/".join(prompt_cache)))
    except Exception:
        pass

    seen = set()
    for root in roots:
        if root in seen:
            continue
        seen.add(root)
        snap_dir = os.path.join(root, source_name, "_stage_outputs", stage_name)
        if not os.path.isdir(snap_dir):
            continue
        parts = []
        for fn in sorted(os.listdir(snap_dir)):
            if not fn.lower().endswith(".txt"):
                continue
            fp = os.path.join(snap_dir, fn)
            if not os.path.isfile(fp):
                continue
            with open(fp, "r", encoding="utf-8") as f:
                parts.append(f.read())
        if parts:
            return "\n".join(parts)
    return None


def _read_stage_snapshot_text_without_manifest(combined_path: str, stage_name: str, ctx: Any | None = None) -> Optional[str]:
    """
    當 manifest 尚未落盤時，直接從 *_stage_outputs* 回讀指定 stage 內容。
    僅用於已明確指定 stage（selector 非空）情境，以避免誤判來源。
    """
    token = str(stage_name or "").strip()
    if not token:
        return None

    roots: list[str] = []
    for key in ("prompt_dir", "temp_txt_dir", "work_pool_root"):
        p = str(getattr(ctx, key, "") or "").strip() if ctx is not None else ""
        if p:
            roots.append(os.path.abspath(p))

    # 由 combined 路徑推導對應 prompt/cache 根目錄
    try:
        cabs = os.path.abspath(combined_path)
        parts = cabs.replace("\\", "/").split("/")
        if "cache" in parts:
            idx = len(parts) - 1 - parts[::-1].index("cache")
            before = parts[:idx]
            roots.append(os.path.abspath("/".join(before + ["Prompt", "cache"])))
    except Exception:
        pass

    # 從 combined 檔名猜測 source 名稱（如 rowA_task -> rowA）
    stem = os.path.splitext(os.path.basename(os.path.abspath(combined_path)))[0]
    source_hints: list[str] = []
    for sep in ("_task", "__", "_prompt", "_"):
        if sep in stem:
            source_hints.append(stem.split(sep, 1)[0].strip())
    source_hints.append(stem)

    # 候選 source: 先猜測，再掃描目錄
    candidates: list[tuple[float, str]] = []
    seen = set()
    for root in roots:
        if root in seen or not os.path.isdir(root):
            continue
        seen.add(root)
        for src in source_hints:
            if not src:
                continue
            cand = os.path.join(root, src, "_stage_outputs", token)
            if os.path.isdir(cand):
                candidates.append((os.path.getmtime(cand), cand))
        for name in os.listdir(root):
            cand = os.path.join(root, name, "_stage_outputs", token)
            if os.path.isdir(cand):
                candidates.append((os.path.getmtime(cand), cand))

    for _, snap_dir in sorted(candidates, key=lambda x: x[0], reverse=True):
        parts = []
        for fn in sorted(os.listdir(snap_dir)):
            if not fn.lower().endswith(".txt"):
                continue
            fp = os.path.join(snap_dir, fn)
            if not os.path.isfile(fp):
                continue
            with open(fp, "r", encoding="utf-8") as f:
                parts.append(f.read())
        if parts:
            return "\n".join(parts)
    return None




def _needs_stage_manifest_lookup(ctx: Any | None) -> bool:
    """是否應啟用 manifest 重試（多階段或已配置 stage 寫回）。"""
    if ctx is None:
        return False
    if _has_explicit_multistage(ctx):
        return True
    rules = getattr(ctx, "sql_writeback_rules", None)
    if isinstance(rules, list):
        for rule in rules:
            if not isinstance(rule, dict):
                continue
            mode = str(rule.get("source", rule.get("sql_writeback_source", "combined")) or "combined").strip().lower()
            if mode == "stage":
                return True
    return False


def _manifest_retry_params(ctx: Any | None) -> tuple[int, float]:
    """回傳 manifest 尋找重試參數：(attempts, sleep_seconds)。"""
    attempts = 1
    sleep_sec = 0.0
    try:
        if _needs_stage_manifest_lookup(ctx):
            attempts = int(getattr(ctx, "manifest_lookup_attempts", 60) or 60)
            sleep_ms = int(getattr(ctx, "manifest_lookup_sleep_ms", 500) or 500)
            sleep_sec = max(sleep_ms, 0) / 1000.0
    except Exception:
        attempts, sleep_sec = 1, 0.0
    return max(attempts, 1), max(sleep_sec, 0.0)


def _find_manifests_with_retry(combined_path: str, ctx: Any | None = None) -> list[str]:
    """
    尋找 manifests，必要時短暫重試。

    原因：多階段流程下，manifest 可能在合併後極短時間才落盤。
    """
    attempts, sleep_sec = _manifest_retry_params(ctx)
    for i in range(attempts):
        manifests = _iter_manifest_candidates(combined_path, ctx=ctx)
        if manifests:
            return manifests
        if i < attempts - 1 and sleep_sec > 0:
            time.sleep(sleep_sec)
    return []




def resolve_writeback_payload(ctx, combined_path: str, combined_text: str) -> WritebackPayload:
    """
    SQL/ES 模式共用：決定主欄位與 flatten 應使用哪份內容。

    ctx.sql_writeback_source:
      - combined (default): 沿用舊行為
      - stage: 使用指定 stage 的 merged 內容
    ctx.sql_writeback_stage:
      - stage 名稱 / task_key / 1-based index
    """
    source_mode = str(getattr(ctx, "sql_writeback_source", "combined") or "combined").strip().lower()
    if source_mode != "stage":
        try:
            payload = loads_json_flexible_deep(combined_text)
        except Exception:
            payload = combined_text
        return WritebackPayload(main_payload=payload, main_text=combined_text, flatten_text=combined_text, source="combined")

    manifests = _find_manifests_with_retry(combined_path, ctx=ctx)
    selector = getattr(ctx, "sql_writeback_stage", None)
    selector_token = str(selector or "").strip()
    if not manifests:
        # 根治：當 manifest 尚未落盤時，允許從 row snapshot 直接讀取指定 stage。
        if selector_token:
            stage_text = _read_stage_snapshot_text_without_manifest(combined_path, selector_token, ctx=ctx)
            if stage_text is not None:
                try:
                    payload = loads_json_flexible_deep(stage_text)
                except Exception:
                    payload = stage_text
                return WritebackPayload(
                    main_payload=payload,
                    main_text=stage_text,
                    flatten_text=stage_text,
                    source=f"stage:{selector_token}",
                )
        raise RuntimeError(
            "stage 寫回模式找不到 _stage_merges/manifest.json；已中止寫回以避免誤寫。"
            "請檢查 stage merge 輸出路徑與 manifest 落盤時序。"
        )

    # 優先順序：
    # 1) manifest.source 可對上 combined 檔名（避免誤抓其他 row 的 manifest）
    # 2) 能成功選到 stage 且讀到 stage merged_file
    combined_stem = os.path.splitext(os.path.basename(os.path.abspath(combined_path)))[0]
    candidates: list[str] = []
    for mp in manifests:
        src = _manifest_source(mp)
        if src and src in combined_stem:
            candidates.append(mp)
    for mp in manifests:
        if mp not in candidates:
            candidates.append(mp)

    for manifest_path in candidates:
        stage_defs = _load_stage_defs(manifest_path)
        selected = _select_stage(stage_defs, selector)
        if not selected:
            continue
        # Runtime assert:
        # 若 writeback 明確指定 stage（selector 非空），該 stage 必須有 merged_file，
        # 否則直接報錯中止，避免默默回退導致寫入錯資料。
        if selector_token and not str(selected.get("merged_file", "") or "").strip():
            stage_name = str(selected.get("name", "")).strip() or selector_token
            raise RuntimeError(
                f"sql_writeback_rules 指定 stage:{stage_name}，但 manifest 缺少 merged_file。"
                "請將該 stage 設為 persist_output=always，或確認強制 merge 生效。"
            )
        stage_text = _read_stage_text(manifest_path, selected)
        if stage_text is None and not selector_token:
            stage_text = _read_stage_snapshot_text(manifest_path, selected, ctx=ctx)
        if stage_text is None:
            stage_text = _read_stage_snapshot_text(manifest_path, selected, ctx=ctx)
        if stage_text is None:
            continue

        try:
            payload = loads_json_flexible_deep(stage_text)
        except Exception:
            payload = stage_text
        stage_name = str(selected.get("name", "")).strip() or "stage"
        return WritebackPayload(
            main_payload=payload,
            main_text=stage_text,
            flatten_text=stage_text,
            source=f"stage:{stage_name}",
        )

    stage_hint = selector_token or "<last merged stage>"
    raise RuntimeError(
        f"stage 寫回模式找不到可用 stage 輸出（selector={stage_hint}）；已中止寫回以避免誤寫。"
        "請檢查 sql_writeback_rules.stage 設定與 stage merge 產物。"
    )
