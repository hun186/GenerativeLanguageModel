"""Provider length is explicit incomplete-output evidence even for valid JSON."""
import json
from types import SimpleNamespace

from czjLLM.prompt_pipeline.pipeline_controller import PromptAPIPipeline


def _worker_with_spy():
    worker = PromptAPIPipeline.__new__(PromptAPIPipeline)
    calls = []
    worker.extract_MainFileName_and_input_text = lambda: ("input", "source material", "hints")
    worker.split_and_generate_new_prompts = lambda **kw: calls.append(kw)
    worker._emit_json_quality = lambda *a, **kw: calls.append(("quality", a))
    return worker, calls


def test_provider_length_never_accepts_even_parseable_json():
    worker, calls = _worker_with_spy()
    ret, output = worker.handle_json_output('{"Event":[{"id":1}]}', finish_reason="length")
    assert ret == [] and output == ""
    assert worker._llm_json_failure_code == "JSON_OUTPUT_LIMIT_REACHED"
    assert len(calls) == 1 and calls[0]["input_text"] == "source material"


def test_provider_stop_keeps_existing_valid_json_behavior():
    worker, calls = _worker_with_spy()
    sample = '{"Event":[{"id":1}]}'
    ret, output = worker.handle_json_output(sample, finish_reason="stop")
    assert ret == [] and output == sample
    assert calls == [("quality", ("slice_json_validation", "JSON_VALID", "accepted"))]


def test_unknown_finish_reason_does_not_fabricate_truncation():
    worker, calls = _worker_with_spy()
    ret, result = worker.handle_json_output('{"a":1}', finish_reason="")
    assert ret == [] and result == '{"a":1}'
    assert len(calls) == 1


def test_explicit_length_without_extractable_input_is_not_success():
    worker, _calls = _worker_with_spy()
    worker.extract_MainFileName_and_input_text = lambda: ("input", "", "")
    assert worker.handle_json_output('{"a":1}', finish_reason="length") == ([], "")


def test_explicit_length_split_error_fails_closed(capsys):
    worker, _calls = _worker_with_spy()
    worker.split_and_generate_new_prompts = lambda **kw: (_ for _ in ()).throw(
        RuntimeError("sensitive-document")
    )
    assert worker.handle_json_output('{"a":1}', finish_reason="length") == ([], "")
    assert "sensitive-document" not in capsys.readouterr().out


def test_production_guards_both_worker_paths_and_repair_callers():
    from pathlib import Path
    source = Path("czjLLM/prompt_pipeline/pipeline_controller.py").read_text(encoding="utf-8")
    assert source.count("finish_reason=normalized_finish_reason(response)") == 1
    assert "finish_reason=finish_reason" in source
    assert source.count('self.task.strip().lower() == "json format repair"') == 2
    assert "JSON_OUTPUT_LIMIT_REACHED" in source


def test_final_no_retry_child_cannot_publish_length_and_does_not_split():
    worker, calls = _worker_with_spy()
    worker.allow_to_retry = False
    ret, result = worker.handle_json_output('{"Event":[]}', finish_reason="length")
    assert ret == [] and result == ""
    assert calls == []
