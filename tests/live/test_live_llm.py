import pytest


@pytest.mark.live_llm
def test_live_llm_protocol_smoke(live_llm_config, tmp_path):
    from czjLLM.prompt_pipeline.pipeline_controller import PromptAPIPipeline

    output = tmp_path / "live-llm.txt"
    result = PromptAPIPipeline(
        task="live protocol smoke",
        content="Return exactly: CZJLLM_LIVE_OK",
        OutputSaveFN=str(output),
        max_tokens=32,
        model_spec=live_llm_config,
        PGMSubDir=str(tmp_path),
    ).proc()
    assert result["ok"]
    assert str(result["output"]).strip()
    assert output.is_file()
