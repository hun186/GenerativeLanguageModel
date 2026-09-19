import json
from dataclasses import dataclass

import pytest

from czjLLM.reduction.artifacts import (
    CheckpointCompatibilityError,
    CheckpointCorruptionError,
)
from czjLLM.reduction.contracts import ReducerResult
from czjLLM.reduction.controllers import (
    AdaptiveHierarchicalController,
    FixedRoundsController,
)
from czjLLM.reduction.hierarchical import (
    EmptyReductionResultError,
    ReducerExecutionError,
    reduce_hierarchical_text,
)
from czjLLM.reduction.registry import ReducerRegistry


@dataclass
class SequenceReducer:
    outputs: list
    changed: bool = False
    profile: str = "concat_text"
    contract_version: str = "test-1"
    requires_stable_order: bool = True
    preserves_order: bool = True

    def __post_init__(self):
        self.calls = 0

    def reduce(self, items, context=None):
        del items, context
        self.calls += 1
        output = self.outputs.pop(0)
        if isinstance(output, BaseException):
            raise output
        return ReducerResult(
            output, self.profile, self.contract_version, self.changed
        )


def registry_for(reducer):
    registry = ReducerRegistry()
    registry.register("concat_text", reducer)
    return registry


def run(reducer, controller, *, checkpoint_root=None, initial=("initial",), builder=None):
    return reduce_hierarchical_text(
        initial,
        profile="concat_text",
        controller=controller,
        next_round_items=builder or (lambda payload, index: [payload]),
        registry=registry_for(reducer),
        checkpoint_root=checkpoint_root,
    )


@pytest.mark.parametrize("rounds", [1, 3])
def test_fixed_rounds_executes_exact_count(rounds):
    reducer = SequenceReducer(["out"] * rounds, changed=False)
    result = run(reducer, FixedRoundsController(rounds))
    assert result.rounds_completed == rounds
    assert result.stop_reason == "fixed_rounds_complete"
    assert reducer.calls == rounds


def test_target_reached_first_round_precedes_max_rounds():
    result = run(
        SequenceReducer(["tiny"]),
        AdaptiveHierarchicalController(4, 1, 0.99),
    )
    assert result.stop_reason == "target_reached"


def test_target_reached_after_multiple_rounds_and_changed_is_ignored():
    reducer = SequenceReducer(["abcdefghij", "abc"], changed=False)
    result = run(reducer, AdaptiveHierarchicalController(3, 5, 0.1))
    assert result.stop_reason == "target_reached"
    assert reducer.calls == 2
    assert result.round_metrics[0].reduction_ratio is None
    assert result.round_metrics[1].reduction_ratio == pytest.approx(0.7)


def test_max_round_precedes_stall():
    result = run(
        SequenceReducer(["abcdefghij", "abcdefghij"]),
        AdaptiveHierarchicalController(1, 2, 0.5),
    )
    assert result.stop_reason == "max_rounds"
    assert result.warnings


@pytest.mark.parametrize("second", ["abcdefghij", "abcdefghijkl"])
def test_stall_including_growth(second):
    result = run(
        SequenceReducer(["abcdefghij", second]),
        AdaptiveHierarchicalController(1, 5, 0.1),
    )
    assert result.stop_reason == "stalled"


def test_first_round_never_stalls_without_previous_aggregate():
    reducer = SequenceReducer(["abcdefghij", "abc"])
    result = run(reducer, AdaptiveHierarchicalController(3, 5, 0.99))
    assert reducer.calls == 2
    assert result.stop_reason == "target_reached"


def test_empty_output_is_execution_error():
    with pytest.raises(EmptyReductionResultError):
        run(SequenceReducer([" \n"]), FixedRoundsController(1))


def test_reducer_failure_is_chained():
    with pytest.raises(ReducerExecutionError) as caught:
        run(SequenceReducer([ValueError("boom")]), FixedRoundsController(1))
    assert isinstance(caught.value.__cause__, ValueError)


def test_rejects_non_text_profile():
    with pytest.raises(ValueError, match="concat_text only"):
        reduce_hierarchical_text(
            ["x"],
            profile="json",
            controller=FixedRoundsController(1),
            next_round_items=lambda payload, index: [payload],
            registry=ReducerRegistry(),
        )


def test_completed_checkpoint_payload_and_metadata(tmp_path):
    result = run(SequenceReducer(["done"]), FixedRoundsController(1), checkpoint_root=tmp_path)
    run_dir = next(tmp_path.iterdir())
    assert (run_dir / "round-0001.payload.txt").read_text() == "done"
    metadata = json.loads((run_dir / "round-0001.json").read_text())
    assert metadata["status"] == "completed"
    assert metadata["terminal_stop_reason"] == "fixed_rounds_complete"
    assert metadata["metrics"]["output_character_count"] == 4
    assert result.payload == "done"


def test_payload_is_written_before_checkpoint_metadata(tmp_path, monkeypatch):
    import czjLLM.reduction.artifacts as artifacts

    observed = []
    original_json = artifacts.atomic_write_json

    def inspecting_write(path, data, **kwargs):
        if str(path).endswith("round-0001.json"):
            observed.append((tmp_path / data["run_key"] / data["payload_artifact"]).exists())
        return original_json(path, data, **kwargs)

    monkeypatch.setattr(artifacts, "atomic_write_json", inspecting_write)
    run(SequenceReducer(["done"]), FixedRoundsController(1), checkpoint_root=tmp_path)
    assert observed == [True]


def test_orphan_payload_is_ignored_and_rebuilt(tmp_path):
    first = SequenceReducer(["one", RuntimeError("stop")])
    with pytest.raises(ReducerExecutionError):
        run(first, FixedRoundsController(2), checkpoint_root=tmp_path)
    run_dir = next(tmp_path.iterdir())
    (run_dir / "round-0002.payload.txt").write_text("orphan")
    resumed = SequenceReducer(["two"])
    result = run(resumed, FixedRoundsController(2), checkpoint_root=tmp_path)
    assert resumed.calls == 1
    assert result.payload == "two"
    assert result.resumed_rounds == 1


def test_terminal_checkpoint_returns_without_rerunning(tmp_path):
    run(SequenceReducer(["done"]), FixedRoundsController(1), checkpoint_root=tmp_path)
    reducer = SequenceReducer([])
    result = run(reducer, FixedRoundsController(1), checkpoint_root=tmp_path)
    assert reducer.calls == 0
    assert result.payload == "done"
    assert result.resumed_rounds == 1


def _make_checkpoint(tmp_path, rounds=1):
    outputs = [f"round-{index}" for index in range(1, rounds + 1)]
    run(SequenceReducer(outputs), FixedRoundsController(rounds), checkpoint_root=tmp_path)
    return next(tmp_path.iterdir())


def test_missing_payload_rejected(tmp_path):
    run_dir = _make_checkpoint(tmp_path)
    (run_dir / "round-0001.payload.txt").unlink()
    with pytest.raises(CheckpointCorruptionError, match="payload"):
        run(SequenceReducer([]), FixedRoundsController(1), checkpoint_root=tmp_path)


def test_output_hash_mismatch_rejected(tmp_path):
    run_dir = _make_checkpoint(tmp_path)
    (run_dir / "round-0001.payload.txt").write_text("tampered")
    with pytest.raises(CheckpointCorruptionError, match="fingerprint"):
        run(SequenceReducer([]), FixedRoundsController(1), checkpoint_root=tmp_path)


def test_policy_metadata_mismatch_rejected(tmp_path):
    run_dir = _make_checkpoint(tmp_path)
    manifest_path = run_dir / "run.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["controller"] = "tampered"
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(CheckpointCompatibilityError, match="controller"):
        run(SequenceReducer([]), FixedRoundsController(1), checkpoint_root=tmp_path)


def test_different_input_has_distinct_run_identity(tmp_path):
    run(SequenceReducer(["a"]), FixedRoundsController(1), checkpoint_root=tmp_path, initial=("a",))
    reducer = SequenceReducer(["b"])
    result = run(reducer, FixedRoundsController(1), checkpoint_root=tmp_path, initial=("b",))
    assert reducer.calls == 1
    assert len(list(tmp_path.iterdir())) == 2
    assert result.payload == "b"


def test_gapped_round_chain_rejected(tmp_path):
    run_dir = _make_checkpoint(tmp_path, rounds=2)
    (run_dir / "round-0001.json").unlink()
    with pytest.raises(CheckpointCorruptionError, match="contiguous"):
        run(SequenceReducer([]), FixedRoundsController(2), checkpoint_root=tmp_path)


def test_broken_parent_chain_rejected(tmp_path):
    run_dir = _make_checkpoint(tmp_path, rounds=2)
    path = run_dir / "round-0002.json"
    data = json.loads(path.read_text())
    data["parent_output_fingerprint"] = "bad"
    path.write_text(json.dumps(data))
    with pytest.raises(CheckpointCorruptionError, match="parent chain"):
        run(SequenceReducer([]), FixedRoundsController(2), checkpoint_root=tmp_path)


def test_corrupt_checkpoint_json_rejected_strictly(tmp_path):
    run_dir = _make_checkpoint(tmp_path)
    (run_dir / "round-0001.json").write_text("{")
    with pytest.raises(CheckpointCorruptionError, match="Cannot read"):
        run(SequenceReducer([]), FixedRoundsController(1), checkpoint_root=tmp_path)


def test_sequence_fingerprint_preserves_item_boundaries():
    from czjLLM.reduction.artifacts import text_sequence_fingerprint

    assert text_sequence_fingerprint(["ab", "c"]) != text_sequence_fingerprint(["a", "bc"])
