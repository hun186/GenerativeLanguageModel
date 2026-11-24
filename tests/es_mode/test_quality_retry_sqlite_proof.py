"""Disposable local SQLite CAS proof: synthetic only; no ES, LLM or runtime."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
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




def _terminate_sqlite_after_durable_commit_before_ack(db_path, operation):
    """Offline-only fault: exit the spawned child immediately after COMMIT."""
    store = DisposableQualityLedger(Path(db_path), KEY, create=False)
    native_connect = sqlite3.connect

    class _CrashAfterCommitConnection(sqlite3.Connection):
        def execute(self, statement, parameters=(), /):
            cursor = super().execute(statement, parameters)
            if statement == "COMMIT":
                # sqlite3 has completed the actual durable transition.
                # The caller must not report a successful ACK or retry blindly.
                os._exit(87)
            return cursor

    def _child_only_connect(*args, **kwargs):
        return native_connect(*args, factory=_CrashAfterCommitConnection, **kwargs)

    sqlite3.connect = _child_only_connect  # spawn child only; never runtime code
    if operation == "claim":
        store.transition(
            ident(), expected_revision=1, operation="claim", policy=ON,
            verified_attempt_id=A,
        )
    elif operation == "finalize":
        store.transition(
            ident(), expected_revision=2, operation="finalize", policy=ON,
            verified_attempt_id=A, result=QualityResult.REJECTED,
            failure_code="SCHEMA_EVENT_REFERENCE",
        )
    else:
        os._exit(98)
    os._exit(99)  # cannot report success; fail if COMMIT hook did not run


@pytest.mark.parametrize("operation", ["claim", "finalize"])
def test_process_death_after_commit_before_ack_preserves_single_cas(operation, tmp_path):
    """Unacknowledged COMMIT remains durable; stale retry cannot publish twice."""
    store = new_store(tmp_path)
    initial = reject_initial(store)
    assert initial.revision == 1 and initial.failed_repairs == 0
    if operation == "finalize":
        inflight = store.transition(
            ident(), expected_revision=1, operation="claim",
            policy=ON, verified_attempt_id=A,
        )
        assert inflight.phase == Phase.IN_FLIGHT and inflight.revision == 2

    ctx = multiprocessing.get_context("spawn")
    process = ctx.Process(
        target=_terminate_sqlite_after_durable_commit_before_ack,
        args=(str(tmp_path / "ledger.db"), operation),
    )
    try:
        process.start()
        process.join(timeout=25)
        assert process.exitcode == 87  # confirmed COMMIT, not a setup failure
        reopened = new_store(tmp_path, create=False)
        persisted = reopened.read(ident())
        if operation == "claim":
            assert persisted.phase == Phase.IN_FLIGHT
            assert persisted.revision == 2 and persisted.failed_repairs == 0
            assert persisted.active_attempt_id == A
            stale_revision = initial.revision
            stale_op = "claim"
            stale_kwargs = {"verified_attempt_id": B}
            # The caller did not observe its ACK. A restart must not silently
            # issue another repair until verified sink reconciliation.
            with pytest.raises(ValueError):
                reopened.transition(
                    ident(), expected_revision=persisted.revision,
                    operation="claim", policy=ON, verified_attempt_id=B,
                )
        else:
            assert persisted.phase == Phase.READY
            assert persisted.revision == 3 and persisted.failed_repairs == 1
            assert persisted.active_attempt_id is None
            assert persisted.last_quality_failure_code == "SCHEMA_EVENT_REFERENCE"
            stale_revision = 2
            stale_op = "finalize"
            stale_kwargs = {
                "verified_attempt_id": A,
                "result": QualityResult.REJECTED,
                "failure_code": "SCHEMA_EVENT_REFERENCE",
            }
            # Exactly one completed rejected quality repair is charged.
            assert reopened.read(ident()).failed_repairs == 1

        with pytest.raises(StaleRevision):
            reopened.transition(
                ident(), expected_revision=stale_revision,
                operation=stale_op, policy=ON, **stale_kwargs,
            )
        assert new_store(tmp_path, create=False).read(ident()) == persisted
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



def test_durable_repair_budget_never_crosses_document_output_pipeline_rule(tmp_path):
    """One exhausted identity must not poison another scope after restart."""
    store = new_store(tmp_path)
    original = ident()
    variants = [
        replace(original, source_document_id="PRIVATE_SOURCE_DOCUMENT_124"),
        replace(original, output_col="multidim_event_json_secondary"),
        replace(original, verified_pipeline_sha256="b" * 64),
        replace(original, quality_rule_version="multidim_event_profile_v2"),
    ]
    assert len(set(variants + [original])) == 5

    state = reject_initial(store)
    for token in (A, B):
        state = store.transition(
            original, expected_revision=state.revision, operation="claim",
            policy=ON, verified_attempt_id=token,
        )
        state = store.transition(
            original, expected_revision=state.revision, operation="finalize",
            policy=ON, verified_attempt_id=token,
            result=QualityResult.REJECTED,
            failure_code="SCHEMA_EVENT_REFERENCE",
        )
    assert state.phase == Phase.NEEDS_REVIEW
    assert state.failed_repairs == 2 and state.revision == 5

    # Every single identity dimension is part of the authenticated HMAC key.
    # A new pipeline or rule must not be blocked by an old exhausted budget.
    reopened = new_store(tmp_path, create=False)
    for variant in variants:
        fresh = reopened.read(variant)
        assert fresh.phase == Phase.UNASSESSED
        assert fresh.revision == 0 and fresh.failed_repairs == 0
        observed = reopened.transition(
            variant, expected_revision=0, operation="observe_initial",
            result=QualityResult.REJECTED,
            failure_code="SCHEMA_TIME_PRECISION",
        )
        assert observed.phase == Phase.READY
        assert observed.revision == 1 and observed.failed_repairs == 0

    # Claiming one revised identity must leave every other identity unchanged.
    claimed = reopened.transition(
        variants[2], expected_revision=1, operation="claim",
        policy=ON, verified_attempt_id=A,
    )
    assert claimed.phase == Phase.IN_FLIGHT and claimed.revision == 2
    assert claimed.failed_repairs == 0
    restarted = new_store(tmp_path, create=False)
    assert restarted.read(original) == state
    assert restarted.read(variants[2]) == claimed
    for variant in (variants[0], variants[1], variants[3]):
        other = restarted.read(variant)
        assert other.phase == Phase.READY
        assert other.revision == 1 and other.failed_repairs == 0

    with sqlite3.connect(tmp_path / "ledger.db") as con:
        keys = [row[0] for row in con.execute(
            "SELECT identity_key FROM quality_states ORDER BY identity_key"
        )]
    assert len(keys) == len(set(keys)) == 5
    assert all(len(key) == 64 and all(c in "0123456789abcdef" for c in key)
               for key in keys)
    raw = (tmp_path / "ledger.db").read_bytes()
    for value in (
        b"PRIVATE_SOURCE_DOCUMENT_123",
        b"PRIVATE_SOURCE_DOCUMENT_124",
        b"multidim_event_json_secondary",
        b"multidim_event_profile_v2",
        KEY,
    ):
        assert value not in raw



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



@pytest.mark.parametrize("damage", ["wrong_seal", "missing_seal", "wrong_schema"])
def test_already_opened_ledger_rechecks_seal_on_each_read_and_cas(tmp_path, damage):
    from contextlib import closing
    store = new_store(tmp_path)
    reject_initial(store)
    with closing(sqlite3.connect(tmp_path / "ledger.db")) as con, con:
        if damage == "wrong_seal":
            con.execute("UPDATE quality_seal SET check_hmac=?", ("0" * 64,))
        elif damage == "missing_seal":
            con.execute("DELETE FROM quality_seal")
        else:
            con.execute("PRAGMA user_version=99")
    # Existing object cannot treat an unknown key as a new budget, nor
    # update an existing state after the seal/schema no longer matches.
    with pytest.raises(LedgerUnavailable):
        store.read(replace(ident(), source_document_id="other"))
    with pytest.raises(LedgerUnavailable):
        store.transition(ident(), expected_revision=1, operation="claim",
                         policy=ON, verified_attempt_id=A)
    with pytest.raises(LedgerUnavailable):
        store.transition(replace(ident(), source_document_id="other"),
                         expected_revision=0, operation="observe_initial",
                         result=QualityResult.REJECTED, failure_code="SCHEMA_TIME_PRECISION")
    with closing(sqlite3.connect(tmp_path / "ledger.db")) as con:
        assert con.execute("SELECT revision FROM quality_states").fetchall() == [(1,)]


def test_already_opened_ledger_rejects_replacement_with_wrong_key(tmp_path):
    store = new_store(tmp_path)
    reject_initial(store)
    replacement = tmp_path / "replacement.db"
    DisposableQualityLedger(replacement, b"x" * 32, create=True)
    os.replace(replacement, tmp_path / "ledger.db")
    with pytest.raises(LedgerUnavailable, match="ledger secret mismatch"):
        store.read(ident())
    with pytest.raises(LedgerUnavailable, match="ledger secret mismatch"):
        reject_initial(store)
