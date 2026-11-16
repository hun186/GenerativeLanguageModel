"""GET-only live Mapping check for GLM MultiDim/SRAF-compatible news_test.

No ES search, document export, update, bulk, LLM or replay. HTTPS with CA
validation is mandatory. IP SAN mismatch is an explicit *diagnostic* exception
that preserves certificate-chain validation and never yields an unqualified PASS.
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
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

# Support direct execution from any working directory.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from czjLLM.common.multidim_mapping_contract_audit import (  # noqa: E402
    INDEX, inspect_mapping_response,
)

MAX_MAPPING_BYTES = 2 * 1024 * 1024


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _endpoint(url: str) -> str:
    try:
        p = urlsplit(url.strip())
        if (p.scheme != "https" or not p.hostname or p.username is not None
                or p.password is not None or p.path not in ("", "/")
                or p.query or p.fragment or p.port is not None and not (1 <= p.port <= 65535)):
            raise ValueError("invalid endpoint")
        # Only a fixed path is appended. Do not accept any URL-supplied path.
        return p.geturl().rstrip("/")
    except (ValueError, TypeError) as exc:
        raise ValueError("HTTPS_ENDPOINT_REQUIRED") from None


def _request_mapping(url: str, cafile: str, username: str, password: str,
                     *, skip_hostname: bool = False) -> dict:
    ca = Path(cafile)
    if not ca.is_file():
        raise ValueError("CA_CERT_FILE_NOT_FOUND")
    try:
        context = ssl.create_default_context(cafile=str(ca))
    except (OSError, ssl.SSLError):
        raise ValueError("CA_CERT_INVALID_OR_UNREADABLE") from None
    if skip_hostname:
        # TLS CA chain + validity still verified (CERT_REQUIRED).
        context.check_hostname = False
    assert context.verify_mode == ssl.CERT_REQUIRED
    auth = base64.b64encode((username + ":" + password).encode("utf-8")).decode("ascii")
    req = Request(
        _endpoint(url) + "/" + INDEX + "/_mapping",
        headers={"Authorization": "Basic " + auth, "Accept": "application/json"},
        method="GET",
    )
    opener = build_opener(HTTPSHandler(context=context), _NoRedirect())
    try:
        with opener.open(req, timeout=12) as response:
            if response.getcode() != 200:
                raise ValueError("HTTP_NON_200")
            data = response.read(MAX_MAPPING_BYTES + 1)
    except HTTPError as exc:
        if exc.code in (401, 403):
            raise ValueError("HTTP_AUTH_OR_PERMISSION_FAILED") from None
        if 300 <= exc.code <= 399:
            raise ValueError("HTTP_REDIRECT_REJECTED") from None
        raise ValueError("HTTP_MAPPING_REQUEST_FAILED") from None
    except (ssl.SSLCertVerificationError,) as exc:
        raise ValueError("TLS_CERTIFICATE_VERIFICATION_FAILED") from None
    except (OSError, URLError, TimeoutError, ssl.SSLError):
        raise ValueError("CONNECTION_OR_TLS_UNAVAILABLE") from None
    if len(data) > MAX_MAPPING_BYTES:
        raise ValueError("MAPPING_RESPONSE_TOO_LARGE")
    try:
        result = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ValueError("MAPPING_JSON_INVALID") from None
    if not isinstance(result, dict):
        raise ValueError("MAPPING_JSON_INVALID")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True, help="ES HTTPS origin, without path/query/credentials")
    parser.add_argument("--ca-cert", required=True, help="CA chain file for HTTPS verification")
    parser.add_argument("--allow-ip-san-mismatch", action="store_true",
                        help="Explicit diagnostic-only hostname exception; CA still required")
    args = parser.parse_args(argv)
    base = {"index": INDEX, "read_only": True, "no_writeback_or_replay": True}
    try:
        url = _endpoint(args.url)
        username = input("ES user (not shown in report): ").strip()
        password = getpass.getpass("ES password (hidden): ")
        if not username or not password:
            raise ValueError("CREDENTIALS_REQUIRED")
        mapping = _request_mapping(url, args.ca_cert, username, password,
                                   skip_hostname=args.allow_ip_san_mismatch)
        report = inspect_mapping_response(mapping)
        report["tls_ca_chain_verification"] = "REQUIRED"
        report["tls_ip_san_verification"] = (
            "TEMPORARILY_SKIPPED" if args.allow_ip_san_mismatch else "REQUIRED"
        )
        if args.allow_ip_san_mismatch and report["status"] == "OBSERVED_MAPPING_COMPATIBLE":
            report["status"] = "OBSERVED_WITH_TLS_EXCEPTION"
    except ValueError as exc:
        # Emit only our predefined reason codes, never exception text containing secrets.
        reasons = {
            "HTTPS_ENDPOINT_REQUIRED", "CA_CERT_FILE_NOT_FOUND",
            "CA_CERT_INVALID_OR_UNREADABLE", "HTTP_NON_200",
            "HTTP_AUTH_OR_PERMISSION_FAILED", "HTTP_REDIRECT_REJECTED",
            "HTTP_MAPPING_REQUEST_FAILED", "TLS_CERTIFICATE_VERIFICATION_FAILED",
            "CONNECTION_OR_TLS_UNAVAILABLE", "MAPPING_RESPONSE_TOO_LARGE",
            "MAPPING_JSON_INVALID", "CREDENTIALS_REQUIRED",
        }
        code = str(exc)
        report = {**base, "status": "UNAVAILABLE",
                  "reason_code": code if code in reasons else "MAPPING_AUDIT_UNAVAILABLE"}
    except (EOFError, KeyboardInterrupt):
        report = {**base, "status": "UNAVAILABLE", "reason_code": "INPUT_UNAVAILABLE"}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    return 0 if report.get("status") == "OBSERVED_MAPPING_COMPATIBLE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
