import json
from pathlib import Path
from types import SimpleNamespace

from czjLLM.sql_mode.runtime.multistage_writeback import resolve_writeback_payload


def _write_manifest(stage_root: Path, source: str, stages: list[dict], files: dict[str, str]):
    stage_root.mkdir(parents=True, exist_ok=True)
    (stage_root / "manifest.json").write_text(
        json.dumps({"source": source, "stages": stages}, ensure_ascii=False),
        encoding="utf-8",
    )
    for name, text in files.items():
        (stage_root / name).write_text(text, encoding="utf-8")


def test_resolve_writeback_payload_prefers_manifest_source_match(tmp_path):
    finished_dir = tmp_path / "finished"
    cache_dir = finished_dir / "cache"
    cache_dir.mkdir(parents=True)
    combined_path = cache_dir / "rowB_task.txt"
    combined_path.write_text('{"fallback": true}', encoding="utf-8")

    stage_merges = finished_dir / "_stage_merges"

    # 干擾 manifest（更新時間較新，且 extract 內容錯誤）
    _write_manifest(
        stage_merges / "rowA",
        source="rowA",
        stages=[
            {"name": "route", "task_key": "", "merged_file": "01_route.txt", "merged": True},
            {"name": "extract", "task_key": "", "merged_file": "02_extract.txt", "merged": True},
        ],
        files={
            "01_route.txt": '[{"route":"org"}]',
            "02_extract.txt": '[{"inputName":"WRONG"}]',
        },
    )

    _write_manifest(
        stage_merges / "rowB",
        source="rowB",
        stages=[
            {"name": "route", "task_key": "", "merged_file": "01_route.txt", "merged": True},
            {"name": "extract", "task_key": "", "merged_file": "02_extract.txt", "merged": True},
        ],
        files={
            "01_route.txt": '[{"route":"org"}]',
            "02_extract.txt": '[{"inputName":"RIGHT"}]',
        },
    )

    ctx = SimpleNamespace(sql_writeback_source="stage", sql_writeback_stage="extract")
    out = resolve_writeback_payload(ctx, str(combined_path), combined_path.read_text(encoding="utf-8"))

    assert out.source == "stage:extract"
    assert out.main_payload == [{"inputName": "RIGHT"}]


def test_resolve_writeback_payload_falls_back_when_stage_not_found(tmp_path):
    combined_path = tmp_path / "cache" / "rowX_task.txt"
    combined_path.parent.mkdir(parents=True)
    combined_text = '[{"route":"org"}]'
    combined_path.write_text(combined_text, encoding="utf-8")

    _write_manifest(
        tmp_path / "_stage_merges" / "rowX",
        source="rowX",
        stages=[{"name": "route", "merged": True, "merged_file": "01_route.txt"}],
        files={"01_route.txt": combined_text},
    )

    ctx = SimpleNamespace(sql_writeback_source="stage", sql_writeback_stage="extract")
    out = resolve_writeback_payload(ctx, str(combined_path), combined_text)

    assert out.source == "combined(fallback:no_matching_stage_manifest)"
    assert out.main_payload == [{"route": "org"}]


def test_resolve_writeback_payload_finds_manifest_from_ctx_finished_dir(tmp_path):
    # combined 結果在 workpool 路徑，manifest 則在 finished 路徑（兩者非祖先關係）
    combined_path = tmp_path / "workpool" / "sql_cache" / "cache" / "rowC_task.txt"
    combined_path.parent.mkdir(parents=True)
    combined_path.write_text('[{"route":"org"}]', encoding="utf-8")

    finished_dir = tmp_path / "llm_finished" / "cache"
    _write_manifest(
        finished_dir / "_stage_merges" / "rowC",
        source="rowC",
        stages=[
            {"name": "route", "merged": True, "merged_file": "01_route.txt"},
            {"name": "extract", "merged": True, "merged_file": "02_extract.txt"},
        ],
        files={
            "01_route.txt": '[{"route":"org"}]',
            "02_extract.txt": '[{"inputName":"OK_FROM_CTX_FINISHED"}]',
        },
    )

    ctx = SimpleNamespace(
        sql_writeback_source="stage",
        sql_writeback_stage="extract",
        llm_source_finished_dir=str(finished_dir),
    )
    out = resolve_writeback_payload(ctx, str(combined_path), combined_path.read_text(encoding="utf-8"))

    assert out.source == "stage:extract"
    assert out.main_payload == [{"inputName": "OK_FROM_CTX_FINISHED"}]
