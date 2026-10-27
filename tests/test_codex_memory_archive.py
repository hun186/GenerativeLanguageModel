"""Regression evidence for archive-first .codex memory compaction.

The original active memory files were copied by GitHub Contents API before
being rewritten. Checking the exact Git blob bytes makes historical decisions,
old CI/review evidence and superseded handoff text recoverable.
"""

import hashlib
from pathlib import Path

import pytest


_ROOT = Path(__file__).resolve().parents[1]
_ARCHIVE_STAMP = "20261027-213700"
_ORIGINAL_GIT_BLOBS = {
    "memory": "72e0fe6912d3c19e46b2c11de4da532e24ed61fd",
    "architecture": "6b3671c46d80acabd692bf2a6f227792c1b06018",
    "api_contract": "b1ef36b488496a83059bf82123c391b719cd3aab",
    "decisions": "2fcdc099dfd3065af18402dfc8e7aed9618b9195",
    "backlog": "0a40f0a9b26d7bebb7125a790995db6b84181a4f",
    "known_issues": "f6ac56a63f63f84b74cb6b5048c88086b70b0e4b",
}


def _git_blob_sha(content: bytes) -> str:
    """Git object hash computed without assuming git CLI is installed."""
    header = b"blob " + str(len(content)).encode("ascii") + b"\x00"
    return hashlib.sha1(header + content).hexdigest()


@pytest.mark.parametrize("name,expected", sorted(_ORIGINAL_GIT_BLOBS.items()))
def test_exact_original_archives_remain_recoverable(name, expected):
    archive = (
        _ROOT / ".codex" / "archive"
        / f"{name}.md-{_ARCHIVE_STAMP}.md"
    )
    assert archive.is_file()
    assert _git_blob_sha(archive.read_bytes()) == expected

    active = (_ROOT / ".codex" / f"{name}.md").read_text(encoding="utf-8")
    assert f"{name}.md-{_ARCHIVE_STAMP}.md" in active
    assert expected in active
    # This rule applies only to active agent memory, not to immutable history.
    assert len(active.splitlines()) <= 200
    assert len(active.encode("utf-8")) < 40_000


def test_active_router_reconciles_recent_accepted_main_and_open_pr():
    router = (_ROOT / ".codex" / "project.md").read_text(encoding="utf-8")
    memory = (_ROOT / ".codex" / "memory.md").read_text(encoding="utf-8")
    backlog = (_ROOT / ".codex" / "backlog.md").read_text(encoding="utf-8")
    assert "46b7c7290417421a6dc09e114f82c1066ce0179d" in router
    assert "#239" in router and "#239" in memory
    assert "#231" in router and "#231" in backlog
    assert "40513712390" in router and "40513712390" in memory
    assert "operator-deferred" in router
    assert "explicit" in backlog.lower()
    assert "automatic" in backlog.lower()
    # No old “pending review” handoff should displace the new current focus.
    assert "Current Focus — PR #226" not in memory
    assert "Issue #211 multistage JSON writeback corrective" not in backlog


def test_archive_checkout_uses_exact_bytes_even_with_windows_autocrlf():
    attrs = (_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert (
        ".codex/archive/*.md-20261027-213700.md -text"
        in attrs.splitlines()
    )


def test_current_es_multidim_and_writeback_contracts_remain_active():
    """Compaction must not silently turn active ES safety rules into history."""
    contract = (_ROOT / ".codex" / "api_contract.md").read_text(
        encoding="utf-8"
    )
    decisions = (_ROOT / ".codex" / "decisions.md").read_text(
        encoding="utf-8"
    )
    architecture = (_ROOT / ".codex" / "architecture.md").read_text(
        encoding="utf-8"
    )
    for field in ("article_date_iso", "article_date_precision", "event_ids",
                  "confirm_writeback()", "Success"):
        assert field in contract
    assert "from one slice" in contract
    assert "YYYY-01-01" in contract
    assert "unknown" in contract
    assert "acknowledgement" in decisions
    assert "es_sink.py" in architecture


def test_archive_integrity_is_in_active_hosted_linux_gate():
    workflow = (
        _ROOT / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    start = workflow.index("  offline-e2e:")
    end = workflow.index("  unit-linux:")
    assert "tests/test_codex_memory_archive.py" in workflow[start:end]
