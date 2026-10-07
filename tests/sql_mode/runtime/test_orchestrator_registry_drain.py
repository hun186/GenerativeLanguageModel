from types import SimpleNamespace

from czjLLM.sql_mode.runtime.orchestrator import (
    _fallback_merge_enabled, _is_reg_drained, _registry_existing_combined_artifact,
)


class _RegistryWithListOnly:
    def __init__(self, items):
        self._items = items

    def list_items(self):
        return dict(self._items)


def test_is_reg_drained_uses_list_items_when_stats_missing():
    reg = _RegistryWithListOnly({"job/a": {"pk": "1101.TW"}})
    assert _is_reg_drained(reg) is False


def test_is_reg_drained_true_when_list_items_empty():
    reg = _RegistryWithListOnly({})
    assert _is_reg_drained(reg) is True



def test_fallback_merge_publishes_actual_combined_path_to_live_registry(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    import czjLLM.utilities.combine_utils as combine_utils

    job_dir = str(tmp_path / "job")
    out_path = tmp_path / "finished" / "actual_32_char_suffix_result.txt"
    out_path.parent.mkdir(parents=True)
    out_path.write_text("done", encoding="utf-8")

    class Registry:
        def __init__(self):
            self.items = {
                job_dir: {
                    "pk": 1,
                    "temp_txt": str(tmp_path / "source.txt"),
                    "CombBackFN": str(tmp_path / "expected_96_char_suffix_result.txt"),
                }
            }

        def get(self, item_dir):
            return self.items.get(item_dir)

        def update(self, item_dir, **fields):
            if item_dir in self.items:
                self.items[item_dir].update(fields)

    registry = Registry()
    ctx = SimpleNamespace(
        temp_txt_finished_dir=str(tmp_path / "finished"),
        llm_source_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        combine_utils,
        "combine_api_finished_item",
        lambda _job_dir, _ctx: str(out_path),
    )

    assert combine_utils.run_merge_for(ctx, job_dir, registry=registry) is True
    assert registry.get(job_dir)["CombBackFN"] == str(out_path)


def test_fallback_merge_does_not_report_success_when_live_registry_handoff_fails(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    import czjLLM.utilities.combine_utils as combine_utils

    job_dir = str(tmp_path / "job")
    out_path = tmp_path / "finished" / "actual.txt"
    out_path.parent.mkdir(parents=True)
    out_path.write_text("done", encoding="utf-8")

    class BrokenRegistry:
        def get(self, item_dir):
            return {"CombBackFN": "stale"} if item_dir == job_dir else None

        def update(self, item_dir, **fields):
            raise RuntimeError("registry write failed")

    ctx = SimpleNamespace(
        temp_txt_finished_dir=str(tmp_path / "finished"),
        llm_source_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        combine_utils,
        "combine_api_finished_item",
        lambda _job_dir, _ctx: str(out_path),
    )

    # The artifact exists, but the still-live row cannot discover it. The
    # orchestrator must therefore release the shared claim for retry instead
    # of marking the fallback merge permanently completed.
    assert combine_utils.run_merge_for(
        ctx, job_dir, registry=BrokenRegistry()
    ) is False



def test_registry_existing_combined_artifact_only_accepts_live_file(tmp_path):
    job_dir = str(tmp_path / "job")
    authoritative = tmp_path / "finished" / "multistage-final.txt"
    authoritative.parent.mkdir(parents=True)
    authoritative.write_text("marker", encoding="utf-8")

    class Registry:
        def __init__(self, path):
            self.path = path

        def get(self, item_dir):
            if item_dir != job_dir:
                return None
            return {"CombBackFN": str(self.path)}

    assert _registry_existing_combined_artifact(
        Registry(authoritative), job_dir
    ) == str(authoritative)
    assert _registry_existing_combined_artifact(
        Registry(tmp_path / "missing.txt"), job_dir
    ) == ""


def test_fallback_registry_handoff_preserves_existing_authoritative_artifact(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace
    import czjLLM.utilities.combine_utils as combine_utils

    job_dir = str(tmp_path / "job")
    authoritative = tmp_path / "finished" / "multistage-marker.txt"
    fallback = tmp_path / "finished" / "fallback-final-stage.txt"
    authoritative.parent.mkdir(parents=True)
    authoritative.write_text("multistage", encoding="utf-8")
    fallback.write_text("fallback", encoding="utf-8")

    class Registry:
        def __init__(self):
            self.items = {job_dir: {"CombBackFN": str(authoritative)}}
            self.update_calls = []

        def get(self, item_dir):
            return self.items.get(item_dir)

        def update(self, item_dir, **fields):
            self.update_calls.append((item_dir, dict(fields)))
            self.items[item_dir].update(fields)

    registry = Registry()
    ctx = SimpleNamespace(
        temp_txt_finished_dir=str(tmp_path / "finished"),
        llm_source_dir=str(tmp_path),
    )
    monkeypatch.setattr(
        combine_utils,
        "combine_api_finished_item",
        lambda _job_dir, _ctx: str(fallback),
    )

    assert combine_utils.run_merge_for(ctx, job_dir, registry=registry) is True
    assert registry.get(job_dir)["CombBackFN"] == str(authoritative)
    assert registry.update_calls == []



def test_fallback_merge_gate_honors_all_supported_slice_merge_aliases():
    assert _fallback_merge_enabled(SimpleNamespace(merge_slices=True)) is True
    assert _fallback_merge_enabled(SimpleNamespace(enable_slice_merge=True)) is True
    assert _fallback_merge_enabled(SimpleNamespace(merge_strategy="dict_deep")) is True
    assert _fallback_merge_enabled(SimpleNamespace(merge_strategy="slice_merge")) is True
    assert _fallback_merge_enabled(SimpleNamespace(merge_strategy="on")) is True
    assert _fallback_merge_enabled(SimpleNamespace()) is False



def test_run_merge_for_transfers_active_claim_to_materialized_state(
    tmp_path, monkeypatch
):
    import czjLLM.utilities.combine_utils as combine_utils
    from czjLLM.reduction.production_control import (
        ensure_production_observer, mark_legacy_merge_item_materialized,
        try_begin_legacy_merge_item, try_resume_materialized_legacy_merge_item,
    )

    job_dir = str(tmp_path / "job-materialized")
    out_path = tmp_path / "finished" / "materialized.txt"
    out_path.parent.mkdir(parents=True)
    out_path.write_text(
        '[{"left": 1}, {"right": 2}]',
        encoding="utf-8",
    )

    class Registry:
        def __init__(self):
            self.items = {job_dir: {"CombBackFN": ""}}

        def get(self, item_dir):
            return self.items.get(item_dir)

        def update(self, item_dir, **fields):
            self.items[item_dir].update(fields)

    ctx = SimpleNamespace(
        temp_txt_finished_dir=str(tmp_path / "finished"),
        llm_source_dir=str(tmp_path),
        PGMSubDir=str(tmp_path),
        mode="es",
        merge_slices=True,
    )
    registry = Registry()
    observer = ensure_production_observer(ctx)

    assert try_begin_legacy_merge_item(ctx, job_dir) is True
    observer.emit("legacy_merge_started", {})
    monkeypatch.setattr(
        combine_utils,
        "combine_api_finished_item",
        lambda _job_dir, _ctx: str(out_path),
    )

    assert combine_utils.run_merge_for(ctx, job_dir, registry=registry) is True
    assert registry.get(job_dir)["CombBackFN"] == str(out_path)
    # Fallback materialization is not completion and can be adopted exactly
    # once by Row Merger for the semantic merge.
    assert observer.snapshot()["legacy_merges_completed"] == 0
    assert try_resume_materialized_legacy_merge_item(ctx, job_dir) is True
