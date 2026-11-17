"""Opt-in HTTPS GET-only random sample of indexed MultiDim article blocks.

Uses only _search count/sample requests; no write, export, scroll/PIT or LLM.
The retrieved _source is transient memory only, never printed or saved.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import json
import ssl
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPSHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from czjLLM.common.multidim_index_sample_audit import (  # noqa: E402
    INDEX, MAX_SAMPLE, summarize_structured_sample,
)
from scripts.audit_multidim_es_mapping_readonly import (  # noqa: E402
    _NoRedirect, _endpoint, _require_ip_literal_for_san_exception,
)

MAX_RESPONSE_BYTES = 12 * 1024 * 1024
RANDOM_SEED = 20261116
NESTED_CANDIDATES = {
    "nested": {
        "path": "multidim_event_json",
        "query": {"match_all": {}},
        "score_mode": "none",
    },
}


def _count(response: dict) -> int:
    try:
        total = response["hits"]["total"]
        if total["relation"] != "eq" or type(total["value"]) is not int or total["value"] < 0:
            raise ValueError("COUNT_NOT_EXACT")
        return total["value"]
    except (TypeError, ValueError, KeyError):
        raise ValueError("COUNT_NOT_EXACT") from None


def _get_search(origin: str, opener, query: dict) -> dict:
    params = urlencode({
        "source": json.dumps(query, separators=(",", ":"), ensure_ascii=True),
        "source_content_type": "application/json",
    })
    path = "/" + INDEX + "/_search?" + params
    if len(path) > 3072:
        raise ValueError("SEARCH_URI_TOO_LONG")
    req = Request(origin + path, headers={"Accept": "application/json"},
                  method="GET")
    try:
        with opener.open(req, timeout=20) as response:
            if response.getcode() != 200:
                raise ValueError("HTTP_NON_200")
            data = response.read(MAX_RESPONSE_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError("HTTP_AUTH_OR_PERMISSION_FAILED") from None
        if 300 <= exc.code <= 399:
            raise ValueError("HTTP_REDIRECT_REJECTED") from None
        if exc.code == 400:
            raise ValueError("ES_SEARCH_REJECTED") from None
        raise ValueError("HTTP_SEARCH_FAILED") from None
    except (OSError, URLError, TimeoutError, ssl.SSLError):
        raise ValueError("CONNECTION_OR_TLS_UNAVAILABLE") from None
    if len(data) > MAX_RESPONSE_BYTES:
        raise ValueError("SEARCH_RESPONSE_TOO_LARGE")
    try:
        result = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("SEARCH_RESPONSE_INVALID") from None
    if not isinstance(result, dict):
        raise ValueError("SEARCH_RESPONSE_INVALID")
    # HTTP 200 and hits.total.relation=eq can coexist with failed shards or
    # timeouts. Never report shard-biased / partial counts as a valid sample.
    shards = result.get("_shards")
    if result.get("timed_out") is not False or not isinstance(shards, dict):
        raise ValueError("SEARCH_PARTIAL_OR_UNVERIFIED")
    total = shards.get("total")
    successful = shards.get("successful")
    failed = shards.get("failed")
    skipped = shards.get("skipped", 0)
    if (any(type(v) is not int or v < 0
            for v in (total, successful, failed, skipped))
            or total == 0 or failed != 0
            or successful + skipped < total
            or result.get("terminated_early") is True):
        raise ValueError("SEARCH_PARTIAL_OR_UNVERIFIED")
    return result


def _fetch_sample(origin: str, cafile: str, user: str, password: str,
                  *, sample_size: int, skip_hostname: bool) -> dict:
    if skip_hostname:
        _require_ip_literal_for_san_exception(origin)
    ca = Path(cafile)
    if not ca.is_file():
        raise ValueError("CA_CERT_FILE_NOT_FOUND")
    try:
        ctx = ssl.create_default_context(cafile=str(ca))
    except (OSError, ssl.SSLError):
        raise ValueError("CA_CERT_INVALID_OR_UNREADABLE") from None
    if skip_hostname:
        ctx.check_hostname = False
    if ctx.verify_mode != ssl.CERT_REQUIRED:
        raise ValueError("CA_VERIFICATION_UNAVAILABLE")
    auth = base64.b64encode((user + ":" + password).encode("utf-8")).decode("ascii")
    from urllib.request import HTTPBasicAuthHandler, HTTPPasswordMgrWithDefaultRealm
    # Keep Basic credentials attached only to the exact HTTPS origin.
    # A redirect is refused by _NoRedirect, and the URL has no path from input.
    manager = HTTPPasswordMgrWithDefaultRealm()
    manager.add_password(None, origin + "/" + INDEX + "/", user, password)
    basic = HTTPBasicAuthHandler(manager)
    opener = build_opener(HTTPSHandler(context=ctx), _NoRedirect(), basic)
    # Preemptive Authorization applies to the expected ES protected endpoint;
    # never include secrets in a response object, error or report.
    class _AuthenticatedOpener:
        def open(self, req, timeout):
            req.add_unredirected_header("Authorization", "Basic " + auth)
            return opener.open(req, timeout=timeout)
    bound = _AuthenticatedOpener()
    total_query = {"size": 0, "track_total_hits": True, "query": {"match_all": {}}}
    candidate_query = {"size": 0, "track_total_hits": True, "query": NESTED_CANDIDATES}
    total = _count(_get_search(origin, bound, total_query))
    candidate_count = _count(_get_search(origin, bound, candidate_query))
    if candidate_count > total:
        raise ValueError("INDEX_COUNTS_CHANGED")
    if candidate_count == 0:
        result = summarize_structured_sample(total, 0, [])
        result["status"] = "OBSERVED_NO_NESTED_CANDIDATES"
        return result
    take = min(candidate_count, sample_size)
    sample_query = {
        "size": take,
        "track_total_hits": True,
        "_source": ["multidim_event_json"],
        "query": {
            "function_score": {
                "query": NESTED_CANDIDATES,
                "random_score": {"seed": RANDOM_SEED, "field": "_seq_no"},
                "boost_mode": "replace",
            }
        },
    }
    sampled = _get_search(origin, bound, sample_query)
    if _count(sampled) != candidate_count:
        raise ValueError("INDEX_COUNTS_CHANGED")
    try:
        hits = sampled["hits"]["hits"]
    except (TypeError, KeyError):
        raise ValueError("SEARCH_RESPONSE_INVALID") from None
    if not isinstance(hits, list) or len(hits) != take:
        raise ValueError("SEARCH_RESPONSE_INVALID")
    report = summarize_structured_sample(total, candidate_count, hits)
    report["sample_seed"] = RANDOM_SEED
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true",
                        help="Operator opt-in to HTTPS GET-only ES reads")
    parser.add_argument("--url", help="ES HTTPS origin without credentials or path")
    parser.add_argument("--ca-cert", help="CA certificate bundle")
    parser.add_argument("--sample-size", type=int, default=150,
                        help="Nested-candidate sample, between 1 and 300")
    parser.add_argument("--allow-ip-san-mismatch", action="store_true",
                        help="Diagnostic only: CA-verified TLS, hostname check skipped")
    args = parser.parse_args(argv)
    minimal = {"index": INDEX, "read_only": True, "no_writeback_or_replay": True,
               "raw_documents_exported": False}
    if not args.run:
        print(json.dumps({**minimal, "status": "NOT_TESTED",
                          "reason_code": "OPERATOR_NOT_OPTED_IN"}, sort_keys=True))
        return 2
    try:
        if not 1 <= args.sample_size <= MAX_SAMPLE:
            raise ValueError("SAMPLE_SIZE_INVALID")
        if not args.url or not args.ca_cert:
            raise ValueError("URL_AND_CA_REQUIRED")
        origin = _endpoint(args.url)
        if args.allow_ip_san_mismatch:
            _require_ip_literal_for_san_exception(origin)
        username = input("ES user (not shown in report): ").strip()
        password = getpass.getpass("ES password (hidden): ")
        if not username or not password:
            raise ValueError("CREDENTIALS_REQUIRED")
        report = _fetch_sample(origin, args.ca_cert, username, password,
                               sample_size=args.sample_size,
                               skip_hostname=args.allow_ip_san_mismatch)
        report["tls_ca_chain_verification"] = "REQUIRED"
        report["tls_ip_san_verification"] = (
            "TEMPORARILY_SKIPPED" if args.allow_ip_san_mismatch else "REQUIRED"
        )
        if args.allow_ip_san_mismatch:
            report["status"] = ("OBSERVED_WITH_TLS_EXCEPTION" if report["status"]
                                == "OBSERVED_SAMPLE_NOT_PROVEN" else report["status"])
    except (ValueError, EOFError, KeyboardInterrupt) as exc:
        permitted = {
            "SAMPLE_SIZE_INVALID", "URL_AND_CA_REQUIRED", "CREDENTIALS_REQUIRED",
            "HTTPS_ENDPOINT_REQUIRED", "CA_CERT_FILE_NOT_FOUND",
            "CA_CERT_INVALID_OR_UNREADABLE", "CA_VERIFICATION_UNAVAILABLE",
            "SEARCH_URI_TOO_LONG", "HTTP_NON_200", "HTTP_AUTH_OR_PERMISSION_FAILED",
            "HTTP_REDIRECT_REJECTED", "ES_SEARCH_REJECTED", "HTTP_SEARCH_FAILED",
            "CONNECTION_OR_TLS_UNAVAILABLE", "SEARCH_RESPONSE_TOO_LARGE",
            "SEARCH_RESPONSE_INVALID", "INDEX_COUNTS_CHANGED",
            "COUNT_NOT_EXACT", "UNVERIFIED_SAMPLE",
            "SEARCH_PARTIAL_OR_UNVERIFIED",
            "TLS_SAN_EXCEPTION_IP_LITERAL_REQUIRED",
        }
        code = str(exc) if isinstance(exc, ValueError) else "INPUT_UNAVAILABLE"
        report = {**minimal, "status": "UNAVAILABLE",
                  "reason_code": code if code in permitted else "SAMPLE_UNAVAILABLE"}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report["status"] == "OBSERVED_SAMPLE_NOT_PROVEN" else 2


if __name__ == "__main__":
    raise SystemExit(main())
