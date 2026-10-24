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
    QualityAccumulator, QualityTailReader,
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

    def __init__(self, path: str = ""):
        self.path = str(path or "")
        self._archive_identity = None
        self._ledger_identity = None
        self._active_reader: QualityTailReader | None = None
        self._accumulator = QualityAccumulator()
        self._integrity = {"status": "not_applicable", "sealed_segments": 0}
        self._segments = 0
        self._archive_corrupt = 0
        self._seen_source = False
        self._active_seen = False
        self._last_report = None

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
        acc = QualityAccumulator()
        corrupt = 0
        for shard in archives:
            reader = QualityTailReader(str(shard), accumulator=acc)
            reader.poll()
            if reader.offset != shard.stat().st_size:
                raise ValueError("incomplete archived quality shard")
            corrupt += reader.skipped_corrupt_lines
        live = QualityTailReader(str(active), accumulator=acc)
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
        # An archive-only run is a valid, stable state. Only a previously
        # observed *active* generation disappearing is suspicious if no
        # corresponding archive generation change explains the rename.
        missing_known = _file_identity(active) is None and self._active_seen
        archive_identity = tuple((p.name, _file_identity(p)) for p in archives)
        ledger_identity = _file_identity(manifest_path(active))
        active_identity = _file_identity(active)
        generation_changed = (
            self._active_reader is None or
            self._archive_identity != archive_identity or
            self._ledger_identity != ledger_identity
        )
        if missing_known and not generation_changed:
            raise ValueError("known quality active stream disappeared without rotation")
        if generation_changed or self._active_replaced(active, active_identity):
            self._rebuild(active, archives, archive_identity, ledger_identity)
        elif active_identity is not None:
            self._active_reader.poll()
            self._active_seen = True
            self._seen_source = True
            if self._active_reader.accumulator is not self._accumulator:
                # An in-flight truncate/rewrite was detected by the underlying
                # tail reader. Rebuild from archives and current active instead
                # of forgetting previously archived document decisions.
                self._rebuild(active, archives, archive_identity, ledger_identity)
        incomplete = False
        if active_identity is not None and self._active_reader is not None:
            current = _file_identity(active)
            if current is None or current[:2] != active_identity[:2]:
                raise ValueError("quality active generation changed during polling")
            incomplete = current[2] > self._active_reader.offset
        result = self._status_snapshot(active_incomplete=incomplete)
        changed = result != self._last_report
        self._last_report = result
        return changed, result
