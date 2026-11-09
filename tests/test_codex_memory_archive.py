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


def test_single_extract_resume_source_identity_is_still_active():
    architecture = (_ROOT / ".codex" / "architecture.md").read_text(
        encoding="utf-8"
    )
    decisions = (_ROOT / ".codex" / "decisions.md").read_text(
        encoding="utf-8"
    )
    for value in (
        "_extract_slice_identity/source/original.json",
        "smart_reset", "ordered", "stage-task", "Success",
    ):
        assert value in architecture
    assert "Remaining TODO" in architecture
    assert "split" in decisions
    assert "raw chunk hashes" in decisions
    assert "fails closed" in architecture


def test_importance_score_shape_repair_stays_strict():
    contract = (_ROOT / ".codex" / "api_contract.md").read_text(
        encoding="utf-8"
    )
    architecture = (_ROOT / ".codex" / "architecture.md").read_text(
        encoding="utf-8"
    )
    for field in (
        "_normalize_flat_importance_fields()",
        "coverage", "novelty", "impact", "credibility",
        "importance_score", "integer", "null",
    ):
        assert field in contract
    assert "excluding booleans" in contract
    assert "reject conflicting values" in contract
    assert "unknown fields" in contract.lower() or "Unknown fields" in contract
    assert "lossless shape" in architecture


def test_cache_aware_provider_audit_and_stage_isolated_gui_are_active():
    """Do not archive away still-effective cache/throughput semantics."""
    contract = (_ROOT / ".codex" / "api_contract.md").read_text(
        encoding="utf-8"
    )
    architecture = (_ROOT / ".codex" / "architecture.md").read_text(
        encoding="utf-8"
    )
    decisions = (_ROOT / ".codex" / "decisions.md").read_text(
        encoding="utf-8"
    )
    for field in (
        "cached_input_tokens", "cached_input_token_source",
        "stage_identity", "effective_tok_per_s_est",
        "total_tok_per_s", "processing_tps", "provider_usage",
    ):
        assert field in contract
    assert "missing data" in contract
    assert "zero cached input" in contract
    assert "two prior" in contract
    assert "50%" in contract
    assert "different stages must never" in contract
    assert "heuristic" in decisions
    assert "historical" in architecture


# The 2026-10-28 acceptance reconciliation is a second, distinct
# archive-first compaction. The original 2026-10-27 six-file snapshots remain
# independently checked by test_exact_original_archives_remain_recoverable.
_RECONCILIATION_GIT_BLOBS = {
    "project": "a4eeb14fe91dadbb3583087a1517f1f290f2834c",
    "memory": "309b57f00fc85f0d03fd12fdb3b7bdfdaa4708d8",
    "backlog": "67b64c801806d585e246d9f0091efe4cb69d37ef",
}


@pytest.mark.parametrize("name,expected", sorted(_RECONCILIATION_GIT_BLOBS.items()))
def test_reconciliation_archive_is_exact_and_active_linked(name, expected):
    """Do not lose the pre-reconciliation review/merge handoffs."""
    stem = f"{name}.md-20261028-104900.md"
    archived = _ROOT / ".codex" / "archive" / stem
    active = _ROOT / ".codex" / f"{name}.md"
    assert archived.is_file() and active.is_file()
    assert _git_blob_sha(archived.read_bytes()) == expected
    body = active.read_text(encoding="utf-8")
    assert stem in body and expected in body
    assert len(body.splitlines()) <= 200
    assert len(body.encode("utf-8")) < 40_000
    attrs = (_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert ".codex/archive/*-20261028-104900.md -text" in attrs


def test_current_handoffs_do_not_reopen_merged_240_241_242():
    """The active work queue follows accepted Hosted main, not old PR text."""
    router = (_ROOT / ".codex" / "project.md").read_text(encoding="utf-8")
    memory = (_ROOT / ".codex" / "memory.md").read_text(encoding="utf-8")
    backlog = (_ROOT / ".codex" / "backlog.md").read_text(encoding="utf-8")
    focus = router.split("## Current Focus", 1)[1].split(
        "## Recent Accepted Outcomes", 1
    )[0]
    current = backlog.split("## Current Summary", 1)[1].split(
        "## True Open Engineering Work", 1
    )[0]
    for content in (focus, current, memory.split("## Current Summary", 1)[1].split(
            "## Accepted Recent Outcomes", 1)[0]):
        assert "e010a5e07c45016f8f0ab4094c30bcd33825d3b5" in content
        assert "40623677955" in content and "SUCCESS" in content
        assert "#231" in content
    for number in ("#240", "#241", "#242"):
        assert number in router and number in memory and number in backlog
    assert "operator-deferred" in focus
    # Escaped text '\\n-' must never splice two independent active bullets.
    assert r"\n- " not in current
    open_items = [
        line for line in backlog.splitlines() if line.startswith("- [ ]")
    ]
    assert open_items
    assert all(
        not any(number in line for number in ("#240", "#241", "#242"))
        for line in open_items
    )
    for old_branch in (
        "docs/codex-active-memory-compaction-20261027",
        "fix/quality-report-protect-manifest-output-20261028",
        "fix/llm-failure-report-cross-dir-ledger-output-20261028",
    ):
        assert old_branch not in focus
        assert old_branch not in current


def test_active_accepted_protection_issues_do_not_require_rediscovery():
    """Historical review-stage risk notes must not masquerade as open PR work."""
    known = (_ROOT / ".codex" / "known_issues.md").read_text(
        encoding="utf-8"
    )
    contract = (_ROOT / ".codex" / "api_contract.md").read_text(
        encoding="utf-8"
    )
    current = known.split("## Current Acceptance Reconciliation", 1)[1].split(
        "## Environment and External Dependencies", 1
    )[0]
    for value in ("#240", "#241", "#242", "40623677955", "SUCCESS", "#231"):
        assert value in current
    assert "operator-deferred" in current
    assert "accepted PR #241" in contract
    assert "pending PR acceptance" not in contract


def test_20261030_precompaction_memory_is_exact_and_active_is_bounded():
    """Archive full pre-untracking handoff before compacting current memory."""
    archived = _ROOT / ".codex" / "archive" / "memory.md-20261030-103500.md"
    active = _ROOT / ".codex" / "memory.md"
    expected_blob = "8af2694365bd5202a1533a36c8b7cd4c82f22408"
    assert archived.is_file()
    assert _git_blob_sha(archived.read_bytes()) == expected_blob
    content = active.read_text(encoding="utf-8")
    assert "memory.md-20261030-103500.md" in content
    assert expected_blob in content
    assert len(content.encode("utf-8")) < 40_000
    assert len(content.splitlines()) <= 200
    attrs = (_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert ".codex/archive/memory.md-20261030-103500.md -text" in attrs.splitlines()


def test_20261030_phase2f_known_issues_archive_is_exact_and_active_bounded():
    """Keep exact historical known issues before compacting the active file."""
    stem = "known_issues.md-20261030-191600.md"
    expected = "e293b2406ffcbf1f48b119f566b52ebbe86854af"
    archive = _ROOT / ".codex" / "archive" / stem
    active = _ROOT / ".codex" / "known_issues.md"
    assert archive.is_file()
    assert _git_blob_sha(archive.read_bytes()) == expected
    body = active.read_text(encoding="utf-8")
    assert stem in body and expected in body
    assert len(body.splitlines()) <= 200
    assert len(body.encode("utf-8")) < 40_000
    assert "## Current Acceptance Reconciliation" in body
    assert "## Environment and External Dependencies" in body
    assert "Windows" in body and "operator-deferred" in body
    assert "WINDOWS_EXPERIMENTAL_UNVERIFIED" in body
    assert "ES" in body and "SQL" in body
    attrs = (_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert f".codex/archive/{stem} -text" in attrs


# PR #270: never replace current focus, memory handoffs, or backlog status
# without preserving the exact immediately preceding Git blob. This is
# independent of earlier archive-first compactions and older test fixtures.
_PR270_PRE_RECONCILIATION_BLOBS = {
    "project": "1c5a01d44264de3ff5baed5fade965c0e6dd1aa5",
    "memory": "53ef85bf9d6a616177e84b9f594b8ae28a1defea",
    "backlog": "869d39e0b2ba37a1e2691c5a3a1cc051be41e6bf",
}


@pytest.mark.parametrize("name,expected", sorted(_PR270_PRE_RECONCILIATION_BLOBS.items()))
def test_pr270_reconciliation_keeps_exact_pre_edit_handoff_archive(name, expected):
    stem = f"{name}.md-20261101-234800.md"
    archive = _ROOT / ".codex" / "archive" / stem
    active = _ROOT / ".codex" / f"{name}.md"
    assert archive.is_file()
    assert _git_blob_sha(archive.read_bytes()) == expected
    body = active.read_text(encoding="utf-8")
    assert stem in body and expected in body
    assert len(body.splitlines()) <= 200
    assert len(body.encode("utf-8")) < 40_000
    attrs = (_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert ".codex/archive/*-20261101-234800.md -text" in attrs


# 2026-11-02 owner-authorized #271-#274 reconciliation. These original
# handoffs are independently preserved before the active files are edited.
_POST_GUI_AUDIT_BLOBS = {
    "project": "c9363be1ce0c02157dbbd860b60708071d6899a3",
    "memory": "5725c26247056df7baf8f8814d2998865461f259",
    "backlog": "0c6122251db1110a205f38618d5809b14441fe95",
}


@pytest.mark.parametrize("name,expected", sorted(_POST_GUI_AUDIT_BLOBS.items()))
def test_20261102_gui_audit_reconciliation_archives_exact_git_blobs(name, expected):
    stem = f"{name}.md-20261102-152500.md"
    archive = _ROOT / ".codex" / "archive" / stem
    active = _ROOT / ".codex" / f"{name}.md"
    assert archive.is_file() and active.is_file()
    assert _git_blob_sha(archive.read_bytes()) == expected
    body = active.read_text(encoding="utf-8")
    assert stem in body and expected in body
    assert len(body.splitlines()) <= 200
    assert len(body.encode("utf-8")) < 40_000
    attrs = (_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert ".codex/archive/*-20261102-152500.md -text" in attrs


def test_gui_audit_work_done_is_not_reopened_in_current_handoff():
    files = {
        name: (_ROOT / ".codex" / f"{name}.md").read_text(encoding="utf-8")
        for name in ("project", "memory", "backlog")
    }
    merged = {
        "#271": "e303a203657933847be4576b97fb9253fb990d7a",
        "#272": "4befa0e1c29e46f614adeec8d3444df67ea4b7d1",
        "#273": "a6720a7e636e40d1c814bdf52fc529217c829de2",
        "#274": "7a7a9ba259e77b90f51737771bcc30058f231eae",
    }
    for name, text in files.items():
        current = text.split(
            "## Current Focus" if name == "project" else "## Current Summary",
            1,
        )[1].split("## ", 1)[0]
        assert all(number in current and sha in current
                   for number, sha in merged.items())
        assert "#266" in current and "operator-deferred" in current
        assert "Windows" in current and "SQL/ES" in current

    active = files["backlog"].split("## True Open Engineering Work", 1)[1]
    current_items = active.split("## Recent Changes", 1)[0].splitlines()
    assert any("- [x]" in line and "#273" in line for line in current_items)
    assert any("- [x]" in line and "#274" in line for line in current_items)
    assert any("- [ ]" in line and "#266" in line for line in current_items)
    assert not any("- [ ]" in line and any(n in line for n in merged)
                   for line in current_items)


def test_20261103_known_issues_archive_keeps_exact_precompaction_evidence():
    original = (
        _ROOT / ".codex" / "archive"
        / "known_issues.md-20261103-113300.md"
    )
    body = (_ROOT / ".codex" / "known_issues.md").read_text(
        encoding="utf-8",
    )
    assert original.is_file()
    assert _git_blob_sha(original.read_bytes()) == (
        "75331f0cee171fa8bb31d0ea9745b81f3079f189"
    )
    assert "known_issues.md-20261103-113300.md" in body
    assert "75331f0cee171fa8bb31d0ea9745b81f3079f189" in body
    assert len(body.encode("utf-8")) < 40_000
    assert len(body.splitlines()) <= 200
    assert "WINDOWS_EXPERIMENTAL_UNVERIFIED" in body
    assert "operator-deferred" in body and "SQL/ES" in body
    assert ".codex/archive/known_issues.md-20261103-113300.md -text" in (
        (_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    )


def test_20261103_pr276_acceptance_handoff_archives_are_exact_and_current():
    pre_edit = {
        "memory": "1676ac16c18ad268d68582b10b2ab2e20f6718e7",
        "backlog": "2fd9b9e92b384ed73faf3503f1babec6f266c454",
    }
    merge_sha = "0e4d719577060414f2a938c12aa19dfe6d777dc8"
    for name, expected in pre_edit.items():
        archived_name = f"{name}.md-20261103-134000.md"
        history = _ROOT / ".codex" / "archive" / archived_name
        active = (_ROOT / ".codex" / f"{name}.md").read_text(
            encoding="utf-8",
        )
        assert history.is_file()
        assert _git_blob_sha(history.read_bytes()) == expected
        assert archived_name in active and expected in active
        assert merge_sha in active and "#276" in active
        assert "operator-deferred" in active and "#266" in active
        assert len(active.encode("utf-8")) < 40_000
        assert len(active.splitlines()) <= 200

    backlog = (_ROOT / ".codex" / "backlog.md").read_text(encoding="utf-8")
    active_work = backlog.split("## True Open Engineering Work", 1)[1]
    active_work = active_work.split("## Recent Changes", 1)[0]
    assert any(
        line.startswith("- [x]") and "#276" in line
        for line in active_work.splitlines()
    )
    assert not any(
        line.startswith("- [ ]") and "Worker pre-call model/IP telemetry PR" in line
        for line in active_work.splitlines()
    )
    assert any(
        line.startswith("- [ ]") and "#266" in line
        for line in active_work.splitlines()
    )
    attributes = (_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert ".codex/archive/*-20261103-134000.md -text" in attributes.splitlines()


def test_20261110_owned_lease_contract_archive_first_compaction():
    """Precompact API contract remains byte-for-byte recoverable on Windows."""
    archived_name = "api_contract.md-20261110-013200.md"
    expected = "2c14b81b42e23ef0a43e87a29469796a2c12a851"
    archive = _ROOT / ".codex" / "archive" / archived_name
    active = (_ROOT / ".codex" / "api_contract.md").read_text(encoding="utf-8")
    assert archive.is_file()
    assert _git_blob_sha(archive.read_bytes()) == expected
    assert archived_name in active and expected in active
    assert "return_lease_token" in active and "lease_token" in active
    assert "accepted PR #241" in active
    assert len(active.encode("utf-8")) < 40_000
    assert len(active.splitlines()) <= 200
    attributes = (_ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines()
    assert f".codex/archive/{archived_name} -text" in attributes
