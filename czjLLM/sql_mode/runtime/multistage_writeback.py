import json
import os
from dataclasses import dataclass
from typing import Any, Optional
from czjLLM.utilities.json_text_utils import loads_json_flexible


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
            payload = loads_json_flexible(combined_text)
        except Exception:
            payload = combined_text
        return WritebackPayload(main_payload=payload, main_text=combined_text, flatten_text=combined_text, source="combined")

    manifests = _iter_manifest_candidates(combined_path, ctx=ctx)
    if not manifests:
        try:
            payload = loads_json_flexible(combined_text)
        except Exception:
            payload = combined_text
        fallback_source = "combined(fallback:no_manifest)"
        if _has_explicit_multistage(ctx):
            fallback_source = "combined(fallback:no_manifest;multistage_configured)"
        return WritebackPayload(main_payload=payload, main_text=combined_text, flatten_text=combined_text, source=fallback_source)

    selector = getattr(ctx, "sql_writeback_stage", None)

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
        stage_text = _read_stage_text(manifest_path, selected)
        if stage_text is None:
            continue

        try:
            payload = loads_json_flexible(stage_text)
        except Exception:
            payload = stage_text
        stage_name = str(selected.get("name", "")).strip() or "stage"
        return WritebackPayload(
            main_payload=payload,
            main_text=stage_text,
            flatten_text=stage_text,
            source=f"stage:{stage_name}",
        )

    try:
        payload = loads_json_flexible(combined_text)
    except Exception:
        payload = combined_text
    return WritebackPayload(
        main_payload=payload,
        main_text=combined_text,
        flatten_text=combined_text,
        source="combined(fallback:no_matching_stage_manifest)",
    )
