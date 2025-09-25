# tests/test_handle_txt_file_basic_unit.py
from pathlib import Path
import os
import pytest

from czjLLM.handlers import handle_txt_file as mod
from czjLLM.job_manager.job_config import LLMJobConfig

@pytest.mark.unit
def test_handle_single_input_file_unit(tmp_path, monkeypatch):
    # ── 1) 建立輸入檔 ─────────────────────────────────────
    sample_text = "This is a test"
    src = tmp_path / "sample.txt"
    src.write_text(sample_text, encoding="utf-8")

    # ── 2) 準備 ctx（不會連網） ──────────────────────────
    ctx = LLMJobConfig()
    ctx.task = "Summary-toTWZH"
    ctx.llm_source_dir = str(tmp_path)               # 當前來源目錄
    ctx.llm_source_backup_dir = str(tmp_path / "bak")# 備份目的
    ctx.prompt_dir = str(tmp_path / "prompts")       # 用不到，但避免屬性缺失
    ctx.main_file_name = src.stem

    # ── 3) 蒐集呼叫以便斷言 ─────────────────────────────
    calls = {"process_file_to_prompt": 0, "showTemplate": 0,
             "countdown_pause": [], "MKDIR": [], "move": []}

    # ── 4) 截掉會連網/耗時或寫檔副作用的點 ──────────────
    # 4a) 前置切片/樣板/倒數 → 改成 no-op 並記錄
    monkeypatch.setattr(mod, "process_file_to_prompt",
                        lambda f, c, adjust=True: calls.__setitem__("process_file_to_prompt", calls["process_file_to_prompt"]+1))
    monkeypatch.setattr(mod, "showTemplate",
                        lambda task=None: calls.__setitem__("showTemplate", calls["showTemplate"]+1))
    monkeypatch.setattr(mod, "countdown_pause",
                        lambda secs: calls["countdown_pause"].append(secs))

    # 4b) 產生搬移目的路徑 / 建目錄 / 搬檔 → 改成可觀察但不動檔案
    monkeypatch.setattr(mod, "DirReplace",
                        lambda f, src_dir, bak_dir: str(Path(bak_dir) / Path(f).name))
    monkeypatch.setattr(mod, "getPathFromFN",
                        lambda p: str(Path(p).parent))
    monkeypatch.setattr(mod, "MKDIR",
                        lambda d: calls["MKDIR"].append(d))
    monkeypatch.setattr(mod.shutil, "move",
                        lambda s, d: calls["move"].append((s, d)))

    # 4c) 用「假 run_merge」取代真正的 LLM 合併流程（完全不連網）
    def fake_run_merge(c, f):
        out = tmp_path / "sample.out.txt"
        out.write_text("這是一個測試：成功讀到內容：This is a test", encoding="utf-8")
        return str(out)

    # ── 5) 執行被測函式（注意：你的 handler 需採用 run_merge 參數） ─
    out_fn = mod.handle_single_input_file(
        str(src), ctx=ctx, adjust=True, pause_seconds=3, defer_merge=False, run_merge=fake_run_merge
    )

    # ── 6) 斷言輸出與流程 ────────────────────────────────
    out_path = Path(out_fn)
    assert out_path.is_file(), "輸出檔案不存在。"
    content = out_path.read_text(encoding="utf-8")
    assert "測試" in content, "輸出內容未包含『測試』。"
    assert calls["process_file_to_prompt"] == 1, "切片流程應被呼叫一次。"
    assert calls["showTemplate"] == 1, "第一次應顯示樣板。"
    assert calls["countdown_pause"] == [3], "應按照參數倒數 3 秒（已被 no-op）。"
    # DirReplace 會把目的路徑指到 bak/ 檔名；MKDIR 應被呼叫一次
    assert len(calls["MKDIR"]) == 1
    # 有呼叫搬移（但實際不搬），目的路徑應落在 bak 目錄
    assert len(calls["move"]) == 1
    assert calls["move"][0][0].endswith("sample.txt")
    assert Path(calls["move"][0][1]).parent.name == "bak"
