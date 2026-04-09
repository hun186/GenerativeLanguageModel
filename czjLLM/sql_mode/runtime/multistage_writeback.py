import json
import os
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class WritebackPayload:
    main_payload: Any
    main_text: str
    flatten_text: str
    source: str


def _iter_manifest_candidates(combined_path: str) -> list[str]:
    """嘗試在 finished/cache 區域附近尋找 multistage manifest。"""
    out: list[str] = []
    base_dir = os.path.dirname(os.path.abspath(combined_path))
    cur = base_dir
    for _ in range(4):
        stage_root = os.path.join(cur, "_stage_merges")
        if os.path.isdir(stage_root):
            for name in os.listdir(stage_root):
                cand = os.path.join(stage_root, name, "manifest.json")
                if os.path.isfile(cand):
                    out.append(cand)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    # 新到舊排序
    out.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return out


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
            payload = json.loads(combined_text)
        except Exception:
            payload = combined_text
        return WritebackPayload(main_payload=payload, main_text=combined_text, flatten_text=combined_text, source="combined")

    manifests = _iter_manifest_candidates(combined_path)
    if not manifests:
        try:
            payload = json.loads(combined_text)
        except Exception:
            payload = combined_text
        return WritebackPayload(main_payload=payload, main_text=combined_text, flatten_text=combined_text, source="combined(fallback:no_manifest)")

    manifest_path = manifests[0]
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        manifest = {}
    stage_defs = manifest.get("stages") if isinstance(manifest, dict) else None
    if not isinstance(stage_defs, list):
        stage_defs = []

    selected = _select_stage(stage_defs, getattr(ctx, "sql_writeback_stage", None))
    if not selected:
        try:
            payload = json.loads(combined_text)
        except Exception:
            payload = combined_text
        return WritebackPayload(main_payload=payload, main_text=combined_text, flatten_text=combined_text, source="combined(fallback:no_stage)")

    stage_text = _read_stage_text(manifest_path, selected)
    if stage_text is None:
        try:
            payload = json.loads(combined_text)
        except Exception:
            payload = combined_text
        return WritebackPayload(main_payload=payload, main_text=combined_text, flatten_text=combined_text, source="combined(fallback:no_stage_file)")

    try:
        payload = json.loads(stage_text)
    except Exception:
        payload = stage_text
    stage_name = str(selected.get("name", "")).strip() or "stage"
    return WritebackPayload(
        main_payload=payload,
        main_text=stage_text,
        flatten_text=stage_text,
        source=f"stage:{stage_name}",
    )
