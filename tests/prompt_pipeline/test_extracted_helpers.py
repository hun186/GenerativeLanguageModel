import sys
import types


class _OpenCC:
    def __init__(self, *args, **kwargs):
        pass

    def convert(self, text):
        return text


sys.modules.setdefault("opencc", types.SimpleNamespace(OpenCC=_OpenCC))
sys.modules.setdefault("json_repair", types.SimpleNamespace(repair_json=lambda text, **kwargs: text))

from pathlib import Path
from types import SimpleNamespace

from czjLLM.prompt_pipeline.runtime_support.load_meter import ItemsRegistry, meter_init, meter_path_init, meter_read, meter_update
from czjLLM.prompt_pipeline.runtime_support.prompt_queue import pick_and_claim_next_prompts, recover_running_to_todo


def test_items_registry_update_and_remove():
    registry = ItemsRegistry()

    registry.add("item-a", pk="pk-1", temp_txt="row.txt", comb_back_fn="combined.json")
    registry.update("item-a", status="ready_for_writeback")

    assert registry.get("item-a") == {
        "pk": "pk-1",
        "temp_txt": "row.txt",
        "CombBackFN": "combined.json",
        "status": "ready_for_writeback",
    }
    assert registry.list_items()["item-a"]["pk"] == "pk-1"

    registry.remove("item-a")
    assert registry.get("item-a") is None


def test_meter_init_and_update_round_trip(tmp_path):
    ctx = SimpleNamespace(PGMSubDir=str(tmp_path), n_process=2)
    meter_fn = meter_path_init(ctx)

    data = meter_init(meter_fn, ctx)
    assert data["thresholds"] == {"low": 4, "high": 6}
    assert Path(meter_fn).exists()

    def mutate(meter):
        meter["queue"]["pending"] = 3
        meter["rows"]["pk-1"] = {"done": 1}

    updated = meter_update(meter_fn, mutate)
    assert updated["queue"]["pending"] == 3
    assert meter_read(meter_fn)["rows"]["pk-1"] == {"done": 1}


def test_prompt_queue_claim_and_recover(tmp_path):
    item_dir = tmp_path / "item"
    todo = item_dir / "TODO"
    todo.mkdir(parents=True)
    (todo / "b.txt").write_text("b", encoding="utf-8")
    (todo / "a.txt").write_text("a", encoding="utf-8")

    claimed = pick_and_claim_next_prompts([str(item_dir)], per_round_limit=1)

    assert len(claimed) == 1
    running_path, claimed_item_dir = claimed[0]
    assert claimed_item_dir == str(item_dir)
    assert Path(running_path).parent.name == "RUNNING"
    assert Path(running_path).name == "a.txt"
    assert not (todo / "a.txt").exists()

    moved = recover_running_to_todo([str(item_dir)])
    assert moved == 1
    assert (todo / "a.txt").exists()
