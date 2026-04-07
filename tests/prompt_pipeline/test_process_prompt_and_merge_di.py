# tests/test_process_prompt_and_merge_di.py
from dataclasses import dataclass
from pathlib import Path
import pytest

# 假設目標函式在這個模組底下
import czjLLM.prompt_pipeline.pipeline_controller as pc

@dataclass
class DummyCtx:
    prompt_dir: str
    main_file_name: str
    task: str = "demo-task"
    stages: list[dict[str, str]] | None = None

class FakeOps(pc.MergeOps):
    def __init__(self, mapping: dict[str, list[str]]):
        """
        mapping: 根目錄 -> 該目錄底下的「檔案清單（完整路徑字串）」
        我們用它來模擬 OSWALK 回傳。
        """
        self._mapping = mapping
        super().__init__(
            list_paths=self._fake_list_paths,
            get_parent=self._fake_get_parent,
            call_llm=self._fake_call_llm,
            combine=self._fake_combine,
            join=lambda *p: str(Path(*p)),
        )
        self.calls = {"call_llm": []}
        self._combine_return = None  # 測試可指定回傳
        self.calls["combine"] = []

    def _fake_list_paths(self, root: str) -> list[str]:
        return self._mapping.get(root, [])

    def _fake_get_parent(self, fn: str) -> str:
        return str(Path(fn).parent)

    def _fake_call_llm(self, items, ctx, allow_to_retry: bool):
        # 記錄呼叫行為，避免真的連網
        self.calls["call_llm"].append((tuple(items), allow_to_retry, getattr(ctx, "task", None)))

    def _fake_combine(self, item_dir: str, ctx) -> str:
        self.calls["combine"].append(item_dir)
        # 直接回傳一個假路徑；也可以寫檔到 tmp_path
        return self._combine_return or str(Path(item_dir) / "combined.out.txt")

@pytest.mark.unit
def test_merge_happy_path_no_todo(tmp_path):
    # 目錄佈局（邏輯上）
    # ctx.prompt_dir 底下的 OSWALK 會看到兩個檔案：
    #   /root/<main>/TODO/a.txt
    #   /root/<main>/Success/b.txt
    root = tmp_path / "root"
    main = "in1"
    todo_file   = root / f"{main}" / "TODO"    / "a.txt"
    success_file= root / f"{main}" / "Success" / "b.txt"

    # 我們不真的建立檔案，FakeOps 直接回傳這些「假路徑字串」
    mapping = {
        str(root): [str(todo_file), str(success_file)],       # 列舉 prompt_dir
        str(root / f"{main}" / "TODO"):   [],                 # TODO 已清空 → 可合併
        str(root / f"{main}" / "Success"): [],                # 不影響
    }
    ops = FakeOps(mapping)
    ctx = DummyCtx(prompt_dir=str(root), main_file_name=main)

    out = pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    # 斷言：call_llm 被呼叫兩次（允許重試 / 不允許）
    assert ops.calls["call_llm"] == [(((str(root / f"{main}")),), True, "demo-task"),
                                     (((str(root / f"{main}")),), False, "demo-task")]

    # 斷言：合併輸出路徑
    assert out.endswith("combined.out.txt")

@pytest.mark.unit
def test_merge_with_todo_remaining(tmp_path, capsys):
    root = tmp_path / "root"
    main = "in2"
    todo_file   = root / f"{main}" / "TODO"    / "x.txt"

    mapping = {
        str(root): [str(todo_file)],           # 只看到 TODO
        str(root / f"{main}" / "TODO"): [str(todo_file)],  # 仍有 TODO → 不合併
    }
    ops = FakeOps(mapping)
    ctx = DummyCtx(prompt_dir=str(root), main_file_name=main)

    out = pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    # 仍會呼叫 LLM 兩次
    assert len(ops.calls["call_llm"]) == 2
    # 因為還有 TODO，out 應為空字串
    assert out == ""

    # 可檢查訊息
    stdout = capsys.readouterr().out
    assert "尚有 1 個段落未處理" in stdout

@pytest.mark.unit
def test_merge_returns_empty_when_no_prompt_items(tmp_path):
    root = tmp_path / "root"
    main = "in3"

    # prompt_dir 下有檔案，但都不在 TODO/Success 目錄
    mapping = {
        str(root): [str(root / main / "Other" / "x.txt")],
    }
    ops = FakeOps(mapping)
    ctx = DummyCtx(prompt_dir=str(root), main_file_name=main)

    out = pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    assert out == ""
    assert ops.calls["call_llm"] == []
    assert ops.calls["combine"] == []

@pytest.mark.unit
def test_merge_deduplicates_and_sorts_prompt_items(tmp_path):
    root = tmp_path / "root"
    main = "topic"
    item_a = root / f"{main}_a"
    item_b = root / f"{main}_b"

    mapping = {
        # 故意放重複與亂序，驗證 sorted(set(...)) 的穩定輸出
        str(root): [
            str(item_b / "TODO" / "1.txt"),
            str(item_a / "TODO" / "2.txt"),
            str(item_b / "Success" / "3.txt"),
        ],
        str(item_a / "TODO"): [],
        str(item_b / "TODO"): [],
    }
    ops = FakeOps(mapping)
    ctx = DummyCtx(prompt_dir=str(root), main_file_name=main)

    out = pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    expected_items = (str(item_a), str(item_b))
    assert ops.calls["call_llm"] == [(expected_items, True, "demo-task"), (expected_items, False, "demo-task")]
    assert ops.calls["combine"] == [str(item_a), str(item_b)]
    assert out == str(item_b / "combined.out.txt")

@pytest.mark.unit
def test_merge_keeps_last_non_empty_combine_result(tmp_path):
    root = tmp_path / "root"
    main = "in4"
    item_a = root / f"{main}_a"
    item_b = root / f"{main}_b"

    mapping = {
        str(root): [
            str(item_a / "TODO" / "1.txt"),
            str(item_b / "TODO" / "2.txt"),
        ],
        str(item_a / "TODO"): [],
        str(item_b / "TODO"): [],
    }
    ops = FakeOps(mapping)
    combine_outputs = ["", str(item_b / "merged-final.txt")]

    def combine_seq(item_dir: str, ctx):
        ops.calls["combine"].append(item_dir)
        return combine_outputs.pop(0)

    ops.combine = combine_seq
    ctx = DummyCtx(prompt_dir=str(root), main_file_name=main)

    out = pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    assert out == str(item_b / "merged-final.txt")
    assert ops.calls["combine"] == [str(item_a), str(item_b)]


@pytest.mark.unit
def test_collect_prompt_items_filters_and_sorts(tmp_path):
    root = tmp_path / "root"
    main = "abc"
    mapping = {
        str(root): [
            str(root / "zzz" / "TODO" / "a.txt"),         # main 不匹配，應排除
            str(root / f"{main}_2" / "Success" / "b.txt"),
            str(root / f"{main}_1" / "TODO" / "c.txt"),
            str(root / f"{main}_2" / "TODO" / "d.txt"),   # duplicate item
        ]
    }
    ops = FakeOps(mapping)

    items = pc._collect_prompt_items(str(root), main, ops)
    assert items == [str(root / f"{main}_1"), str(root / f"{main}_2")]


@pytest.mark.unit
def test_multistage_process_runs_stage_tasks_and_combines(tmp_path):
    root = tmp_path / "root"
    main = "mstage"
    item_a = root / f"{main}_a"
    item_b = root / f"{main}_b"
    mapping = {
        str(root): [
            str(item_a / "TODO" / "1.txt"),
            str(item_b / "TODO" / "2.txt"),
        ],
        str(item_a / "TODO"): [],
        str(item_b / "TODO"): [],
    }
    ops = FakeOps(mapping)
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "extract", "task": "抽取"},
            {"name": "classify", "task": "分類"},
        ],
    )

    out = pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    # 2 chunks x 2 stages x retry/no-retry = 8 次
    assert len(ops.calls["call_llm"]) == 8
    called_tasks = [c[2] for c in ops.calls["call_llm"]]
    assert called_tasks.count("抽取") == 4
    assert called_tasks.count("分類") == 4
    assert ops.calls["combine"] == [str(item_a), str(item_b)]
    assert out == str(item_b / "combined.out.txt")
