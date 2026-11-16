"""Isolated, opt-in, disposable SQLite CAS proof for Issue #313.

NOT a production ES/Queue/LLM retry ledger. This module is not imported by
GLM dispatch. Caller-provided "verified" values and authorizations are NOT
authenticated here; no runtime dispatch may rely on this proof.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import sqlite3
import stat

from czjLLM.es_mode.quality_retry_contract import (
    RetryIdentity, RetryPolicy, RetryState, Phase, QualityResult,
    StaleRevision, StateTransitionError, observe_initial, claim_quality_repair,
    finalize_quality_repair, reconcile_uncertain,
    normalize_policy_exhaustion, authorized_manual_reset,
)

_SCHEMA_VERSION = 1
_MAX_PAYLOAD = 4096
_FIELDS = (
    "phase", "failed_repairs", "revision", "active_attempt_id",
    "last_quality_failure_code", "manual_reset_generation",
    "last_manual_reset_id",
)


class LedgerUnavailable(StateTransitionError):
    """Fixed, private-data-free failure."""


def _secret(key: bytes) -> bytes:
    if type(key) is not bytes or len(key) < 32:
        raise LedgerUnavailable("ledger secret unavailable")
    return key


def _identity_key(identity: RetryIdentity, secret: bytes) -> str:
    if not isinstance(identity, RetryIdentity):
        raise LedgerUnavailable("ledger identity unverified")
    data = json.dumps(
        [identity.source_document_id, identity.output_col,
         identity.verified_pipeline_sha256, identity.quality_rule_version],
        separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")
    return hmac.new(secret, b"glm-quality-ledger-key-v1\0" + data,
                    hashlib.sha256).hexdigest()


def _snapshot_mac(key: str, raw: str, secret: bytes) -> str:
    return hmac.new(
        secret, b"glm-quality-ledger-snapshot-v1\0" +
        key.encode("ascii") + b"\0" + raw.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def _encode(state: RetryState) -> str:
    body = {name: (state.phase.value if name == "phase" else getattr(state, name))
            for name in _FIELDS}
    return json.dumps(body, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _decode(raw: str, identity: RetryIdentity) -> RetryState:
    if type(raw) is not str or len(raw.encode("utf-8")) > _MAX_PAYLOAD:
        raise LedgerUnavailable("ledger snapshot invalid")
    try:
        body = json.loads(raw)
        if not isinstance(body, dict) or set(body) != set(_FIELDS):
            raise ValueError("invalid snapshot")
        body["phase"] = Phase(body["phase"])
        return RetryState(identity=identity, **body)
    except (ValueError, TypeError, KeyError, OverflowError):
        raise LedgerUnavailable("ledger snapshot invalid") from None


def _private_file(path: Path, *, create: bool) -> None:
    # This proof deliberately refuses world-readable/shared directories,
    # symlinks, hardlinks and implicit DB creation. Not an NTFS/SMB guarantee.
    try:
        parent = path.parent
        st = parent.lstat()
        if stat.S_ISLNK(st.st_mode) or not stat.S_ISDIR(st.st_mode):
            raise LedgerUnavailable("private ledger directory required")
        if os.name != "nt" and st.st_mode & 0o077:
            raise LedgerUnavailable("private ledger directory required")
        if create:
            flags = (os.O_CREAT | os.O_EXCL | os.O_WRONLY |
                     getattr(os, "O_NOFOLLOW", 0))
            fd = os.open(path, flags, 0o600)
            os.close(fd)
        target = path.lstat()
        if (not stat.S_ISREG(target.st_mode) or target.st_nlink != 1
                or (os.name != "nt" and target.st_mode & 0o077)):
            raise LedgerUnavailable("private ledger file required")
    except LedgerUnavailable:
        raise
    except OSError:
        raise LedgerUnavailable("private ledger file unavailable") from None


class DisposableQualityLedger:
    """Explicitly created local fixture; not an ES/Worker authorization API."""

    def __init__(self, path: Path, secret: bytes, *, create: bool = False):
        self.path = Path(path)
        self.secret = _secret(secret)
        _private_file(self.path, create=create)
        with self._connect() as connection:
            # Only create the schema when the caller explicitly created a
            # disposable file. Never silently repair or migrate a ledger.
            if create:
                connection.execute(
                    "CREATE TABLE quality_states ("
                    "identity_key TEXT PRIMARY KEY, revision INTEGER NOT NULL,"
                    "snapshot TEXT NOT NULL, mac TEXT NOT NULL)"
                )
                connection.execute("PRAGMA user_version=1")
            else:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                if version != _SCHEMA_VERSION:
                    raise LedgerUnavailable("ledger schema unsupported")
                has = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                    " AND name='quality_states'"
                ).fetchone()
                if has is None:
                    raise LedgerUnavailable("ledger schema unsupported")

    def _connect(self):
        _private_file(self.path, create=False)
        try:
            con = sqlite3.connect(self.path, timeout=3.0, isolation_level=None)
            con.execute("PRAGMA busy_timeout=3000")
            con.execute("PRAGMA synchronous=FULL")
            mode = con.execute("PRAGMA journal_mode=DELETE").fetchone()[0]
            if str(mode).lower() != "delete":
                raise LedgerUnavailable("durable journal unavailable")
            return con
        except (sqlite3.Error, OSError):
            raise LedgerUnavailable("ledger access unavailable") from None

    def _read(self, con, identity: RetryIdentity):
        key = _identity_key(identity, self.secret)
        row = con.execute(
            "SELECT revision, snapshot, mac FROM quality_states "
            "WHERE identity_key=?", (key,)
        ).fetchone()
        if row is None:
            return key, RetryState(identity)
        revision, raw, mac = row
        if (type(revision) is not int or type(mac) is not str or
                not hmac.compare_digest(mac, _snapshot_mac(key, raw, self.secret))):
            raise LedgerUnavailable("ledger snapshot invalid")
        state = _decode(raw, identity)
        if state.revision != revision:
            raise LedgerUnavailable("ledger snapshot invalid")
        return key, state

    def read(self, identity: RetryIdentity) -> RetryState:
        try:
            with self._connect() as con:
                return self._read(con, identity)[1]
        except LedgerUnavailable:
            raise
        except (sqlite3.Error, TypeError, ValueError):
            raise LedgerUnavailable("ledger read unavailable") from None

    def transition(self, identity: RetryIdentity, *, expected_revision: int,
                   operation: str, policy: RetryPolicy | None = None, **kwargs) -> RetryState:
        """Atomic synthetic transition. Caller authorization is NOT verified."""
        actions = {
            "observe_initial": observe_initial,
            "claim": claim_quality_repair,
            "finalize": finalize_quality_repair,
            "reconcile": reconcile_uncertain,
            "normalize_exhaustion": normalize_policy_exhaustion,
            "manual_reset": authorized_manual_reset,
        }
        if operation not in actions or type(expected_revision) is not int:
            raise LedgerUnavailable("ledger operation unsupported")
        if (operation in ("claim", "finalize", "reconcile", "normalize_exhaustion")
                and not isinstance(policy, RetryPolicy)):
            raise LedgerUnavailable("ledger policy required")

        con = self._connect()
        try:
            con.execute("BEGIN IMMEDIATE")
            key, current = self._read(con, identity)
            if current.revision != expected_revision:
                raise StaleRevision("stale offline ledger revision")
            opts = dict(kwargs)
            opts["expected_revision"] = expected_revision
            if operation in ("claim", "finalize", "reconcile", "normalize_exhaustion"):
                proposed = actions[operation](current, policy, **opts)
            else:
                proposed = actions[operation](current, **opts)
            if proposed.identity != identity or proposed.revision != current.revision + 1:
                raise LedgerUnavailable("ledger transition invalid")
            raw = _encode(proposed)
            if len(raw.encode("utf-8")) > _MAX_PAYLOAD:
                raise LedgerUnavailable("ledger snapshot invalid")
            mac = _snapshot_mac(key, raw, self.secret)
            if current.revision == 0:
                con.execute(
                    "INSERT INTO quality_states(identity_key,revision,snapshot,mac)"
                    " VALUES(?,?,?,?)",
                    (key, proposed.revision, raw, mac),
                )
            else:
                changed = con.execute(
                    "UPDATE quality_states SET revision=?,snapshot=?,mac=?"
                    " WHERE identity_key=? AND revision=?",
                    (proposed.revision, raw, mac, key, current.revision),
                ).rowcount
                if changed != 1:
                    raise StaleRevision("stale offline ledger revision")
            con.execute("COMMIT")
            return proposed
        except (LedgerUnavailable, StaleRevision, StateTransitionError):
            con.rollback()
            raise
        except (sqlite3.Error, OSError, ValueError, TypeError):
            con.rollback()
            raise LedgerUnavailable("ledger transaction unavailable") from None
        finally:
            con.close()
