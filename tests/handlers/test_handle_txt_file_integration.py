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

    # 1) 讓相對 logs 落在 tmp_path，並先建好
    monkeypatch.chdir(tmp_path)
    (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

    # 2) 暫時移除 client 的 proxies 參數（相容不同 SDK）
    try:
        import openai as _oai
        if hasattr(_oai, "OpenAI"):
            _Orig = _oai.OpenAI
            class _Patched(_Orig):
                def __init__(self, *args, **kwargs):
                    kwargs.pop("proxies", None)
                    super().__init__(*args, **kwargs)
            monkeypatch.setattr(_oai, "OpenAI", _Patched, raising=False)
    except Exception:
        pass

    # 3) 減少延遲與副作用
    monkeypatch.setattr(mod, "showTemplate", lambda task=None: None)
    monkeypatch.setattr(mod, "countdown_pause", lambda s: None)
    monkeypatch.setattr(mod, "DirReplace", lambda f, s, b: str(Path(b) / Path(f).name))
    monkeypatch.setattr(mod, "getPathFromFN", lambda p: str(Path(p).parent))
    monkeypatch.setattr(mod, "MKDIR", lambda d: None)
    monkeypatch.setattr(mod.shutil, "move", lambda s, d: None)

    # 4) 準備輸入與 ctx
    src = tmp_path / "sample.txt"
    src.write_text("This is a test", encoding="utf-8")

    ctx = LLMJobConfig()
    ctx.task = "Summary-toTWZH"
    ctx.model_spec = {"base_url": base_url, "model_name": model_name, "api_key": api_key}
    ctx.llm_source_dir = str(tmp_path)
    ctx.llm_source_backup_dir = str(tmp_path / "bak")
    ctx.prompt_dir = str(tmp_path / "prompts")
    ctx.main_file_name = src.stem
    ctx.PGMSubDir = str(tmp_path)  # ← 重要，給 logs 定位

    out_fn = mod.handle_single_input_file(str(src), ctx=ctx)

    # 5) 斷言
    assert out_fn, "應回傳輸出檔案路徑"
    out_path = Path(out_fn)
    assert out_path.is_file(), f"輸出檔案不存在：{out_path}"
    content = out_path.read_text(encoding="utf-8")
    assert any(k in content for k in ["測試", "test"])

