# tests/test_process_prompt_and_merge_di.py
import os
from dataclasses import dataclass
from pathlib import Path
import pytest

# 假設目標函式在這個模組底下
import czjLLM.prompt_pipeline.pipeline_controller as pc
import czjLLM.utilities.env_overrides as env_utils

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
        self.calls["combine_task"] = []

    def _fake_list_paths(self, root: str) -> list[str]:
        return self._mapping.get(root, [])

    def _fake_get_parent(self, fn: str) -> str:
        return str(Path(fn).parent)

    def _fake_call_llm(self, items, ctx, allow_to_retry: bool):
        # 記錄呼叫行為，避免真的連網
        self.calls["call_llm"].append((tuple(items), allow_to_retry, getattr(ctx, "task", None)))

    def _fake_combine(self, item_dir: str, ctx) -> str:
        self.calls["combine"].append(item_dir)
        self.calls["combine_task"].append(getattr(ctx, "task", None))
        # 直接回傳一個假路徑；也可以寫檔到 tmp_path
        return self._combine_return or str(Path(item_dir) / "combined.out.txt")


@pytest.mark.unit
def test_resolve_llm_debug_flags_uses_stage_defaults_when_env_missing(monkeypatch):
    monkeypatch.setattr(env_utils, "_ENV_FILE_LOADED", True)
    monkeypatch.delenv("CZJLLM_DEBUG_PRINT_LLM_IO", raising=False)
    monkeypatch.delenv("CZJLLM_DEBUG_PRINT_MAX_CHARS", raising=False)
    enabled, max_chars = pc._resolve_llm_debug_flags(stage_debug_enabled=False, stage_debug_max_chars=2000)
    assert enabled is False
    assert max_chars == 2000


@pytest.mark.unit
def test_resolve_llm_debug_flags_allows_env_override(monkeypatch):
    monkeypatch.setattr(env_utils, "_ENV_FILE_LOADED", True)
    monkeypatch.setenv("CZJLLM_DEBUG_PRINT_LLM_IO", "true")
    monkeypatch.setenv("CZJLLM_DEBUG_PRINT_MAX_CHARS", "-1")
    enabled, max_chars = pc._resolve_llm_debug_flags(stage_debug_enabled=False, stage_debug_max_chars=2000)
    assert enabled is True
    assert max_chars == -1


@pytest.mark.unit
def test_env_file_priority(monkeypatch, tmp_path):
    (tmp_path / ".env").write_text("X=base\n", encoding="utf-8")
    (tmp_path / ".env.dev").write_text("X=dev\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("X=local\n", encoding="utf-8")
    monkeypatch.setenv("CZJLLM_ENV", "dev")
    monkeypatch.delenv("X", raising=False)
    monkeypatch.setattr(env_utils, "_ENV_FILE_LOADED", False)
    env_utils.load_czjllm_env_files_once(base_dir=str(tmp_path))
    assert os.environ.get("X") == "local"

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
def test_collect_prompt_items_supports_todo_stage_subdirs(tmp_path):
    root = tmp_path / "root"
    main = "abc"
    mapping = {
        str(root): [
            str(root / f"{main}_1" / "TODO" / "stage_a" / "c.txt"),
            str(root / f"{main}_2" / "Success" / "stage_b" / "d.txt"),
        ]
    }
    ops = FakeOps(mapping)

    items = pc._collect_prompt_items(str(root), main, ops)
    assert items == [str(root / f"{main}_1"), str(root / f"{main}_2")]


@pytest.mark.unit
def test_recover_running_to_todo_preserves_nested_subdirs(tmp_path):
    item = tmp_path / "item_a"
    run_nested = item / "RUNNING" / "stage_x"
    todo_nested = item / "TODO" / "stage_x"
    run_nested.mkdir(parents=True)
    (run_nested / "1.txt").write_text("X", encoding="utf-8")

    pc.recover_running_to_todo([str(item)])

    assert (todo_nested / "1.txt").exists()
    assert not (run_nested / "1.txt").exists()


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
    # 多階段最終 combine 名稱已改為「由 stage key/name 組成」，
    # 不再直接使用最後一段 task 文字。
    assert ops.calls["combine_task"] == ["extract_classify", "extract_classify"]
    assert ctx.task == "legacy-task"
    assert out == str(item_b / "combined.out.txt")


@pytest.mark.unit
def test_multistage_final_combine_uses_safe_task_name_when_stage_task_is_mapping(tmp_path):
    root = tmp_path / "root"
    main = "mstage_map"
    item = root / f"{main}_a"
    mapping = {
        str(root): [str(item / "TODO" / "1.txt")],
        str(item / "TODO"): [],
    }
    ops = FakeOps(mapping)
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "extract", "task": "抽取"},
            {"name": "summarize", "task": {"CT_name": "以繁體中文摘要", "template": lambda content: content}},
        ],
    )
    ctx.taskSetting = {
        "extract": "抽取",
        "summarize": {"CT_name": "以繁體中文摘要", "template": lambda content: content},
    }

    out = pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    called_tasks = [c[2] for c in ops.calls["call_llm"]]
    assert called_tasks.count("抽取") == 2
    assert called_tasks.count("summarize") == 2
    # 多階段最終 combine 名稱已改為「由 stage key/name 組成」。
    assert ops.calls["combine_task"] == ["extract_summarize"]
    assert ctx.task == "legacy-task"
    assert out == str(item / "combined.out.txt")


@pytest.mark.unit
def test_multistage_final_combine_uses_stage_name_for_freeform_prompt(tmp_path):
    root = tmp_path / "root"
    main = "mstage_prompt"
    item = root / f"{main}_a"
    mapping = {
        str(root): [str(item / "TODO" / "1.txt")],
        str(item / "TODO"): [],
    }
    ops = FakeOps(mapping)
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "route", "prompt": "你是分類器，只輸出 JSON"},
            {"name": "extract", "prompt": "請抽取欄位"},
        ],
    )

    out = pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    assert ops.calls["combine_task"] == ["route_extract"]
    assert ctx.task == "legacy-task"
    assert out == str(item / "combined.out.txt")


@pytest.mark.unit
def test_multistage_nonfirst_stage_todo_is_rendered_with_stage_template(tmp_path):
    root = tmp_path / "root"
    main = "stage_prompt"
    item = root / f"{main}_a"
    todo_dir = item / "TODO"
    success_dir = item / "Success"
    todo_dir.mkdir(parents=True)
    success_dir.mkdir(parents=True)
    (todo_dir / "1.txt").write_text("FIRST_STAGE_INPUT", encoding="utf-8")

    records: list[tuple[str, str]] = []

    def list_paths(path: str) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [str(x) for x in sorted(p.rglob("*.txt"))]

    def call_llm(items, _ctx, allow_to_retry: bool, task_override=None):
        for item_dir in items:
            todo = Path(item_dir) / "TODO"
            succ = Path(item_dir) / "Success"
            succ.mkdir(parents=True, exist_ok=True)
            for pf in sorted(todo.glob("*.txt")):
                text = pf.read_text(encoding="utf-8")
                records.append((str(task_override), text))
                (succ / pf.name).write_text(text, encoding="utf-8")
                pf.unlink()

    ops = pc.MergeOps(
        list_paths=list_paths,
        get_parent=lambda fn: str(Path(fn).parent),
        call_llm=call_llm,
        combine=lambda item_dir, _ctx: str(Path(item_dir) / "combined.out.txt"),
        join=lambda *p: str(Path(*p)),
    )
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "pdf_opt", "task": "PDF OPT-Instruction First", "input_from": "original"},
            {"name": "en_to_zh", "task": {"CT_name": "Translation-toTWZH", "template": lambda content: f"TW::{content}"}, "input_from": "previous"},
        ],
    )

    pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    stage2_records = [x for x in records if x[0] == "Translation-toTWZH"]
    assert stage2_records


@pytest.mark.unit
def test_multistage_forced_stage_merge_when_sql_writeback_rule_requests_stage(tmp_path):
    root = tmp_path / "root"
    main = "stage_force_merge"
    item = root / main
    todo_dir = item / "TODO"
    success_dir = item / "Success"
    todo_dir.mkdir(parents=True)
    success_dir.mkdir(parents=True)
    (todo_dir / "0.txt").write_text("RAW_INPUT", encoding="utf-8")

    def list_paths(path: str) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [str(x) for x in sorted(p.rglob("*.txt"))]

    def call_llm(items, _ctx, allow_to_retry: bool, task_override=None):
        for item_dir in items:
            todo = Path(item_dir) / "TODO"
            succ = Path(item_dir) / "Success"
            succ.mkdir(parents=True, exist_ok=True)
            for pf in sorted(todo.glob("*.txt")):
                # 模擬 stage 有輸出且寫回 Success
                (succ / pf.name).write_text(f"{task_override}::{pf.read_text(encoding='utf-8')}", encoding="utf-8")
                pf.unlink()

    ops = pc.MergeOps(
        list_paths=list_paths,
        get_parent=lambda fn: str(Path(fn).parent),
        call_llm=call_llm,
        combine=lambda item_dir, _ctx: str(Path(item_dir) / "combined.out.txt"),
        join=lambda *p: str(Path(*p)),
    )
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "route", "task": "ROUTE", "persist_output": "always"},
            {"name": "extract", "task": "EXTRACT", "persist_output": "final"},
            {"name": "audit_json", "task": "AUDIT", "persist_output": "always"},
        ],
    )
    # 重點：雖然 extract 非最後一段（persist_output=final），
    # 但 sql_writeback_rules 指定 source=stage:extract 時，必須輸出 merged file 供寫回使用。
    ctx.sql_writeback_rules = [{"output_col": "File_result", "source": "stage", "stage": "extract"}]
    ctx.temp_txt_finished_dir = str(tmp_path / "finished")

    pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    manifest = Path(ctx.temp_txt_finished_dir) / "_stage_merges" / main / "manifest.json"
    assert manifest.exists()
    data = __import__("json").loads(manifest.read_text(encoding="utf-8"))
    extract = [s for s in data.get("stages", []) if s.get("name") == "extract"][0]
    assert extract.get("merged") is True
    assert str(extract.get("merged_file", "")).strip() != ""


@pytest.mark.unit
def test_multistage_warns_when_nonlast_stage_uses_final_persist_without_writeback(tmp_path, capsys):
    root = tmp_path / "root"
    main = "stage_warn_final_mid"
    item = root / main
    todo_dir = item / "TODO"
    success_dir = item / "Success"
    todo_dir.mkdir(parents=True)
    success_dir.mkdir(parents=True)
    (todo_dir / "0.txt").write_text("RAW_INPUT", encoding="utf-8")

    def list_paths(path: str) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [str(x) for x in sorted(p.rglob("*.txt"))]

    def call_llm(items, _ctx, allow_to_retry: bool, task_override=None):
        for item_dir in items:
            todo = Path(item_dir) / "TODO"
            succ = Path(item_dir) / "Success"
            succ.mkdir(parents=True, exist_ok=True)
            for pf in sorted(todo.glob("*.txt")):
                (succ / pf.name).write_text(f"{task_override}::{pf.read_text(encoding='utf-8')}", encoding="utf-8")
                pf.unlink()

    ops = pc.MergeOps(
        list_paths=list_paths,
        get_parent=lambda fn: str(Path(fn).parent),
        call_llm=call_llm,
        combine=lambda item_dir, _ctx: str(Path(item_dir) / "combined.out.txt"),
        join=lambda *p: str(Path(*p)),
    )
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "route", "task": "ROUTE", "persist_output": "always"},
            {"name": "extract", "task": "EXTRACT", "persist_output": "final"},
            {"name": "audit_json", "task": "AUDIT", "persist_output": "always"},
        ],
    )
    ctx.temp_txt_finished_dir = str(tmp_path / "finished")

    pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    out = capsys.readouterr().out
    assert "persist_output=final 但非最後一段" in out


@pytest.mark.unit
def test_multistage_full_restart_clears_existing_success_files(tmp_path):
    root = tmp_path / "root"
    main = "restart_mode"
    item = root / f"{main}_a"
    todo_dir = item / "TODO"
    success_dir = item / "Success"
    todo_dir.mkdir(parents=True)
    success_dir.mkdir(parents=True)
    (todo_dir / "1.txt").write_text("P1", encoding="utf-8")
    stale_success = success_dir / "stale.txt"
    stale_success.write_text("OLD", encoding="utf-8")

    def list_paths(path: str) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [str(x) for x in sorted(p.rglob("*.txt"))]

    def call_llm(items, _ctx, allow_to_retry: bool, task_override=None):
        for item_dir in items:
            todo = Path(item_dir) / "TODO"
            succ = Path(item_dir) / "Success"
            succ.mkdir(parents=True, exist_ok=True)
            for pf in sorted(todo.glob("*.txt")):
                (succ / pf.name).write_text(pf.read_text(encoding="utf-8"), encoding="utf-8")
                pf.unlink()

    ops = pc.MergeOps(
        list_paths=list_paths,
        get_parent=lambda fn: str(Path(fn).parent),
        call_llm=call_llm,
        combine=lambda item_dir, _ctx: str(Path(item_dir) / "combined.out.txt"),
        join=lambda *p: str(Path(*p)),
    )
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "s1", "task": "PDF OPT-Instruction First"},
            {"name": "s2", "task": "Summary-toTWZH"},
        ],
    )
    ctx.resume_policy = "full_restart"

    pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    assert not stale_success.exists()


@pytest.mark.unit
def test_multistage_smart_reset_clears_stage_output_snapshots(tmp_path):
    root = tmp_path / "root"
    main = "smart_mode"
    item = root / f"{main}_a"
    todo_dir = item / "TODO"
    success_dir = item / "Success"
    stage_out = item / "_stage_outputs" / "old_stage"
    todo_dir.mkdir(parents=True)
    success_dir.mkdir(parents=True)
    stage_out.mkdir(parents=True)
    (todo_dir / "1.txt").write_text("P1", encoding="utf-8")
    stale_snapshot = stage_out / "stale.txt"
    stale_snapshot.write_text("OLD", encoding="utf-8")

    def list_paths(path: str) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [str(x) for x in sorted(p.rglob("*.txt"))]

    def call_llm(items, _ctx, allow_to_retry: bool, task_override=None):
        for item_dir in items:
            todo = Path(item_dir) / "TODO"
            succ = Path(item_dir) / "Success"
            succ.mkdir(parents=True, exist_ok=True)
            for pf in sorted(todo.glob("*.txt")):
                (succ / pf.name).write_text(pf.read_text(encoding="utf-8"), encoding="utf-8")
                pf.unlink()

    ops = pc.MergeOps(
        list_paths=list_paths,
        get_parent=lambda fn: str(Path(fn).parent),
        call_llm=call_llm,
        combine=lambda item_dir, _ctx: str(Path(item_dir) / "combined.out.txt"),
        join=lambda *p: str(Path(*p)),
    )
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "s1", "task": "PDF OPT-Instruction First"},
            {"name": "s2", "task": "Summary-toTWZH"},
        ],
    )
    ctx.resume_policy = "smart_reset"

    pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    assert not stale_snapshot.exists()


@pytest.mark.unit
def test_single_stage_full_restart_clears_existing_success_files(tmp_path):
    root = tmp_path / "root"
    main = "single_restart"
    item = root / f"{main}_a"
    todo_dir = item / "TODO"
    success_dir = item / "Success"
    todo_dir.mkdir(parents=True)
    success_dir.mkdir(parents=True)
    (todo_dir / "1.txt").write_text("P1", encoding="utf-8")
    stale_success = success_dir / "stale.txt"
    stale_success.write_text("OLD", encoding="utf-8")

    def list_paths(path: str) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [str(x) for x in sorted(p.rglob("*.txt"))]

    def call_llm(items, _ctx, allow_to_retry: bool):
        for item_dir in items:
            todo = Path(item_dir) / "TODO"
            succ = Path(item_dir) / "Success"
            succ.mkdir(parents=True, exist_ok=True)
            for pf in sorted(todo.glob("*.txt")):
                (succ / pf.name).write_text(pf.read_text(encoding="utf-8"), encoding="utf-8")
                pf.unlink()

    ops = pc.MergeOps(
        list_paths=list_paths,
        get_parent=lambda fn: str(Path(fn).parent),
        call_llm=call_llm,
        combine=lambda item_dir, _ctx: str(Path(item_dir) / "combined.out.txt"),
        join=lambda *p: str(Path(*p)),
    )
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[{"name": "s1", "task": "PDF OPT-Instruction First"}],
    )
    ctx.resume_policy = "full_restart"

    pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)
    assert not stale_success.exists()
    resume_log = root / "_resume_logs" / "resume_events.log"
    assert resume_log.exists()
    assert "resume_policy=full_restart" in resume_log.read_text(encoding="utf-8")


@pytest.mark.unit
def test_multistage_stage1_bootstrap_ignores_nested_stage_todo(tmp_path):
    root = tmp_path / "root"
    main = "bootstrap_guard"
    item = root / f"{main}_a"
    todo_dir = item / "TODO"
    success_dir = item / "Success"
    nested_old = todo_dir / "old_stage"
    todo_dir.mkdir(parents=True)
    success_dir.mkdir(parents=True)
    nested_old.mkdir(parents=True)
    (todo_dir / "1.txt").write_text("ROOT_PROMPT", encoding="utf-8")
    (nested_old / "old.txt").write_text("STALE_NESTED", encoding="utf-8")

    records: list[tuple[str, str]] = []

    def list_paths(path: str) -> list[str]:
        p = Path(path)
        if not p.exists():
            return []
        return [str(x) for x in sorted(p.rglob("*.txt"))]

    def call_llm(items, _ctx, allow_to_retry: bool, task_override=None):
        for item_dir in items:
            todo = Path(item_dir) / "TODO"
            succ = Path(item_dir) / "Success"
            succ.mkdir(parents=True, exist_ok=True)
            for pf in sorted(todo.glob("*.txt")):
                text = pf.read_text(encoding="utf-8")
                records.append((str(task_override), text))
                (succ / pf.name).write_text(text, encoding="utf-8")
                pf.unlink()

    ops = pc.MergeOps(
        list_paths=list_paths,
        get_parent=lambda fn: str(Path(fn).parent),
        call_llm=call_llm,
        combine=lambda item_dir, _ctx: str(Path(item_dir) / "combined.out.txt"),
        join=lambda *p: str(Path(*p)),
    )
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[
            {"name": "pdf_opt", "task": "PDF OPT-Instruction First", "input_from": "original"},
            {"name": "en_to_zh", "task": {"CT_name": "Translation-toTWZH", "template": lambda content: f"TW::{content}"}, "input_from": "previous"},
        ],
    )
    pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)

    stage1_records = [x for x in records if x[0] == "PDF OPT-Instruction First"]
    assert stage1_records
    assert all("STALE_NESTED" not in txt for _, txt in stage1_records)


@pytest.mark.unit
def test_process_prompt_and_merge_raises_when_explicit_stages_parse_fails(tmp_path, monkeypatch):
    root = tmp_path / "root"
    main = "in_stage_err"
    item = root / main
    (item / "TODO").mkdir(parents=True)
    (item / "Success").mkdir(parents=True)
    (item / "TODO" / "0.txt").write_text("x", encoding="utf-8")

    ops = pc.MergeOps(
        list_paths=lambda p: [str(x) for x in Path(p).rglob("*.txt")] if Path(p).exists() else [],
        get_parent=lambda fn: str(Path(fn).parent),
        call_llm=lambda *a, **k: None,
        combine=lambda item_dir, _ctx: str(Path(item_dir) / "combined.out.txt"),
        join=lambda *p: str(Path(*p)),
    )
    ctx = DummyCtx(
        prompt_dir=str(root),
        main_file_name=main,
        task="legacy-task",
        stages=[{"name": "route", "prompt": "p1"}, {"name": "extract", "task_key": "k2"}],
    )

    def _boom(_ctx):
        raise ValueError("bad stage cfg")

    monkeypatch.setattr(pc, "resolve_pipeline_stages", _boom)

    with pytest.raises(RuntimeError, match="多階段設定解析失敗"):
        pc.process_prompt_and_merge(ctx, file_path=str(tmp_path / "src" / f"{main}.txt"), ops=ops)


def test_process_prompt_and_merge_uses_stage_flow_for_explicit_single_stage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from czjLLM.prompt_pipeline import pipeline_controller as pc

    ctx = SimpleNamespace(
        prompt_dir=str(tmp_path / "prompt"),
        main_file_name="row1",
        task="legacy",
        stages=[{"name": "extract", "task": "ExtractTask"}],
        taskSetting={},
    )
    src = tmp_path / "row1.txt"
    src.write_text("input", encoding="utf-8")
    calls = {"multi": 0}

    def _fake_multistage(_ctx, file_path, ops=None, max_rounds=20):
        calls["multi"] += 1
        return "merged.txt"

    monkeypatch.setattr(pc, "process_prompt_and_merge_multistage", _fake_multistage)

    out = pc.process_prompt_and_merge(ctx, str(src))

    assert out == "merged.txt"
    assert calls["multi"] == 1
