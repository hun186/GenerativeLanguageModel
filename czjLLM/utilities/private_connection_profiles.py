"""Discover SQL/ES profiles alongside ignored private, complete connection files.

Existing YAML/root profile paths continue working: if a private file with the
same basename exists next to a public example, the private file wins.
No actual credentials are created, copied, logged or committed by this module.
"""
from __future__ import annotations

from pathlib import Path

KINDS = {"config_sql", "config_es"}
EXTENSIONS = {".py", ".yaml", ".yml"}


def profile_directory(kind: str) -> Path:
    if kind not in KINDS:
        raise ValueError("Unsupported connection profile kind")
    return Path(__file__).resolve().parents[1] / kind


def profile_options(directory: str | Path) -> dict[str, str]:
    """Enumerate public examples and one-level private files for UI selection."""
    root = Path(directory)
    private = root / "private"
    public_files = {
        p.name: p for p in root.iterdir()
        if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.is_symlink()
    } if root.is_dir() else {}
    private_files = {
        p.name: p for p in private.iterdir()
        if p.is_file() and p.suffix.lower() in EXTENSIONS and not p.is_symlink()
    } if private.is_dir() else {}

    # A private profile with the same filename supersedes its tracked example.
    result = {
        name: str(path)
        for name, path in sorted(public_files.items())
        if name not in private_files
    }
    result.update({
        "private/" + name: str(path)
        for name, path in sorted(private_files.items())
    })
    return result


def resolve_profile_path(config_path: str | Path, kind: str) -> Path:
    """Resolve public or private paths, even when the public file was untracked.

    Recognizes legacy root paths in existing job YAML and a bare filename.
    Explicit private paths must exist; they never fall back to another file.
    """
    root = profile_directory(kind)
    requested = Path(config_path)
    candidates = [requested]
    if not requested.is_absolute():
        candidates.append(root / requested)

    # An existing public profile may be shadowed by its ignored private twin.
    for candidate in candidates:
        if candidate.is_file():
            if candidate.is_symlink():
                raise ValueError("Connection profile symlinks are not supported")
            if candidate.parent.name == kind:
                override = candidate.parent / "private" / candidate.name
                if override.is_file() and not override.is_symlink():
                    return override
            return candidate

    # Historical YAML may name config_sql/<file>.py or
    # czjLLM/config_es/<file>.py; that root file might now be untracked.
    # Require the immediate parent of the missing file to match its kind.
    if len(requested.parts) == 1 or requested.parent.name == kind:
        if requested.parent.name == kind and requested.is_absolute():
            private = requested.parent / "private" / requested.name
        else:
            private = root / "private" / requested.name
        if private.is_file() and not private.is_symlink():
            return private
    raise FileNotFoundError(
        "SQL/ES connection profile not found. Copy the complete configuration "
        "into config_sql/private/ or config_es/private/ before starting this job."
    )
