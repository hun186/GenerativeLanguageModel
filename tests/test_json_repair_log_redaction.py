"""JSON combiner console logs must not expose input fragments or exception bodies.

These are deterministic failure-path regressions; no provider/DB call is made.
The compatibility return values deliberately remain the existing behavior.
"""
import json

from czjLLM.utilities import json_combining


def test_repair_failure_does_not_log_original_llm_text_or_exception(monkeypatch, capsys):
    source_marker = "PRIVATE_SOURCE_NEVER_PRINT"
    failure_marker = "PRIVATE_EXCEPTION_NEVER_PRINT"
    malformed = '[{"source":"' + source_marker + '","score": }]'

    def broken_repair(_text, **_kwargs):
        raise RuntimeError(failure_marker)

    monkeypatch.setattr(json_combining, "repair_json", broken_repair)
    result = json_combining.robust_merge_json_lists(malformed)
    logs = capsys.readouterr().out

    assert json.loads(result) == []  # Legacy skip-on-repair-failure semantics.
    assert "[JSON-COMBINE] decode_failed; attempting_local_repair" in logs
    assert "[JSON-COMBINE] repair_failed_segment_skipped" in logs
    assert source_marker not in logs and failure_marker not in logs
    assert "source" not in logs


def test_repair_failure_preserves_preceding_valid_array_without_logging_data(
    monkeypatch, capsys,
):
    source = "PRIVATE_SECOND_SEGMENT_NEVER_PRINT"
    first = json.dumps([{"id": 1}])
    malformed = '[{"private":"' + source + '","score": }]'
    monkeypatch.setattr(
        json_combining, "repair_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("PRIVATE_EXCEPTION_NEVER_PRINT")
        ),
    )

    result = json.loads(json_combining.robust_merge_json_lists(first + "\n" + malformed))
    logs = capsys.readouterr().out

    assert result == [{"id": 1}]
    assert source not in logs and "PRIVATE_EXCEPTION_NEVER_PRINT" not in logs


def test_legacy_combiner_exception_does_not_print_payload_or_error(
    monkeypatch, capsys,
):
    internal = '[{"private":"PRIVATE_COMBINED_NEVER_PRINT","score": }]'
    monkeypatch.setattr(json_combining, "robust_merge_json_lists", lambda _raw: internal)

    def broken_repair(_text, **_kwargs):
        raise RuntimeError("PRIVATE_REPAIR_ERROR_NEVER_PRINT")

    monkeypatch.setattr(json_combining, "repair_json", broken_repair)
    result, error = json_combining.combine_json_return("ordinary")
    logs = capsys.readouterr().out

    assert result == internal
    assert error  # Legacy error return remains unchanged.
    assert "[JSON-COMBINE] combined_decode_failed; attempting_local_repair" in logs
    assert "[JSON-COMBINE] combined_postprocess_failed" in logs
    assert "PRIVATE_COMBINED_NEVER_PRINT" not in logs
    assert "PRIVATE_REPAIR_ERROR_NEVER_PRINT" not in logs


def test_invalid_repaired_shape_does_not_print_repaired_object(monkeypatch, capsys):
    internal = '[{"private":"PRIVATE_COMBINED_NEVER_PRINT","score": }]'
    monkeypatch.setattr(json_combining, "robust_merge_json_lists", lambda _raw: internal)

    def repair(_text, *, return_objects=False):
        if return_objects:
            return ["PRIVATE_REPAIRED_OBJECT_NEVER_PRINT"]
        return "[]"

    monkeypatch.setattr(json_combining, "repair_json", repair)
    result, error = json_combining.combine_json_return("ordinary", NoNestedList=False)
    logs = capsys.readouterr().out

    assert result == internal and error
    assert "[JSON-COMBINE] repaired_item_shape_invalid" in logs
    assert "[JSON-COMBINE] combined_postprocess_failed" in logs
    assert "PRIVATE_REPAIRED_OBJECT_NEVER_PRINT" not in logs
    assert "PRIVATE_COMBINED_NEVER_PRINT" not in logs


def test_successful_repair_reports_fixed_code_without_printing_original(monkeypatch, capsys):
    source = "PRIVATE_REPAIRED_INPUT_NEVER_PRINT"
    malformed = '[{"private":"' + source + '",}]'
    repaired = json.dumps([{"private": source}])
    monkeypatch.setattr(json_combining, "repair_json", lambda _text: repaired)

    result = json.loads(json_combining.robust_merge_json_lists(malformed))
    logs = capsys.readouterr().out

    assert result == [{"private": source}]
    assert "[JSON-COMBINE] repaired_segment_accepted" in logs
    assert source not in logs
