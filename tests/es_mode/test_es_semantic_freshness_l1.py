from czjLLM.es_mode.adapters.pending_policy import ElasticsearchPendingPolicyMixin


class Policy(ElasticsearchPendingPolicyMixin):
    def __init__(self, rerun): self.cfg = {"output_col": "summary", "rerun": rerun}


def test_es_execution_fingerprint_is_cumulative():
    strict = Policy({"enable": True, "execution_fingerprint": "new"})
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {"execution_fingerprint": "new"}}, ["summary"]).pending is False
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {}}, ["summary"]).reason == "missing_processing_identity"
    assert strict.check_source_pending({"summary": "ok", "summary_meta": {"execution_fingerprint": "old"}}, ["summary"]).reason == "execution_fingerprint_mismatch"
    legacy = Policy({"enable": False})
    assert legacy.check_source_pending({"summary": "ok"}, ["summary"]).pending is False
