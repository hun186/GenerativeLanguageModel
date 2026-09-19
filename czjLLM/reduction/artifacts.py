"""Strict, atomic completed-round checkpoints for hierarchical reduction."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple

from czjLLM.utilities.atomic_io import atomic_write_json
from czjLLM.utilities.fs_safe import safe_atomic_write_text, safe_read_text


CHECKPOINT_CONTRACT_VERSION = "1"


class ReductionCheckpointError(RuntimeError):
    """Base class for checkpoint failures."""


class CheckpointCorruptionError(ReductionCheckpointError):
    """A committed checkpoint or its payload is malformed or inconsistent."""


class CheckpointCompatibilityError(ReductionCheckpointError):
    """Checkpoint metadata does not describe the requested run contract."""


def text_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def text_sequence_fingerprint(items: Sequence[str]) -> str:
    digest = hashlib.sha256()
    digest.update(len(items).to_bytes(8, "big"))
    for item in items:
        encoded = item.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def normalized_fingerprint(value: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def derive_run_key(initial_input_fingerprint: str, policy_fingerprint: str) -> str:
    return normalized_fingerprint(
        {
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "initial_input_fingerprint": initial_input_fingerprint,
            "policy_fingerprint": policy_fingerprint,
        }
    )


@dataclass(frozen=True)
class ResumeState:
    round_index: int
    payload: str
    output_fingerprint: str
    terminal_stop_reason: Optional[str]
    metrics: Tuple[Mapping[str, Any], ...]


class CheckpointStore:
    """Persist and strictly validate completed rounds for one deterministic run."""

    def __init__(
        self,
        root: str | Path,
        *,
        run_key: str,
        controller: str,
        profile: str,
        reducer_contract_version: str,
        policy_fingerprint: str,
        initial_input_fingerprint: str,
    ) -> None:
        self.root = Path(root)
        self.run_key = run_key
        self.run_dir = self.root / run_key
        self.expected = {
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "run_key": run_key,
            "controller": controller,
            "profile": profile,
            "reducer_contract_version": reducer_contract_version,
            "policy_fingerprint": policy_fingerprint,
            "initial_input_fingerprint": initial_input_fingerprint,
        }

    @property
    def manifest_path(self) -> Path:
        return self.run_dir / "run.json"

    def initialize(self) -> None:
        if self.manifest_path.exists():
            manifest = self._read_json(self.manifest_path)
            self._validate_compatibility(manifest, "run manifest")
            return
        atomic_write_json(str(self.manifest_path), self.expected)

    @staticmethod
    def _read_json(path: Path) -> Mapping[str, Any]:
        try:
            with path.open("r", encoding="utf-8") as stream:
                value = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CheckpointCorruptionError(
                f"Cannot read checkpoint metadata {path}: {exc}"
            ) from exc
        if not isinstance(value, dict):
            raise CheckpointCorruptionError(
                f"Checkpoint metadata must be an object: {path}"
            )
        return value

    def _validate_compatibility(self, value: Mapping[str, Any], label: str) -> None:
        for key, expected in self.expected.items():
            if value.get(key) != expected:
                raise CheckpointCompatibilityError(
                    f"Incompatible {label}: {key} expected {expected!r}, "
                    f"found {value.get(key)!r}"
                )

    def commit_round(
        self,
        *,
        round_index: int,
        payload: str,
        parent_output_fingerprint: Optional[str],
        reducer_input_fingerprint: str,
        metrics: Mapping[str, Any],
        terminal_stop_reason: Optional[str],
    ) -> None:
        payload_name = f"round-{round_index:04d}.payload.txt"
        checkpoint_path = self.run_dir / f"round-{round_index:04d}.json"
        payload_path = self.run_dir / payload_name
        # The JSON written last is the sole completed-round commit marker.
        safe_atomic_write_text(payload_path, payload)
        output_fingerprint = text_fingerprint(payload)
        checkpoint = {
            **self.expected,
            "round_id": f"round-{round_index:04d}",
            "round_index": round_index,
            "parent_output_fingerprint": parent_output_fingerprint,
            "reducer_input_fingerprint": reducer_input_fingerprint,
            "output_fingerprint": output_fingerprint,
            "payload_artifact": payload_name,
            "metrics": dict(metrics),
            "status": "completed",
            "terminal_stop_reason": terminal_stop_reason,
        }
        atomic_write_json(str(checkpoint_path), checkpoint)

    def load_highest_completed(self) -> Optional[ResumeState]:
        self.initialize()
        checkpoints = sorted(self.run_dir.glob("round-*.json"))
        previous_fingerprint: Optional[str] = None
        state: Optional[ResumeState] = None
        metrics_history = []
        for expected_index, path in enumerate(checkpoints, start=1):
            data = self._read_json(path)
            self._validate_compatibility(data, f"round checkpoint {path.name}")
            if data.get("status") != "completed":
                raise CheckpointCorruptionError(
                    f"Checkpoint is not completed: {path}"
                )
            if data.get("round_index") != expected_index:
                raise CheckpointCorruptionError(
                    f"Checkpoint rounds are not contiguous at {path.name}"
                )
            expected_round_id = f"round-{expected_index:04d}"
            if path.name != f"{expected_round_id}.json" or data.get(
                "round_id"
            ) != expected_round_id:
                raise CheckpointCorruptionError(
                    f"Checkpoint round identity mismatch at {path.name}"
                )
            reducer_input_fingerprint = data.get("reducer_input_fingerprint")
            if (
                not isinstance(reducer_input_fingerprint, str)
                or len(reducer_input_fingerprint) != 64
            ):
                raise CheckpointCorruptionError(
                    f"Invalid reducer input fingerprint in {path.name}"
                )
            if expected_index == 1 and reducer_input_fingerprint != self.expected[
                "initial_input_fingerprint"
            ]:
                raise CheckpointCorruptionError(
                    f"Initial reducer input fingerprint mismatch in {path.name}"
                )
            if data.get("parent_output_fingerprint") != previous_fingerprint:
                raise CheckpointCorruptionError(
                    f"Broken checkpoint parent chain at {path.name}"
                )
            payload_name = data.get("payload_artifact")
            if not isinstance(payload_name, str) or Path(payload_name).name != payload_name:
                raise CheckpointCorruptionError(
                    f"Invalid payload artifact in {path.name}"
                )
            payload_path = self.run_dir / payload_name
            try:
                payload = safe_read_text(payload_path)
            except (OSError, UnicodeError) as exc:
                raise CheckpointCorruptionError(
                    f"Missing or unreadable payload for {path.name}: {payload_path}"
                ) from exc
            actual_fingerprint = text_fingerprint(payload)
            if data.get("output_fingerprint") != actual_fingerprint:
                raise CheckpointCorruptionError(
                    f"Payload fingerprint mismatch for {path.name}"
                )
            previous_fingerprint = actual_fingerprint
            terminal = data.get("terminal_stop_reason")
            if terminal is not None and not isinstance(terminal, str):
                raise CheckpointCorruptionError(
                    f"Invalid terminal stop reason in {path.name}"
                )
            if state is not None and state.terminal_stop_reason is not None:
                raise CheckpointCorruptionError(
                    f"Checkpoint exists after terminal round: {path.name}"
                )
            metrics = data.get("metrics")
            if not isinstance(metrics, dict):
                raise CheckpointCorruptionError(
                    f"Invalid round metrics in {path.name}"
                )
            metrics_history.append(metrics)
            state = ResumeState(
                expected_index,
                payload,
                actual_fingerprint,
                terminal,
                tuple(metrics_history),
            )
        return state
