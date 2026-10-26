"""Incremental run-scoped GUI quality reader across manual JSONL rotations.

Archive generations are inspected and verified outside the Tk thread. During a
stable generation, only the growing active JSONL tail is read. A rotation or a
replacement/truncate of the active file requires rebuilding one shared
QualityAccumulator over all archived shards + the active stream. This avoids
double-counting logical events and preserves document reject->confirm recovery.

This does not make manual rotation safe while GUI/writers are running: the
existing maintenance CLI still requires all producers and GUI readers stopped.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat

from czjLLM.utilities.processing_quality import (
    QualityAccumulator, QualityCapacityExceeded, QualityTailReader,
)
from czjLLM.utilities.processing_quality_manifest import (
    manifest_path, verify_quality_manifest,
)
from czjLLM.utilities.processing_quality_rotation import quality_stream_segments


def _file_identity(path: Path) -> tuple | None:
    """Bounded metadata checks; never follow symlinks or report private names."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    if (stat.S_ISLNK(info.st_mode)
            or bool(getattr(info, "st_file_attributes", 0)
                    & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))
            or not stat.S_ISREG(info.st_mode)):
        raise ValueError("quality run path is not a regular file")
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)


class QualityRunTailReader:
    """Poll one run, incrementally; reset only on actual physical generations.

    Never poll this object from Tk. A bounded stat of each archived segment
    detects replaced shards. The expensive archive hash+replay happens only on
    initial load or when archive or ledger metadata changes.
    """

    # Conservative per-run GUI thresholds. They bound retained cardinality
    # and per-line decoding, NOT total Python RSS. Offline reporting remains
    # uncapped and is the operator path for oversized runs.
    DEFAULT_MAX_EVENTS = 50_000
    DEFAULT_MAX_IDENTITY_CHARS = 4_000_000
    DEFAULT_MAX_LINE_BYTES = 64 * 1024

    def __init__(self, path: str = "", *,
                 max_events: int = DEFAULT_MAX_EVENTS,
                 max_identity_chars: int = DEFAULT_MAX_IDENTITY_CHARS,
                 max_line_bytes: int = DEFAULT_MAX_LINE_BYTES):
        for name, value in (("max_events", max_events),
                            ("max_identity_chars", max_identity_chars),
                            ("max_line_bytes", max_line_bytes)):
            if type(value) is not int or value < 1:
                raise ValueError("invalid GUI quality budget: " + name)
        self._max_events = max_events
        self._max_identity_chars = max_identity_chars
        self._max_line_bytes = max_line_bytes
        self.path = str(path or "")
        self._archive_identity = None
        self._ledger_identity = None
        self._active_reader: QualityTailReader | None = None
        self._accumulator = self._new_accumulator()
        self._integrity = {"status": "not_applicable", "sealed_segments": 0}
        self._segments = 0
        self._archive_corrupt = 0
        self._seen_source = False
        self._active_seen = False
        # A source that already exceeds the GUI budget must not be rehashed /
        # replayed on each background poll. Cache ONLY its observed metadata
        # generation and keep raising fail-closed until something changes.
        self._capacity_generation: tuple | None = None
        # Observed filesystem history is NOT a part of the evictable capacity
        # cache: a concurrent writer can invalidate that cache mid-replay.
        # Still refuse silently shrinking known legacy archives / active file.
        self._observed_archive_count = 0
        self._observed_active_identity: tuple | None = None
        self._last_report = None

    def _new_accumulator(self) -> QualityAccumulator:
        return QualityAccumulator(
            max_events=self._max_events,
            max_identity_chars=self._max_identity_chars,
        )

    def _status_snapshot(self, *, active_incomplete: bool = False) -> dict:
        data = self._accumulator.snapshot()
        data["quality_archived_segments"] = self._segments
        data["quality_archive_integrity"] = self._integrity["status"]
        data["quality_skipped_corrupt_lines"] = (
            self._archive_corrupt +
            (self._active_reader.skipped_corrupt_lines if self._active_reader else 0)
        )
        if data["quality_skipped_corrupt_lines"]:
            data["quality_stream_status"] = "degraded_corrupt_lines"
        elif active_incomplete:
            data["quality_stream_status"] = "incomplete_tail"
        elif self._integrity["status"] == "unsealed_legacy":
            data["quality_stream_status"] = "unsealed_legacy"
        elif not self._seen_source:
            data["quality_stream_status"] = "not_initialized"
        else:
            data["quality_stream_status"] = "observed"
        return data

    def _active_replaced(self, active: Path, identity: tuple | None) -> bool:
        reader = self._active_reader
        if reader is None:
            return False
        if identity is None:
            # A previous active may have been renamed or deleted.
            return reader._file_identity is not None
        if reader._file_identity is None:
            return False
        if identity[:2] != reader._file_identity or identity[2] < reader.offset:
            return True
        try:
            with active.open("rb") as fp:
                st = os.fstat(fp.fileno())
                if (st.st_dev, st.st_ino) != identity[:2]:
                    return True
                return reader._fingerprints(fp, reader.offset) != (
                    reader._committed_head, reader._committed_tail,
                )
        except OSError:
            return True

    def _rebuild(self, active: Path, archives: list[Path],
                 archive_identity: tuple, ledger_identity: tuple | None) -> None:
        # Only replace previous metrics after *all* shard reads have succeeded;
        # an inconsistent sealed ledger must not be displayed as valid zeros.
        integrity = verify_quality_manifest(active, archives)
        acc = self._new_accumulator()
        corrupt = 0
        for shard in archives:
            reader = QualityTailReader(
                str(shard), accumulator=acc, max_line_bytes=self._max_line_bytes,
            )
            reader.poll()
            if reader.offset != shard.stat().st_size:
                raise ValueError("incomplete archived quality shard")
            corrupt += reader.skipped_corrupt_lines
        live = QualityTailReader(
            str(active), accumulator=acc, max_line_bytes=self._max_line_bytes,
        )
        if _file_identity(active) is not None:
            live.poll()
        if (tuple((p.name, _file_identity(p)) for p in archives)
                != archive_identity or
                _file_identity(manifest_path(active)) != ledger_identity):
            raise ValueError("quality archive generation changed while reading")
        if verify_quality_manifest(active, archives) != integrity:
            raise ValueError("quality archive integrity changed while reading")
        self._active_reader = live
        self._accumulator = acc
        self._archive_corrupt = corrupt
        self._integrity = integrity
        self._segments = len(archives)
        self._archive_identity = archive_identity
        self._ledger_identity = ledger_identity
        self._active_seen = _file_identity(active) is not None
        self._seen_source = bool(archives or self._active_seen)

    def poll(self) -> tuple[bool, dict]:
        """Return (changed, snapshot) with separate accuracy/identity status.

        Raise ValueError on missing/tampered sealed archives, unsafe filesystem
        state or a deleted known run. The GUI worker must render such errors
        explicitly and must never keep presenting a stale 'observed' result.
        """
        if not self.path:
            result = self._status_snapshot()
            changed = result != self._last_report
            self._last_report = result
            return changed, result
        active = Path(self.path)
        archives = quality_stream_segments(active)
        archive_identity = tuple((p.name, _file_identity(p)) for p in archives)
        # Retain the maximum known archive generation even if a capacity
        # failure's cache is invalidated by a concurrent metadata change.
        prior_archives = self._observed_archive_count
        if len(archive_identity) < prior_archives:
            raise ValueError("known quality archive shard disappeared")
        ledger_identity = _file_identity(manifest_path(active))
        active_identity = _file_identity(active)
        if self._observed_active_identity is not None and active_identity is None:
            # A known active stream may disappear only when a newly numbered
            # archive explains its rename. This matters before the *first*
            # successful rebuild: _active_reader/_active_seen may be unset.
            new_segments = archive_identity[prior_archives:]
            if not any(
                identity is not None
                and identity[:2] == self._observed_active_identity[:2]
                and identity[2] >= self._observed_active_identity[2]
                for _, identity in new_segments
            ):
                raise ValueError("known quality active stream disappeared without rotation")
            # Do not commit the acknowledged rotation just yet: an invalid
            # manifest must still be recoverable if the operator restores
            # the last known good archive layout.
        generation = (archive_identity, ledger_identity, active_identity)
        generation_changed = (
            self._active_reader is None or
            self._archive_identity != archive_identity or
            self._ledger_identity != ledger_identity
        )
        if generation == self._capacity_generation:
            # Preserve the worker's capacity_exceeded warning without another
            # O(number_of_events) replay or manifest hash on each GUI poll.
            raise QualityCapacityExceeded("quality GUI source remains over budget")
        try:
            if generation_changed or self._active_replaced(active, active_identity):
                self._rebuild(active, archives, archive_identity, ledger_identity)
            elif active_identity is not None:
                self._active_reader.poll()
                self._active_seen = True
                self._seen_source = True
                if self._active_reader.accumulator is not self._accumulator:
                    # In-flight truncate/rewrite: rebuild from all segments
                    # instead of losing previously archived document decisions.
                    self._rebuild(active, archives, archive_identity, ledger_identity)
        except QualityCapacityExceeded:
            # A capacity failure is itself evidence that these input paths
            # were present at the beginning of the attempted replay, even if
            # metadata changes later and prevents caching the retry shortcut.
            self._observed_archive_count = len(archive_identity)
            self._observed_active_identity = active_identity
            # Only memoize a FAILED attempt when archive, manifest AND active
            # metadata stayed unchanged for its duration. If a writer changed
            # them mid-replay, retry fresh rather than caching a stale failure.
            try:
                after_archives = quality_stream_segments(active)
                after_generation = (
                    tuple((p.name, _file_identity(p)) for p in after_archives),
                    _file_identity(manifest_path(active)),
                    _file_identity(active),
                )
                self._capacity_generation = (
                    generation if after_generation == generation else None
                )
            except (OSError, ValueError):
                self._capacity_generation = None
            raise
        self._capacity_generation = None
        incomplete = False
        if active_identity is not None and self._active_reader is not None:
            current = _file_identity(active)
            if current is None or current[:2] != active_identity[:2]:
                raise ValueError("quality active generation changed during polling")
            incomplete = current[2] > self._active_reader.offset
        result = self._status_snapshot(active_incomplete=incomplete)
        # Commit observed history only for a successful read or a definite
        # capacity exceed, not for an invalid manifest/symlink. Otherwise a
        # temporary corrupt extra shard would block restoration forever.
        self._observed_archive_count = len(archive_identity)
        self._observed_active_identity = active_identity
        changed = result != self._last_report
        self._last_report = result
        return changed, result
