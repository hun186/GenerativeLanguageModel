"""Privacy-preserving exact group comparison, fed by the verified Audit scanner."""
import hashlib
import hmac
import os

from czjLLM.job_manager.audit_distribution import (
    AuditAccumulator, project_public_audit, _audit_token_count,
)

MAX_COMPARISON_GROUPS = 32
MAX_ID_CHARS = 4096
_CONTEXT_SOURCES = frozenset({"response", "ollama_api_ps", "model_spec"})


class AuditComparison:
    """One partition per exact model/endpoint/context/source tuple.

    Missing identifiers are counted separately; a full group budget never
    silently merges different groups. Aliases are ephemeral per scan generation.
    """
    def __init__(self, *, max_rows, max_groups=MAX_COMPARISON_GROUPS):
        self.max_rows = max_rows
        self.max_groups = max_groups
        self.salt = os.urandom(32)
        self.groups = {}
        self.unidentified = self.omitted = self.total = 0

    def _alias(self, domain, value):
        return hmac.new(self.salt, domain.encode() + b"\0" + value.encode("utf-8"),
                        hashlib.sha256).hexdigest()[:24]

    def consume(self, row):
        self.total += 1
        model, endpoint = row.get("model"), row.get("base_url")
        if (not isinstance(model, str) or not isinstance(endpoint, str)
                or not model.strip() or not endpoint.strip()
                or len(model) > MAX_ID_CHARS or len(endpoint) > MAX_ID_CHARS):
            self.unidentified += 1
            return
        model_alias = self._alias("model", model)
        endpoint_alias = self._alias("endpoint", endpoint)
        context = _audit_token_count(row.get("context_limit_tokens"))
        source = row.get("context_limit_source")
        if not context or source not in _CONTEXT_SOURCES:
            context, source = None, "unknown"
        key = (model_alias, endpoint_alias, context, source)
        if key not in self.groups:
            if len(self.groups) >= self.max_groups:
                self.omitted += 1
                return
            self.groups[key] = AuditAccumulator(max_rows=self.max_rows)
        self.groups[key].consume((row,), strict=True)

    def snapshot(self):
        rows = []
        for key, acc in self.groups.items():
            model, endpoint, context, source = key
            stats = project_public_audit(acc.snapshot())
            rows.append({
                "model_alias": model, "endpoint_alias": endpoint,
                "context_limit_tokens": context, "context_limit_source": source,
                "calls": stats["calls"], "failures": stats["failures"],
                "failure_pct": 100 * stats["failures"] / stats["calls"],
                "slice_time": stats["metrics"]["elapsed_seconds"],
                "total_tok_per_s": stats["metrics"]["total_tok_per_s"],
                "effective_tok_per_s_est": stats["metrics"]["effective_tok_per_s_est"],
                "effective_provider_rows": stats["effective_provider_rows"],
                "effective_heuristic_rows": stats["effective_heuristic_rows"],
                "ttft": stats["stream_timing"]["metrics"]["stream_ttft_seconds"],
                "first_content": stats["stream_timing"]["metrics"]["stream_first_content_seconds"],
                "provider_cache": stats["provider_cache"],
            })
        rows.sort(key=lambda x: (-x["calls"], x["model_alias"], x["endpoint_alias"],
                                 x["context_limit_tokens"] or 0, x["context_limit_source"]))
        return {"scope": "current_audit_observed_groups",
                "status": "limited" if self.omitted else "observed",
                "total_rows": self.total, "unidentified_rows": self.unidentified,
                "omitted_rows": self.omitted,
                "grouped_rows": sum(x["calls"] for x in rows),
                "groups": rows, "group_limit": self.max_groups,
                "aliases": "ephemeral_per_scan_generation"}
