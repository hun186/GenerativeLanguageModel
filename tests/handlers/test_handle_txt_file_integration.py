# tests/test_handle_txt_file_integration.py
from pathlib import Path
import os
import pytest
import json, re
from czjLLM.handlers import handle_txt_file as mod
from czjLLM.job_manager.job_config import LLMJobConfig

def _digits(s: str | None) -> str:
    return re.sub(r"\D", "", s or "")


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
    sample_text = """
親愛的專案團隊成員：

您好！

本郵件旨在邀請您參加專案「鳳凰」的 2023 年第四季度進度更新會議。會議詳情如下：

日期： 2023 年 11 月 30 日（星期四）

時間： 下午 2:00 - 4:00

地點： 總公司 5 樓 第三會議室 (亦可透過 Teams 參加，連結將於會前提供)

會議目的：

檢視本季度里程碑達成狀況。

討論下一季度的資源分配與潛在風險。

確認最終產品發佈時程。

請各位預先審閱隨附的會議資料（附件：Q4_Project_Phoenix_Review.pdf），並於 11 月 27 日前回覆此郵件告知是否出席。

若有任何議題希望加入討論，也請不吝告知。

感謝您的配合！

祝順心

張大為 敬上
專案經理
創新科技部門
大同股份有限公司
電話：+886-2-8765-4321
電子郵件：david.chang@datung.com
    """
    src = tmp_path / "sample.txt"
    src.write_text(sample_text, encoding="utf-8")

    ctx = LLMJobConfig()
    #ctx.task = "Summary-toTWZH"
    ctx.task = "RAG Chunk and Contact Information to json format"    
    ctx.model_spec = {"base_url": base_url, "model_name": model_name, "api_key": api_key}
    ctx.llm_source_dir = str(tmp_path)
    ctx.llm_source_backup_dir = str(tmp_path / "bak")
    ctx.prompt_dir = str(tmp_path / "prompts")
    ctx.main_file_name = src.stem
    ctx.PGMSubDir = str(tmp_path)  # ← 重要，給 logs 定位
    #print("ctx in test_handle_txt_file_integration",ctx)
    out_fn = mod.handle_single_input_file(str(src), ctx=ctx)

    # 5) 斷言
    assert out_fn, "應回傳輸出檔案路徑"
    out_path = Path(out_fn)
    assert out_path.is_file(), f"輸出檔案不存在：{out_path}"
    content = out_path.read_text(encoding="utf-8")

    want_unit = "大同股份有限公司"
    want_phone_digits = _digits("+886-2-8765-4321")
    
    data = json.loads(content)  # 期望是 list 或 {"content": [...]}
    
    # 取出清單
    items = (
        data["content"] if isinstance(data, dict) and isinstance(data.get("content"), list)
        else data if isinstance(data, list)
        else []
    )
    
    ok = any(
        (isinstance(it, dict)
         and (it.get("type") == "Contact Information")
         and (it.get("unit") == want_unit or it.get("單位") == want_unit or it.get("公司") == want_unit)
         and (_digits(it.get("TEL") or it.get("電話") or it.get("phone")) == want_phone_digits))
        for it in items
    )
    
    assert ok, f"找不到目標聯絡資訊，輸出：{items!r}"
