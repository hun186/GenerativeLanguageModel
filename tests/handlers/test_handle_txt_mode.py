# tests/test_handle_txt_mode.py
import os
import types
import pytest

# 目標模組
from czjLLM.handlers import handle_txt_file as mod


@pytest.mark.unit
def test_handle_single_input_file_happy_path(monkeypatch, tmp_path):
    """應呼叫切片→顯示樣板→倒數→合併→建立目的資料夾→搬移，且只在第一次顯示樣板。"""
    # 準備假 ctx
    class Ctx: pass
    ctx = Ctx()
    ctx.task = "Summary-toTWZH"
    ctx.llm_source_dir = str(tmp_path / "src")
    ctx.llm_source_backup_dir = str(tmp_path / "bak")
    ctx.prompt_dir = str(tmp_path / "prompts")
    os.makedirs(ctx.llm_source_dir, exist_ok=True)

    # 建立假輸入檔
    f1 = tmp_path / "src" / "in1.txt"
    f1.write_text("hello")

    # 記錄呼叫
    calls = {
        "process_file_to_prompt": [],
        "showTemplate": 0,
        "countdown_pause": [],
        "process_prompt_and_merge": [],
        "MKDIR": [],
        "move": [],
    }

    # ---- mock 相依 ----
    monkeypatch.setattr(mod, "process_file_to_prompt",
                        lambda file, c, adjust=True: calls["process_file_to_prompt"].append((file, adjust)))
    monkeypatch.setattr(mod, "showTemplate",
                        lambda task=None: calls.__setitem__("showTemplate", calls["showTemplate"] + 1))
    monkeypatch.setattr(mod, "countdown_pause",
                        lambda secs: calls["countdown_pause"].append(secs))
    monkeypatch.setattr(mod, "process_prompt_and_merge",
                        lambda c, file: calls["process_prompt_and_merge"].append((c, file)))
    # 目標路徑：模擬把來源檔改到 bak/moved/in1.txt
    monkeypatch.setattr(mod, "DirReplace", lambda file, src, bak: os.path.join(bak, "moved", os.path.basename(file)))
    monkeypatch.setattr(mod, "getPathFromFN", lambda p: os.path.dirname(p))
    monkeypatch.setattr(mod, "MKDIR", lambda d: calls["MKDIR"].append(d))
    monkeypatch.setattr(mod.shutil, "move", lambda s, d: calls["move"].append((s, d)))

    # ---- 執行 ----
    mod.handle_single_input_file(str(f1), ctx, adjust=True, pause_seconds=3, defer_merge=False)

    # ---- 斷言 ----
    assert calls["process_file_to_prompt"] == [(str(f1), True)]
    assert calls["showTemplate"] == 1
    assert calls["countdown_pause"] == [3]
    assert calls["process_prompt_and_merge"] == [(ctx, str(f1))]
    # MKDIR 目標資料夾正確
    assert calls["MKDIR"] and calls["MKDIR"][0].endswith(os.path.join("bak", "moved"))
    # 最終搬移目標正確
    assert calls["move"] and calls["move"][0][0] == str(f1)
    assert calls["move"][0][1].endswith(os.path.join("bak", "moved", "in1.txt"))

    # 再處理第二個檔案，確認 showTemplate 只會在第一次出現
    f2 = tmp_path / "src" / "in2.txt"
    f2.write_text("world")
    mod.handle_single_input_file(str(f2), ctx, pause_seconds=0, defer_merge=False)
    # 倒數只被呼叫一次，且參數為第一次呼叫時的 pause_seconds（3）
    assert len(calls["countdown_pause"]) == 1
    assert calls["countdown_pause"][0] == 3


@pytest.mark.unit
def test_handle_single_input_file_defer_merge(monkeypatch, tmp_path):
    """defer_merge=True 時，應在顯示樣板/倒數後提前返回，不進行合併與搬移。"""
    class Ctx: pass
    ctx = Ctx()
    ctx.task = "Summary-toTWZH"
    ctx.llm_source_dir = str(tmp_path / "src")
    ctx.llm_source_backup_dir = str(tmp_path / "bak")
    ctx.prompt_dir = str(tmp_path / "prompts")
    os.makedirs(ctx.llm_source_dir, exist_ok=True)

    f = tmp_path / "src" / "in.txt"
    f.write_text("content")

    flags = {"merged": False, "moved": False, "shown": 0, "paused": []}

    monkeypatch.setattr(mod, "process_file_to_prompt", lambda *a, **k: None)
    monkeypatch.setattr(mod, "showTemplate", lambda **k: flags.__setitem__("shown", flags["shown"] + 1))
    monkeypatch.setattr(mod, "countdown_pause", lambda s: flags["paused"].append(s))
    monkeypatch.setattr(mod, "process_prompt_and_merge", lambda *a, **k: flags.__setitem__("merged", True))
    monkeypatch.setattr(mod.shutil, "move", lambda *a, **k: flags.__setitem__("moved", True))

    mod.handle_single_input_file(str(f), ctx, pause_seconds=5, defer_merge=True)

    assert flags["shown"] == 1
    assert flags["paused"] == [5]
    assert not flags["merged"]
    assert not flags["moved"]


@pytest.mark.unit
def test_handle_single_input_file_freeform_task_skips_template_preview(monkeypatch, tmp_path):
    """task 不是 taskSetting 鍵值時，不應中斷流程。"""
    class Ctx: pass
    ctx = Ctx()
    ctx.task = "你是分類器，只輸出 JSON"
    ctx.llm_source_dir = str(tmp_path / "src")
    ctx.llm_source_backup_dir = str(tmp_path / "bak")
    ctx.prompt_dir = str(tmp_path / "prompts")
    os.makedirs(ctx.llm_source_dir, exist_ok=True)

    f = tmp_path / "src" / "in.txt"
    f.write_text("content")

    flags = {"show_called": 0, "paused": [], "logs": []}

    monkeypatch.setattr(mod, "process_file_to_prompt", lambda *a, **k: None)
    monkeypatch.setattr(mod, "showTemplate", lambda **k: flags.__setitem__("show_called", flags["show_called"] + 1))
    monkeypatch.setattr(mod, "countdown_pause", lambda s: flags["paused"].append(s))
    monkeypatch.setattr(mod, "tlog", lambda s: flags["logs"].append(s))

    mod.handle_single_input_file(str(f), ctx, pause_seconds=2, defer_merge=True)

    assert flags["show_called"] == 0
    assert flags["paused"] == [2]
    assert any("自訂任務" in x for x in flags["logs"])


@pytest.mark.unit
def test_handle_txt_mode_flow_and_first_pause(monkeypatch, tmp_path):
    """應列出 .txt 並依序處理；第一個檔案 pause_seconds=10，其餘為 0；最後清空空目錄。"""
    # 假檔案清單（含非 .txt）
    a = str(tmp_path / "a.txt")
    b = str(tmp_path / "b.txt")
    c = str(tmp_path / "c.csv")

    # ctx 與 args
    class Ctx: pass
    ctx = Ctx()
    ctx.llm_source_dir = str(tmp_path / "src")
    ctx.prompt_dir = str(tmp_path / "prompts")
    os.makedirs(ctx.llm_source_dir, exist_ok=True)

    args = types.SimpleNamespace(config=None)  # 讓 CLI 提示會被呼叫

    # 記錄呼叫
    printed_hint = {"called": False}
    handled = []

    # ---- mock 相依 ----
    # OSWALK 回傳我們預設清單
    monkeypatch.setattr(mod, "OSWALK", lambda root: [a, b, c])
    # 攔截 handle_single_input_file，記錄輸入與 pause_seconds
    def fake_handle(file, ctx_in, adjust=True, pause_seconds=0, defer_merge=False):
        handled.append((file, pause_seconds, defer_merge))
    monkeypatch.setattr(mod, "handle_single_input_file", fake_handle)
    # CLI 使用提示
    monkeypatch.setattr(mod, "print_cli_usage_hint", lambda _ctx: printed_hint.__setitem__("called", True))
    # 結尾移除空目錄
    removed = {"dirs": []}
    monkeypatch.setattr(mod, "remove_empty_dirs", lambda d: removed["dirs"].append(d))

    # ---- 執行 ----
    mod.handle_txt_mode(ctx, args)

    # ---- 斷言 ----
    # 只處理 .txt，且順序保留
    assert [h[0] for h in handled] == [a, b]
    # 第一個 10 秒、第二個 0 秒
    assert [h[1] for h in handled] == [10, 0]
    # 有顯示 CLI 提示
    assert printed_hint["called"] is True
    # 有清空空目錄（呼叫一次）
    assert removed["dirs"] == [ctx.prompt_dir]
