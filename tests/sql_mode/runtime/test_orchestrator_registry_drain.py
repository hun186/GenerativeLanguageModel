from czjLLM.sql_mode.runtime.orchestrator import _is_reg_drained


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
