# tests/test_handle_txt_file_integration.py
from pathlib import Path
import os
import pytest

from czjLLM.handlers import handle_txt_file as mod
from czjLLM.job_manager.job_config import LLMJobConfig

@pytest.mark.integration
def test_handle_single_input_file_integration(tmp_path, monkeypatch):
    base_url = os.getenv("LLM_BASE_URL")
    model_name = os.getenv("LLM_MODEL_NAME")
    api_key = os.getenv("LLM_API_KEY")
    if not (base_url and model_name and api_key):
        pytest.skip("未設定 LLM_* 環境變數，略過整合測試。")

    # 避免拖慢測試
    monkeypatch.setattr(mod, "showTemplate", lambda task=None: None)
    monkeypatch.setattr(mod, "countdown_pause", lambda s: None)

    src = tmp_path / "sample.txt"
    src.write_text("This is a test", encoding="utf-8")

    ctx = LLMJobConfig()
    ctx.task = "Summary-toTWZH"
    ctx.model_spec = {"base_url": base_url, "model_name": model_name, "api_key": api_key}
    ctx.llm_source_dir = str(tmp_path)
    ctx.llm_source_backup_dir = str(tmp_path / "bak")
    ctx.prompt_dir = str(tmp_path / "prompts")
    ctx.main_file_name = src.stem

    # （可）攔 DirReplace/MKDIR/move，避免亂移檔案
    monkeypatch.setattr(mod, "DirReplace", lambda f, s, b: str(Path(b) / Path(f).name))
    monkeypatch.setattr(mod, "getPathFromFN", lambda p: str(Path(p).parent))
    monkeypatch.setattr(mod, "MKDIR", lambda d: None)
    monkeypatch.setattr(mod.shutil, "move", lambda s, d: None)

    out_fn = mod.handle_single_input_file(str(src), ctx=ctx)
    assert Path(out_fn).is_file()
    content = Path(out_fn).read_text(encoding="utf-8")
    assert any(k in content for k in ["測試", "test"]), "模型回覆內容不如預期。"
