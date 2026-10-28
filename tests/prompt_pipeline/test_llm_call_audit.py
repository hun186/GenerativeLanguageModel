import ast
import csv
import importlib.util
from pathlib import Path
from types import SimpleNamespace


_AUDIT_PATH = (
    Path(__file__).parents[2] / "czjLLM" / "utilities" / "llm_call_audit.py"
)
_SPEC = importlib.util.spec_from_file_location("llm_call_audit_under_test", _AUDIT_PATH)
assert _SPEC and _SPEC.loader
_AUDIT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_AUDIT)
create_llm_call_audit_run = _AUDIT.create_llm_call_audit_run
log_llm_call = _AUDIT.log_llm_call
write_prompt_token_metadata = _AUDIT.write_prompt_token_metadata
read_prompt_token_metadata = _AUDIT.read_prompt_token_metadata


def test_every_prompt_worker_factory_receives_run_audit_metadata():
    controller_path = (
        Path(__file__).parents[2]
        / "czjLLM"
        / "prompt_pipeline"
        / "pipeline_controller.py"
    )
    tree = ast.parse(controller_path.read_text(encoding="utf-8"))
    context_factories = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name in {"llm_stream_consumer", "call_llm_api"}
    ]
    worker_calls = [
        node
        for factory in context_factories
        for node in ast.walk(factory)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "PromptAPIPipeline"
    ]

    assert len(worker_calls) == 2
    assert all(
        any(
            keyword.arg is None
            and isinstance(keyword.value, ast.Call)
            and isinstance(keyword.value.func, ast.Name)
            and keyword.value.func.id == "_llm_call_audit_kwargs"
            for keyword in call.keywords
        )
        for call in worker_calls
    )


def test_json_repair_failure_preserves_fixed_audit_marker_contract():
    source_path = (
        Path(__file__).parents[2] / "czjLLM" /
        "prompt_pipeline" / "pipeline_controller.py"
    )
    text = source_path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    controller = next(n for n in tree.body
                      if isinstance(n, ast.ClassDef) and n.name == "PromptAPIPipeline")
    proc = next(n for n in controller.body
                if isinstance(n, ast.FunctionDef) and n.name == "proc")
    handler = next(n for n in controller.body
                   if isinstance(n, ast.FunctionDef) and n.name == "handle_json_output")
    proc_text = ast.get_source_segment(text, proc)
    handler_text = ast.get_source_segment(text, handler)
    assert 'self._llm_json_failure_code = ""' in proc_text
    assert 'self._llm_json_failure_code = "JSON_POSTPROCESSING_FAILED"' in handler_text
    assert 'err = (self._llm_json_failure_code if not ok else "")' in proc_text
    assert "error=err" in proc_text


def test_audit_run_appends_a_call_row(tmp_path):
    metadata = create_llm_call_audit_run(str(tmp_path))
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=5, total_tokens=17),
        _czjllm_elapsed_seconds=1.25,
    )

    log_llm_call(
        audit_path=metadata["llm_call_audit_path"],
        run_id=metadata["llm_call_audit_run_id"],
        task="extract",
        prompt_file="prompt.txt",
        model_spec={"model_name": "test-model", "num_ctx": 1024},
        response=response,
        max_tokens=100,
        task_text_tokens=7,
        template_tokens=4,
        rendered_prompt_tokens=11,
        prompt_component_token_source="local_tokenizer_no_special_tokens",
    )

    with Path(metadata["llm_call_audit_path"]).open(encoding="utf-8", newline="") as fp:
        rows = list(csv.DictReader(fp))

    assert len(rows) == 1
    assert rows[0]["run_id"] == metadata["llm_call_audit_run_id"]
    assert rows[0]["total_tokens"] == "17"
    assert rows[0]["task_text_tokens"] == "7"
    assert rows[0]["template_tokens"] == "4"
    assert rows[0]["rendered_prompt_tokens"] == "11"
    assert rows[0]["prompt_component_token_source"] == "local_tokenizer_no_special_tokens"
    assert rows[0]["elapsed_seconds"] == "1.25"


def test_prompt_token_metadata_sidecar_contains_numbers_only(tmp_path):
    prompt = tmp_path / "TODO" / "0.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("secret source text", encoding="utf-8")

    write_prompt_token_metadata(
        str(prompt),
        task_text_tokens=123,
        template_tokens=45,
        rendered_prompt_tokens=168,
    )
    sidecar = prompt.parent.parent / ".llm_audit_tokens" / f"{prompt.name}.audit_tokens.json"
    raw = sidecar.read_text(encoding="utf-8")
    assert "secret source text" not in raw
    expected = {
        "task_text_tokens": 123,
        "template_tokens": 45,
        "rendered_prompt_tokens": 168,
        "prompt_component_token_source": "local_tokenizer_no_special_tokens",
    }
    assert read_prompt_token_metadata(str(prompt)) == expected
    # Queue claiming renames TODO/0.txt -> RUNNING/0.txt. The numeric sidecar
    # lives at the item root, so the worker still resolves the same metadata.
    running_prompt = prompt.parent.parent / "RUNNING" / prompt.name
    assert read_prompt_token_metadata(str(running_prompt)) == expected



def test_prompt_api_pipeline_emits_one_audit_row_per_request():
    controller_path = (
        Path(__file__).parents[2]
        / "czjLLM"
        / "prompt_pipeline"
        / "pipeline_controller.py"
    )
    tree = ast.parse(controller_path.read_text(encoding="utf-8"))
    pipeline_cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PromptAPIPipeline"
    )
    proc = next(
        node for node in pipeline_cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "proc"
    )
    audit_calls = [
        node for node in ast.walk(proc)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "log_llm_call"
    ]
    request_calls = [
        node for node in ast.walk(proc)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "CallLLMAPI"
    ]

    assert len(request_calls) == 1
    assert len(audit_calls) == 1
    source = ast.get_source_segment(
        controller_path.read_text(encoding="utf-8"), proc
    )
    assert "llm_request_attempted = True" in source
    assert "if llm_request_attempted:" in source
    assert "response=response" in source
    assert "ok=ok" in source
    assert "error=err" in source
    assert "worker_call_id=worker_call_id" in source
    assert "call_llm_api_returned=call_llm_api_returned" in source
    assert "call_llm_api_returned = False" in source
    assert "call_llm_api_returned = True" in source
    # Explicitly observed only after the call expression returns, before
    # response parsing/JSON repair/output persistence starts.
    assert source.index("response, cost = CallLLMAPI(") < source.index("call_llm_api_returned = True")
    assert source.index("call_llm_api_returned = True") < source.index("worker_failure_code = \"WORKER_RESPONSE_EXCEPTION\"")
    assert "worker_call_id = uuid.uuid4().hex" in source
    # The source boundary must set the identifier before actual CallLLMAPI
    # dispatch, not derive it from any prompt/response/error text.
    assert source.index("worker_call_id = uuid.uuid4().hex") < source.index("response, cost = CallLLMAPI(")
    assert source.index("response, cost = CallLLMAPI(") < source.index("worker_call_id=worker_call_id")


def test_provider_cached_usage_is_explicit_and_not_inferred(tmp_path):
    import csv
    from types import SimpleNamespace

    audit = tmp_path / "cache.csv"
    response = SimpleNamespace(
        usage=SimpleNamespace(
            prompt_tokens=120, completion_tokens=10, total_tokens=130,
            prompt_tokens_details=SimpleNamespace(cached_tokens=40),
        ), _czjllm_elapsed_seconds=2.5,
    )
    log_llm_call(audit_path=str(audit), run_id="run", prompt_file="p.txt",
                 model_spec={"model_name": "unit-model", "num_ctx": 1024},
                 response=response, stage_identity="stage-1")
    with audit.open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert rows[0]["cached_input_tokens"] == "40"
    assert rows[0]["cached_input_token_source"] == "provider_usage"
    assert rows[0]["stage_identity"] == "stage-1"

    no_cache_metadata = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=120, completion_tokens=10, total_tokens=130),
        _czjllm_elapsed_seconds=1.0,
    )
    log_llm_call(audit_path=str(audit), run_id="run", prompt_file="p2.txt",
                 model_spec={"model_name": "unit-model", "num_ctx": 1024},
                 response=no_cache_metadata)
    with audit.open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert rows[1]["cached_input_tokens"] == ""
    assert rows[1]["cached_input_token_source"] == ""
    assert rows[1]["stage_identity"] == ""


def test_deepseek_cache_hit_and_provider_explicit_zero(tmp_path):
    import csv
    from types import SimpleNamespace

    audit = tmp_path / "cache.csv"
    for cached in (75, 0):
        response = SimpleNamespace(
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20,
                                  total_tokens=120, prompt_cache_hit_tokens=cached),
            _czjllm_elapsed_seconds=2,
        )
        log_llm_call(audit_path=str(audit), run_id="run", prompt_file="p.txt",
                     model_spec={"model_name": "unit-model", "num_ctx": 1024},
                     response=response)
    with audit.open(newline="", encoding="utf-8") as fp:
        rows = list(csv.DictReader(fp))
    assert [row["cached_input_tokens"] for row in rows] == ["75", "0"]
    assert all(row["cached_input_token_source"] == "provider_usage" for row in rows)


def test_stage_identity_remains_metadata_not_prompt_payload(tmp_path):
    from pathlib import Path

    prompt = tmp_path / "TODO" / "a.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("secret task prompt", encoding="utf-8")
    write_prompt_token_metadata(
        str(prompt), task_text_tokens=20, template_tokens=10,
        rendered_prompt_tokens=30, stage_identity="classify",
    )
    sidecar = Path(str(prompt.parent.parent / ".llm_audit_tokens"
                       / "a.txt.audit_tokens.json"))
    raw = sidecar.read_text(encoding="utf-8")
    assert "secret task prompt" not in raw
    assert read_prompt_token_metadata(str(prompt))["stage_identity"] == "classify"
    running = prompt.parent.parent / "RUNNING" / "a.txt"
    assert read_prompt_token_metadata(str(running))["stage_identity"] == "classify"


def test_original_first_stage_relabel_preserves_token_counts_and_privacy(tmp_path):
    from pathlib import Path

    relabel = _AUDIT.relabel_prompt_token_stage
    prompt = tmp_path / "TODO" / "slice.txt"
    prompt.parent.mkdir(parents=True)
    prompt.write_text("private first-stage prompt", encoding="utf-8")
    write_prompt_token_metadata(
        str(prompt), task_text_tokens=72, template_tokens=30,
        rendered_prompt_tokens=102, stage_identity="single_stage",
    )
    assert relabel(str(prompt), "yaml_stage_alpha") is True
    expected = read_prompt_token_metadata(str(prompt))
    assert expected["stage_identity"] == "yaml_stage_alpha"
    assert expected["task_text_tokens"] == 72
    assert expected["template_tokens"] == 30
    assert expected["rendered_prompt_tokens"] == 102
    sidecar = Path(_AUDIT.prompt_token_metadata_path(str(prompt)))
    assert "private first-stage prompt" not in sidecar.read_text(encoding="utf-8")
    # Claiming TODO -> RUNNING keeps the same logical sidecar.
    running = prompt.parent.parent / "RUNNING" / "slice.txt"
    assert read_prompt_token_metadata(str(running))["stage_identity"] == "yaml_stage_alpha"

    missing = tmp_path / "TODO" / "missing.txt"
    missing.write_text("no component count", encoding="utf-8")
    assert relabel(str(missing), "yaml_stage_alpha") is False
    assert not _AUDIT.prompt_token_metadata_path(str(missing)).exists()

    # A legacy numeric sidecar without a tokenizer source must remain unknown.
    legacy = tmp_path / "TODO" / "legacy.txt"
    legacy.write_text("legacy", encoding="utf-8")
    legacy_sidecar = _AUDIT.prompt_token_metadata_path(str(legacy))
    legacy_sidecar.parent.mkdir(parents=True, exist_ok=True)
    legacy_sidecar.write_text(
        '{"task_text_tokens": 4, "template_tokens": 5, "rendered_prompt_tokens": 9}',
        encoding="utf-8",
    )
    assert relabel(str(legacy), "yaml_stage_alpha") is True
    assert read_prompt_token_metadata(str(legacy))["stage_identity"] == "yaml_stage_alpha"
    assert "prompt_component_token_source" not in read_prompt_token_metadata(str(legacy))


def test_multistage_original_prompt_retags_before_early_return():
    from pathlib import Path

    path = Path(__file__).parents[2] / "czjLLM" / "prompt_pipeline" / "pipeline_controller.py"
    source = path.read_text(encoding="utf-8")
    section = source.split('if (\n            stage_name == stage_defs[0].name', 1)[1]
    section = section.split('return  # 已有 TODO，不覆蓋', 1)[0]
    assert "shutil.copy2" in section
    assert "relabel_prompt_token_stage(str(fp), stage_name)" in section
    assert section.index("shutil.copy2") < section.index("relabel_prompt_token_stage")


def test_new_audit_records_have_distinct_opaque_row_ids_and_xlsx_column(tmp_path):
    """Same-second identical calls are separate records, not inferred retries."""
    import re
    import zipfile

    metadata = create_llm_call_audit_run(str(tmp_path))
    path = Path(metadata["llm_call_audit_path"])
    for _ in range(2):
        log_llm_call(
            audit_path=str(path), run_id=metadata["llm_call_audit_run_id"],
            task="same-task", model_spec={"model_name": "test", "num_ctx": 1024},
            ok=False, error="ReadTimeout: confidential input",
        )
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames[-3:] == [
            "audit_record_id", "worker_call_id", "call_llm_api_returned"]
    assert len(rows) == 2
    identifiers = [row["audit_record_id"] for row in rows]
    assert len(set(identifiers)) == 2
    assert all(re.fullmatch(r"[0-9a-f]{32}", value) for value in identifiers)
    assert all(row["ok"] == "NO" for row in rows)
    # XLSX is the real producer export, not a mocked summary.
    with zipfile.ZipFile(path.with_suffix(".xlsx")) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "audit_record_id" in sheet
    assert all(value in sheet for value in identifiers)
    # The read-only failure report still measures observed call rows, not IDs.
    from czjLLM.utilities.llm_failure_summary import summarize_llm_failure_audit
    result = summarize_llm_failure_audit(path)
    assert result["observed_call_attempts"] == 2
    assert result["failed_call_attempts"] == 2
    assert "audit_record_id" not in result


def test_append_to_preupgrade_audit_preserves_legacy_csv_width(tmp_path):
    """An in-flight old run is not silently upgraded mid-file."""
    legacy = tmp_path / "llm_call_audit_20261028-legacy.csv"
    with legacy.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=_AUDIT._FIELDS[:-1])
        writer.writeheader()
    original_header = legacy.read_bytes().splitlines()[0]
    log_llm_call(
        audit_path=str(legacy), run_id="old-run",
        model_spec={"model_name": "test", "num_ctx": 1024},
        ok=True,
    )
    assert legacy.read_bytes().splitlines()[0] == original_header
    with legacy.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        records = list(reader)
        assert reader.fieldnames == _AUDIT._FIELDS[:-1]
    assert len(records) == 1
    assert records[0]["ok"] == "YES"
    assert None not in records[0]
    from czjLLM.utilities.llm_failure_summary import summarize_llm_failure_audit
    assert summarize_llm_failure_audit(legacy)["successful_call_attempts"] == 1


def test_append_rejects_incompatible_existing_audit_header_without_misalignment(tmp_path):
    path = tmp_path / "llm_call_audit_20261028-wrong.csv"
    path.write_bytes(b"timestamp,ok,error\n")
    unchanged = path.read_bytes()
    import pytest
    with pytest.raises(ValueError, match="incompatible existing LLM audit CSV header"):
        log_llm_call(audit_path=str(path), run_id="old", model_spec={"num_ctx": 1024})
    assert path.read_bytes() == unchanged
    assert not path.with_suffix(".xlsx").exists()


def test_worker_call_id_is_explicit_and_distinct_from_audit_record_identity(tmp_path):
    """Only a Worker with a true dispatch identifier can supply provenance."""
    import re
    import zipfile
    path = tmp_path / "llm_call_audit_20261028-worker.csv"
    source_call = "0123456789abcdef0123456789abcdef"
    log_llm_call(audit_path=str(path), run_id="run-a", worker_call_id=source_call,
                 model_spec={"num_ctx": 1024}, ok=False, error="ReadTimeout SECRET")
    log_llm_call(audit_path=str(path), run_id="run-a",
                 model_spec={"num_ctx": 1024}, ok=False, error="ReadTimeout SECRET")
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    assert len(rows) == 2
    assert rows[0]["worker_call_id"] == source_call
    assert rows[1]["worker_call_id"] == ""  # No dispatch evidence: don't invent it.
    assert all(re.fullmatch(r"[0-9a-f]{32}", row["audit_record_id"]) for row in rows)
    assert rows[0]["audit_record_id"] != source_call
    assert rows[0]["audit_record_id"] != rows[1]["audit_record_id"]
    with zipfile.ZipFile(path.with_suffix(".xlsx")) as archive:
        sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "worker_call_id" in sheet and source_call in sheet
    from czjLLM.utilities.llm_failure_summary import summarize_llm_failure_audit
    report = summarize_llm_failure_audit(path)
    assert report["observed_call_attempts"] == 2
    assert report["failed_call_attempts"] == 2
    assert "worker_call_id" not in report and "audit_record_id" not in report


def test_worker_call_id_rejects_untrusted_values_without_csv_side_effect(tmp_path):
    import pytest
    path = tmp_path / "llm_call_audit_20261028-invalid-worker.csv"
    for invalid in ("secret/api_key", "f" * 31, "G" * 32,
                    "f" * 33, "f" * 32 + "\\nsecret", None, 123):
        with pytest.raises(ValueError, match="invalid worker call identifier"):
            log_llm_call(audit_path=str(path), run_id="run",
                         worker_call_id=invalid, model_spec={"num_ctx": 1024})
        assert not path.exists()
        assert not path.with_suffix(".xlsx").exists()


def test_two_supported_legacy_audit_headers_keep_exact_width(tmp_path):
    """Pre-#245, #245 and #246 headers cannot be silently upgraded."""
    from czjLLM.utilities.llm_failure_summary import summarize_llm_failure_audit
    for past_fields in (_AUDIT._FIELDS[:-3], _AUDIT._FIELDS[:-2], _AUDIT._FIELDS[:-1]):
        path = tmp_path / f"llm_call_audit_{len(past_fields)}-old.csv"
        with path.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=past_fields)
            writer.writeheader()
        original_header = path.read_bytes().splitlines()[0]
        log_llm_call(audit_path=str(path), run_id="run",
                     worker_call_id="a" * 32,
                     model_spec={"num_ctx": 1024}, ok=True)
        assert path.read_bytes().splitlines()[0] == original_header
        with path.open(newline="", encoding="utf-8") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
        assert reader.fieldnames == past_fields
        assert len(rows) == 1 and rows[0]["ok"] == "YES"
        assert None not in rows[0]
        assert summarize_llm_failure_audit(path)["successful_call_attempts"] == 1


def test_explicit_wrapper_return_and_local_failure_are_separate(tmp_path):
    """Caller source decides return; ok=NO may mean a LOCAL failure."""
    import zipfile
    from czjLLM.utilities.llm_failure_summary import summarize_llm_failure_audit

    path = tmp_path / "llm_call_audit_20261028-outcome.csv"
    scenarios = (
        ("a" * 32, True, False, "JSON_POSTPROCESSING_FAILED"),
        ("b" * 32, False, False, "Timeout while invoking CallLLMAPI"),
        ("c" * 32, True, True, ""),
        ("", None, False, "ReadTimeout unknown source"),
    )
    for worker_id, returned, ok, error in scenarios:
        log_llm_call(audit_path=str(path), run_id="run",
                     worker_call_id=worker_id, call_llm_api_returned=returned,
                     model_spec={"num_ctx": 1024}, ok=ok, error=error)

    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
        assert reader.fieldnames[-3:] == [
            "audit_record_id", "worker_call_id", "call_llm_api_returned"]
    assert [row["call_llm_api_returned"] for row in rows] == ["YES", "NO", "YES", ""]
    assert [row["ok"] for row in rows] == ["NO", "NO", "YES", "NO"]
    assert rows[0]["worker_call_id"] == "a" * 32
    assert rows[3]["worker_call_id"] == ""
    assert all(row["audit_record_id"] for row in rows)
    with zipfile.ZipFile(path.with_suffix(".xlsx")) as archive:
        xml = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
    assert "call_llm_api_returned" in xml
    assert "a" * 32 in xml
    report = summarize_llm_failure_audit(path)
    assert report["observed_call_attempts"] == 4
    assert report["failed_call_attempts"] == 3
    assert "call_llm_api_returned" not in report
    assert "worker_call_id" not in report


def test_return_outcome_requires_source_worker_id_and_bool_without_file_write(tmp_path):
    import pytest
    path = tmp_path / "llm_call_audit_20261028-invalid-outcome.csv"
    cases = (
        ("", True), ("", False),
        ("a" * 32, 0), ("a" * 32, 1), ("a" * 32, "YES"),
        ("a" * 32, []), ("a" * 32, "NO"),
    )
    for worker_call_id, returned in cases:
        with pytest.raises(ValueError, match="CallLLMAPI return"):
            log_llm_call(audit_path=str(path), run_id="run",
                         worker_call_id=worker_call_id,
                         call_llm_api_returned=returned,
                         model_spec={"num_ctx": 1024})
        assert not path.exists()
        assert not path.with_suffix(".xlsx").exists()


def test_legacy_worker_id_header_does_not_gain_return_field(tmp_path):
    """Existing #246 files remain byte-width compatible on append."""
    path = tmp_path / "llm_call_audit_20261028-previous.csv"
    fields = _AUDIT._FIELDS[:-1]
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
    original_header = path.read_bytes().splitlines()[0]
    log_llm_call(audit_path=str(path), run_id="run", worker_call_id="a" * 32,
                 call_llm_api_returned=False, model_spec={"num_ctx": 1024},
                 ok=False, error="ReadTimeout")
    assert path.read_bytes().splitlines()[0] == original_header
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        rows = list(reader)
    assert reader.fieldnames == fields
    assert len(rows) == 1 and rows[0]["worker_call_id"] == "a" * 32
    assert None not in rows[0]
