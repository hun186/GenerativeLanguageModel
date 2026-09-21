from pathlib import Path

import pytest

from tests.reduction.test_single_pass_routing import _ctx, _read_output, _write
import czjLLM.utilities.combine_utils as combine_utils


class FakeAdapter:
    calls = []
    fingerprint = "fake-v1"
    outputs = ["short"]

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def execution_fingerprint(self):
        return self.fingerprint

    def next_round_items(self, payload, round_index):
        self.calls.append((payload, round_index))
        runtime_dir = (
            Path(self.kwargs["item_workspace"])
            / ".reduction"
            / "runtime"
            / f"round-{round_index:04d}"
        )
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return list(self.outputs)


def _hierarchical(controller, options, task="ROUND"):
    return {
        "enabled": True, "profile": "concat_text", "controller": controller,
        "controller_options": options, "runtime": {"round_task": task},
    }


@pytest.fixture(autouse=True)
def fake_adapter(monkeypatch):
    FakeAdapter.calls = []
    FakeAdapter.fingerprint = "fake-v1"
    FakeAdapter.outputs = ["short"]
    monkeypatch.setattr(combine_utils, "TextRoundRuntimeAdapter", FakeAdapter)


def test_fixed_round_one_only_reduces_existing_success_outputs(tmp_path):
    ctx = _ctx(tmp_path, _hierarchical("fixed_rounds", {"rounds": 1}))
    item = Path(ctx.prompt_dir) / "fixed-one"
    _write(item, "0.txt", "A")
    _write(item, "1.txt", "B")
    assert _read_output(item, ctx) == "A\nB\n"
    assert FakeAdapter.calls == []


def test_fixed_round_two_invokes_exactly_one_map_cycle(tmp_path):
    ctx = _ctx(tmp_path, _hierarchical("fixed_rounds", {"rounds": 2}))
    item = Path(ctx.prompt_dir) / "fixed-two"
    _write(item, "0.txt", "A")
    _write(item, "1.txt", "B")
    assert _read_output(item, ctx) == "short"
    assert FakeAdapter.calls == [("A\nB\n", 2)]


def test_fixed_round_two_preserves_multiple_map_output_boundaries(tmp_path):
    FakeAdapter.outputs = ["foo\n", "bar\n"]
    ctx = _ctx(tmp_path, _hierarchical("fixed_rounds", {"rounds": 2}))
    item = Path(ctx.prompt_dir) / "fixed-two-boundaries"
    _write(item, "0.txt", "initial")

    assert _read_output(item, ctx) == "foo\nbar\n"
    assert FakeAdapter.calls == [("initial\n", 2)]


def test_adaptive_target_at_round_one_skips_map(tmp_path):
    ctx = _ctx(tmp_path, _hierarchical("adaptive_hierarchical", {
        "target_max_chars": 10, "max_rounds": 3, "min_reduction_ratio": 0.1,
    }))
    item = Path(ctx.prompt_dir) / "adaptive-done"
    _write(item, "0.txt", "A")
    assert _read_output(item, ctx) == "A\n"
    assert FakeAdapter.calls == []


def test_adaptive_continuation_maps_then_reduces(tmp_path):
    ctx = _ctx(tmp_path, _hierarchical("adaptive_hierarchical", {
        "target_max_chars": 5, "max_rounds": 3, "min_reduction_ratio": 0.1,
    }))
    item = Path(ctx.prompt_dir) / "adaptive-continue"
    _write(item, "0.txt", "a much longer aggregate")
    assert _read_output(item, ctx) == "short"
    assert FakeAdapter.calls == [("a much longer aggregate\n", 2)]


def test_terminal_checkpoint_resume_and_fingerprint_invalidation(tmp_path):
    ctx = _ctx(tmp_path, _hierarchical("fixed_rounds", {"rounds": 2}))
    item = Path(ctx.prompt_dir) / "resume"
    _write(item, "0.txt", "A")
    assert _read_output(item, ctx) == "short"
    assert len(FakeAdapter.calls) == 1
    assert _read_output(item, ctx) == "short"
    assert len(FakeAdapter.calls) == 1

    FakeAdapter.fingerprint = "fake-v2"
    FakeAdapter.outputs = ["changed"]
    assert _read_output(item, ctx) == "changed"
    assert len(FakeAdapter.calls) == 2


def test_hierarchical_debug_false_preserves_resume_workspace(tmp_path):
    ctx = _ctx(tmp_path, _hierarchical("fixed_rounds", {"rounds": 2}))
    ctx.debug = False
    item = Path(ctx.prompt_dir) / "production-resume"
    _write(item, "0.txt", "A")
    _write(item, "1.txt", "B")

    assert _read_output(item, ctx) == "short"
    assert item.is_dir()
    assert (item / "Success" / "0.txt").is_file()
    assert (item / "Success" / "1.txt").is_file()
    assert (item / ".reduction" / "checkpoints").is_dir()
    assert (item / ".reduction" / "runtime" / "round-0002").is_dir()
    assert len(FakeAdapter.calls) == 1

    assert _read_output(item, ctx) == "short"
    assert len(FakeAdapter.calls) == 1
    assert item.is_dir()


def test_single_pass_debug_false_keeps_historical_cleanup(tmp_path):
    ctx = _ctx(
        tmp_path,
        {"enabled": True, "profile": "concat_text", "controller": "single_pass"},
    )
    ctx.debug = False
    item = Path(ctx.prompt_dir) / "single-pass-cleanup"
    _write(item, "0.txt", "A")

    assert _read_output(item, ctx) == "A\n"
    assert not item.exists()
