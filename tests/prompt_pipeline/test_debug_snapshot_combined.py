"""Debug snapshots must not infer a combined artifact from a guessed filename."""
from types import SimpleNamespace

from czjLLM.prompt_pipeline import debug_snapshot


class _Registry:
    def __init__(self, item, metadata):
        self.item = item
        self.metadata = metadata

    def list_items(self):
        return {str(self.item): self.metadata}


def test_combined_status_uses_authoritative_registry_path_only(tmp_path, monkeypatch):
    item = tmp_path / "item"
    (item / "TODO").mkdir(parents=True)
    (item / "Success").mkdir()
    real_combined = tmp_path / "other-dir" / "result.txt"
    real_combined.parent.mkdir()
    ctx = SimpleNamespace(PGMSubDir=str(tmp_path))
    meter = {
        "queue": {"pending": 1, "running": 0},
        "rows": {},
    }
    monkeypatch.setattr(
        debug_snapshot, "robust_json_read", lambda *args, **kwargs: meter,
    )

    def snapshot(meta):
        return debug_snapshot.build_debug_snapshot(
            ctx, _Registry(item, meta), str(tmp_path / "meter.json"),
            base_url_load_fn=str(tmp_path / "absent_load.json"),
        )

    assert "combined=UNKNOWN" in snapshot({"pk": "a"})
    assert "combined=N" in snapshot({"pk": "a", "CombBackFN": str(real_combined)})
    real_combined.write_text("{}", encoding="utf-8")
    assert "combined=Y" in snapshot({"pk": "a", "CombBackFN": str(real_combined)})
    assert str(real_combined) not in snapshot({"pk": "a", "CombBackFN": str(real_combined)})
