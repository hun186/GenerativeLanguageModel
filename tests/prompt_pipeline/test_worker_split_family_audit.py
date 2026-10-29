"""Isolated-provider tests; real queued files, Worker proc and persisted CSV."""
import csv
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
import pytest
from czjLLM.prompt_pipeline import pipeline_controller as pc
from czjLLM.prompt_pipeline.slice_identity import (
    install_split_prompts, verified_queued_prompt_source, verified_split_family_id,
)
from czjLLM.utilities.llm_call_audit import log_llm_call
from czjLLM.utilities.llm_failure_summary import summarize_llm_failure_audit


def queued(tmp, text):
    path = tmp / "item" / "RUNNING" / "root.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def resp(text):
    return SimpleNamespace(usage=SimpleNamespace(completion_tokens=1),
                           choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def worker(monkeypatch, tmp, path, text, task="plain task"):
    w = pc.PromptAPIPipeline.__new__(pc.PromptAPIPipeline)
    w.task, w.content, w.promptFile = task, text, str(path)
    w.OutputSaveFN, w.removeFinPromptFile = "", False
    w.max_tokens, w.allow_to_retry, w.include_think = 1024, True, False
    w.debug_print_llm_io, w.debug_print_max_chars = False, 80
    w.audit_path, w.audit_run_id, w.audit_prompt_tokens = str(tmp / "llm_call_audit_family.csv"), "run", {}
    w.PGMSubDir = str(tmp)
    w.model_spec = {"base_url":["http://offline.invalid"],"model_name":"isolated-model","num_ctx":2048}
    monkeypatch.setattr(pc, "select_idle_ollama_url", lambda *_a,**_k:"http://offline.invalid")
    monkeypatch.setattr(pc, "release_url_load", lambda *_a,**_k:None)
    return w


def rows(file):
    with open(file, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def test_first_parent_created_after_call_and_child_share_family(monkeypatch,tmp_path):
    parent = queued(tmp_path, "private original prompt")
    w = worker(monkeypatch,tmp_path,parent,"private original prompt","to json")
    monkeypatch.setattr(pc,"CallLLMAPI",lambda *_a,**_k:(resp("invalid json"),0))
    def repair(_):
        install_split_prompts(str(parent),w.content,[("root-0.txt","left"),("root-1.txt","right")])
        parent.unlink()
        return [("retry","")], ""
    monkeypatch.setattr(w,"handle_json_output",repair)
    assert w.proc()["ok"] is False
    journal = parent.parent.parent / "_extract_slice_identity" / "splits" / "root.txt.json"
    family=json.loads(journal.read_text())["split_family_id"]
    a=rows(w.audit_path)
    assert len(a)==1 and a[0]["split_family_id"]==family
    assert a[0]["ok"]=="NO" and a[0]["call_llm_api_returned"]=="YES"
    child=parent.parent.parent / "TODO" / "root-0.txt"
    monkeypatch.setattr(pc,"CallLLMAPI",lambda *_a,**_k:(resp("done"),0))
    assert worker(monkeypatch,tmp_path,child,"left").proc()["ok"]
    a=rows(w.audit_path)
    assert len(a)==2 and a[1]["split_family_id"]==family
    assert a[0]["worker_call_id"]!=a[1]["worker_call_id"]
    assert a[0]["audit_record_id"]!=a[1]["audit_record_id"]
    with zipfile.ZipFile(Path(w.audit_path).with_suffix(".xlsx")) as archive:
        xml=archive.read("xl/worksheets/sheet1.xml").decode()
    assert "split_family_id" in xml and family in xml and "private original prompt" not in xml
    report=summarize_llm_failure_audit(Path(w.audit_path))
    assert report["observed_call_attempts"]==2 and report["failed_call_attempts"]==1
    assert "split_family_id" not in report


def test_mismatch_unknown_but_source_verified_child_and_nested_valid(monkeypatch,tmp_path):
    root=queued(tmp_path,"root")
    install_split_prompts(str(root),"root",[("root-0.txt","child"),("root-1.txt","sibling")])
    monkeypatch.setattr(pc,"CallLLMAPI",lambda *_a,**_k:(resp("ok"),0))
    w=worker(monkeypatch,tmp_path,root,"not the on-disk prompt")
    w.proc()
    assert rows(w.audit_path)[0]["split_family_id"]==""
    child=root.parent.parent / "TODO" / "root-0.txt"
    install_split_prompts(str(child),"child",[("root-0-0.txt","leaf"),("root-0-1.txt","other")])
    leaf=child.parent / "root-0-0.txt"
    worker(monkeypatch,tmp_path,leaf,"leaf").proc()
    journal=root.parent.parent / "_extract_slice_identity" / "splits" / "root.txt.json"
    family=json.loads(journal.read_text())["split_family_id"]
    assert rows(w.audit_path)[1]["split_family_id"]==family
    # Missing UUID in a direct ancestor is not evidence for its descendant.
    nested=child.parent.parent / "_extract_slice_identity" / "splits" / "root-0.txt.json"
    obj=json.loads(nested.read_text())
    obj.pop("split_family_id")
    nested.write_text(json.dumps(obj))
    worker(monkeypatch,tmp_path,leaf,"leaf").proc()
    assert rows(w.audit_path)[2]["split_family_id"]==""


def test_real_queue_stream_hash_newlines_and_symlink_rejection(tmp_path):
    path=queued(tmp_path,"x"*65535+"\r\ny\r\nz")
    assert verified_queued_prompt_source(str(path),"x"*65535+"\ny\nz")
    assert not verified_queued_prompt_source(str(path),"short")
    assert not verified_queued_prompt_source(str(path.parent/"missing.txt"),"x")
    alias=path.parent/"alias.txt"
    try: alias.symlink_to(path)
    except (OSError,NotImplementedError): pytest.skip("no symlinks")
    assert not verified_queued_prompt_source(str(alias),"x"*65535+"\ny\nz")


def test_strict_uuid_and_worker_proof_before_writing_csv(tmp_path):
    path=tmp_path/"llm_call_audit_new.csv"
    for invalid in ("0"*32,"A"*32,"f"*31,None,12,"secret"):
        with pytest.raises(ValueError,match="split family"):
            log_llm_call(audit_path=str(path),run_id="x",worker_call_id="a"*32,
                         call_llm_api_returned=False,split_family_id=invalid,
                         model_spec={"num_ctx":2048})
        assert not path.exists()
    for args in ({"worker_call_id":""},{"worker_call_id":"a"*32,"call_llm_api_returned":None}):
        with pytest.raises(ValueError,match="split family"):
            log_llm_call(audit_path=str(path),run_id="x",split_family_id=uuid4().hex,
                         model_spec={"num_ctx":2048},**args)
        assert not path.exists()


def test_four_legacy_header_widths_and_report_denominator_unchanged(tmp_path):
    from czjLLM.utilities import llm_call_audit as mod
    for n in range(1,5):
        fields=mod._FIELDS[:-n]
        path=tmp_path / f"llm_call_audit_old_{n}.csv"
        with path.open("w",newline="",encoding="utf-8") as h:
            csv.DictWriter(h,fieldnames=fields).writeheader()
        before=path.read_bytes().splitlines()[0]
        log_llm_call(audit_path=str(path),run_id="x",worker_call_id="a"*32,
                     call_llm_api_returned=True,split_family_id=uuid4().hex,
                     model_spec={"num_ctx":2048})
        assert path.read_bytes().splitlines()[0]==before
        with path.open(newline="",encoding="utf-8") as h:
            reader=csv.DictReader(h)
            values=list(reader)
        assert reader.fieldnames==fields and len(values)==1
        assert None not in values[0] and "split_family_id" not in fields
        assert summarize_llm_failure_audit(path)["observed_call_attempts"]==1



def test_large_prompt_hash_is_bounded_and_crlf_split_across_chunks(tmp_path):
    import tracemalloc
    prompt = ("x" * 65535 + "\r\n" + "中文" + "\r" + "z") * 32
    path = queued(tmp_path, prompt)
    normalized = prompt.replace("\r\n", "\n").replace("\r", "\n")
    tracemalloc.start()
    try:
        assert verified_queued_prompt_source(str(path), prompt)
        assert verified_queued_prompt_source(str(path), normalized)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    # Payload is >2 MiB; neither side of source proof may make full copies.
    assert peak < 1_000_000


def test_ancestor_directory_symlink_is_unknown_for_both_source_and_journal(tmp_path):
    real = tmp_path / "real"
    parent = queued(real, "root source")
    install_split_prompts(
        str(parent), "root source",
        [("root-0.txt", "left"), ("root-1.txt", "right")],
    )
    assert verified_split_family_id(str(parent), "root source")
    alias = tmp_path / "alias"
    try:
        alias.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("directory symlinks unavailable")
    aliased_parent = alias / "item" / "RUNNING" / "root.txt"
    assert not verified_queued_prompt_source(str(aliased_parent), "root source")
    assert verified_split_family_id(str(aliased_parent), "root source") == ""
