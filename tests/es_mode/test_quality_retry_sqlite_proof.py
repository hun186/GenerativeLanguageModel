"""Disposable local SQLite CAS proof: synthetic only; no ES, LLM or runtime."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import multiprocessing
import os
import queue
import sqlite3
import threading

import pytest

from czjLLM.es_mode.quality_retry_contract import (
    RetryIdentity, RetryPolicy, Phase, QualityResult, StaleRevision,
)
from czjLLM.es_mode.quality_retry_sqlite_proof import (
    DisposableQualityLedger, LedgerUnavailable,
)

KEY = b"synthetic-disposable-unit-test-key-42b" * 2
A = "12345678-1234-4234-8234-1234567890a1"
B = "12345678-1234-4234-8234-1234567890a2"
RESET = "12345678-1234-4234-8234-1234567890a3"
ON = RetryPolicy(enabled=True)


def ident():
    return RetryIdentity(
        "PRIVATE_SOURCE_DOCUMENT_123", "multidim_event_json",
        "a" * 64, "multidim_event_profile_v1",
    )


def new_store(tmp_path, *, create=True):
    return DisposableQualityLedger(tmp_path / "ledger.db", KEY, create=create)


def reject_initial(store):
    return store.transition(
        ident(), expected_revision=0, operation="observe_initial",
        result=QualityResult.REJECTED, failure_code="SCHEMA_TIME_PRECISION",
    )


def test_store_needs_explicit_create_and_private_dir(tmp_path):
    with pytest.raises(LedgerUnavailable):
        new_store(tmp_path, create=False)
    created = new_store(tmp_path)
    assert created.read(ident()).phase == Phase.UNASSESSED
    with pytest.raises(LedgerUnavailable):
        new_store(tmp_path, create=True)
    with pytest.raises(LedgerUnavailable):
        DisposableQualityLedger(tmp_path / "another.db", b"short", create=True)


def test_two_connections_claim_once_then_resume_inflight_after_restart(tmp_path):
    store = new_store(tmp_path)
    state = reject_initial(store)
    assert state.revision == 1
    barrier = threading.Barrier(2)

    def worker(token):
        fixture = new_store(tmp_path, create=False)
        seen = fixture.read(ident())
        barrier.wait()
        try:
            return fixture.transition(
                ident(), expected_revision=seen.revision, operation="claim",
                policy=ON, verified_attempt_id=token,
            )
        except StaleRevision:
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(worker, (A, B)))
    assert sum(x is not None for x in results) == 1
    opened = new_store(tmp_path, create=False).read(ident())
    assert opened.phase == Phase.IN_FLIGHT
    assert opened.revision == 2
    assert opened.failed_repairs == 0
    with pytest.raises((StaleRevision, ValueError)):
        store.transition(
            ident(), expected_revision=1, operation="claim",
            policy=ON, verified_attempt_id=A,
        )


def _spawn_quality_claim(path, attempt_id, ready, start, outcomes):
    """Top-level spawn target: independent process; never touches ES/LLM."""
    try:
        store = DisposableQualityLedger(Path(path), KEY, create=False)
        state = store.read(ident())
        ready.put(state.revision)
        if not start.wait(timeout=25):
            outcomes.put("START_TIMEOUT")
            return
        try:
            claimed = store.transition(
                ident(), expected_revision=state.revision, operation="claim",
                policy=ON, verified_attempt_id=attempt_id,
            )
        except (StaleRevision, LedgerUnavailable):
            outcomes.put("BLOCKED")
        else:
            outcomes.put("WON" if claimed.phase == Phase.IN_FLIGHT else "BAD_PHASE")
    except Exception:
        # No raw paths, secrets, exception repr or identity exported.
        outcomes.put("UNEXPECTED_ERROR")


def test_independent_spawned_processes_can_never_claim_same_revision(tmp_path):
    store = new_store(tmp_path)
    assert reject_initial(store).revision == 1
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    ready = ctx.Queue()
    outcomes = ctx.Queue()
    workers = [
        ctx.Process(target=_spawn_quality_claim, args=(
            str(tmp_path / "ledger.db"), token, ready, start, outcomes,
        ))
        for token in (A, B)
    ]
    try:
        for process in workers:
            process.start()
        assert [ready.get(timeout=25), ready.get(timeout=25)] == [1, 1]
        start.set()
        results = [outcomes.get(timeout=25), outcomes.get(timeout=25)]
        assert sorted(results) == ["BLOCKED", "WON"]
        for process in workers:
            process.join(timeout=25)
            assert process.exitcode == 0
        persisted = new_store(tmp_path, create=False).read(ident())
        assert persisted.phase == Phase.IN_FLIGHT
        assert persisted.revision == 2
        assert persisted.failed_repairs == 0
    finally:
        start.set()
        for process in workers:
            if process.is_alive():
                process.terminate()
            process.join(timeout=5)
        ready.close()
        outcomes.close()



def _terminate_sqlite_claim_after_update_before_commit(db_path):
    """Spawn-only fault injection in a disposable ledger, never a runtime hook."""
    store = DisposableQualityLedger(Path(db_path), KEY, create=False)
    original_connect = DisposableQualityLedger._connect

    def _connection_with_temporary_abort_trigger(self):
        con = original_connect(self)
        # TEMP trigger and callback exist only in this child connection. The
        # real transition performs its own BEGIN IMMEDIATE, signed UPDATE,
        # then would COMMIT; exit at the UPDATE/COMMIT boundary.
        con.create_function("abort_before_commit", 0, lambda: os._exit(86))
        con.execute(
            "CREATE TEMP TRIGGER fail_before_commit "
            "AFTER UPDATE ON main.quality_states "
            "BEGIN SELECT abort_before_commit(); END"
        )
        return con

    DisposableQualityLedger._connect = _connection_with_temporary_abort_trigger
    store.transition(
        ident(), expected_revision=1, operation="claim", policy=ON,
        verified_attempt_id=A,
    )
    # Must never be reached; distinct exit status makes false positives fail.
    os._exit(99)


def test_terminated_writer_before_commit_preserves_previous_claim_budget(tmp_path):
    """Real child-process exit after SQLite UPDATE must roll back the CAS."""
    store = new_store(tmp_path)
    before = reject_initial(store)
    assert before.phase == Phase.READY
    assert before.revision == 1 and before.failed_repairs == 0

    ctx = multiprocessing.get_context("spawn")
    process = ctx.Process(
        target=_terminate_sqlite_claim_after_update_before_commit,
        args=(str(tmp_path / "ledger.db"),),
    )
    try:
        process.start()
        process.join(timeout=25)
        assert process.exitcode == 86  # SQLite UPDATE trigger actually fired
        # A new independent connection must recover the hot rollback journal
        # and see the pre-crash signed state, not a phantom IN_FLIGHT claim.
        after = new_store(tmp_path, create=False).read(ident())
        assert after == before
        assert after.phase == Phase.READY and after.failed_repairs == 0
        assert after.active_attempt_id is None

        # No automatic replay is attempted. This explicitly authorized test
        # claim models a new dispatch decision after local state recovery.
        claimed = new_store(tmp_path, create=False).transition(
            ident(), expected_revision=after.revision, operation="claim",
            policy=ON, verified_attempt_id=B,
        )
        assert claimed.phase == Phase.IN_FLIGHT
        assert claimed.revision == 2 and claimed.failed_repairs == 0
        assert new_store(tmp_path, create=False).read(ident()) == claimed
    finally:
        if process.is_alive():
            process.terminate()
        if process.pid is not None:
            process.join(timeout=5)



def test_repair_exhaustion_survives_restart_without_another_claim(tmp_path):
    store = new_store(tmp_path)
    state = reject_initial(store)
    for token in (A, B):
        state = store.transition(
            ident(), expected_revision=state.revision, operation="claim",
            policy=ON, verified_attempt_id=token,
        )
        state = new_store(tmp_path, create=False).transition(
            ident(), expected_revision=state.revision, operation="finalize",
            policy=ON, verified_attempt_id=token,
            result=QualityResult.REJECTED,
            failure_code="SCHEMA_EVENT_REFERENCE",
        )
    assert state.failed_repairs == 2 and state.phase == Phase.NEEDS_REVIEW
    persisted = new_store(tmp_path, create=False).read(ident())
    assert persisted == state
    with pytest.raises(ValueError):
        store.transition(
            ident(), expected_revision=persisted.revision, operation="claim",
            policy=ON, verified_attempt_id=A,
        )
    reset = store.transition(
        ident(), expected_revision=persisted.revision,
        operation="manual_reset", operator_authorized=True,
        unique_operator_action_id=RESET,
    )
    assert reset.phase == Phase.READY and reset.failed_repairs == 0
    assert new_store(tmp_path, create=False).read(ident()) == reset


def test_unknown_date_completion_never_enters_repair_queue(tmp_path):
    store = new_store(tmp_path)
    state = store.transition(
        ident(), expected_revision=0, operation="observe_initial",
        result=QualityResult.ACCEPTED_UNKNOWN_DATE,
    )
    assert state.phase == Phase.COMPLETE
    with pytest.raises(ValueError):
        store.transition(
            ident(), expected_revision=state.revision, operation="claim",
            policy=ON, verified_attempt_id=A,
        )


def test_tamper_or_wrong_hmac_key_fails_closed(tmp_path):
    store = new_store(tmp_path)
    reject_initial(store)
    with sqlite3.connect(tmp_path / "ledger.db") as con:
        con.execute(
            "UPDATE quality_states SET snapshot=?",
            ('{"phase":"COMPLETE","revision":1}',),
        )
    with pytest.raises(LedgerUnavailable, match="ledger snapshot invalid"):
        store.read(ident())
    with pytest.raises(LedgerUnavailable, match="ledger secret mismatch"):
        DisposableQualityLedger(
            tmp_path / "ledger.db", b"different-key-material-32bytes-more" * 2,
            create=False,
        )


def test_on_disk_does_not_include_plaintext_identifiers_or_secret(tmp_path):
    store = new_store(tmp_path)
    reject_initial(store)
    raw = (tmp_path / "ledger.db").read_bytes()
    for marker in (b"PRIVATE_SOURCE_DOCUMENT", b"multidim_event_json",
                   b"multidim_event_profile_v1", b"aaaaaa", KEY):
        assert marker not in raw
