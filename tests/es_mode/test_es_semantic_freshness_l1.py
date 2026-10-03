from czjLLM.es_mode.adapters.pending_policy import ElasticsearchPendingPolicyMixin
from datetime import datetime, timedelta, timezone


class Policy(ElasticsearchPendingPolicyMixin):
    def __init__(self, rerun): self.cfg = {"output_col": "summary", "rerun": rerun}


def test_es_execution_fingerprint_is_cumulative():
    strict = Policy({"enable": True, "execution_fingerprint": "new"})
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {"execution_fingerprint": "new"}}, ["summary"]).pending is False
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {}}, ["summary"]).reason == "missing_processing_identity"
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {"execution_fingerprint": "old"}}, ["summary"]).reason == "execution_fingerprint_mismatch"
    legacy = Policy({"enable": False})
    assert legacy.check_source_pending({"summary": "ok"}, ["summary"]).pending is False


def test_es_semantic_metadata_missing_and_mismatch_reasons_match_query_policy():
    cases = [
        ({"model_tag": "m"}, {}, "missing_meta"),
        ({"model_tag": "m"}, {"model_tag": "old"}, "model_tag_mismatch"),
        ({"pipeline_hash": "p"}, {}, "missing_meta"),
        ({"pipeline_hash": "p"}, {"pipeline_hash": "old"}, "pipeline_hash_mismatch"),
    ]
    for configured, meta, reason in cases:
        policy = Policy({"enable": True, **configured})
        assert policy._needs_rerun_clause("idx", "summary") is not None
        assert policy.check_source_pending({"summary": "ok", "summary_meta": meta}, ["summary"]).reason == reason
        matching = dict(configured)
        assert policy.check_source_pending(
            {"summary": "ok", "summary_meta": matching}, ["summary"]
        ).reason == "fresh_completed"


def test_es_required_output_and_time_policy_specific_reasons():
    required = Policy({"enable": True, "required_output_checks": [{"path": "needed"}]})
    assert required.check_source_pending({"summary": {"other": "x"}}, ["summary"]).reason == "required_output_invalid"
    old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    stale = Policy({"enable": True, "stale_after_days": 2})
    assert stale.check_source_pending(
        {"summary": "ok", "summary_meta": {"processed_at": old}}, ["summary"]
    ).reason == "stale_after_days"
    forced = Policy({"enable": True, "force_since": datetime.now(timezone.utc).isoformat()})
    assert forced.check_source_pending(
        {"summary": "ok", "summary_meta": {"processed_at": old}}, ["summary"]
    ).reason == "force_since"
