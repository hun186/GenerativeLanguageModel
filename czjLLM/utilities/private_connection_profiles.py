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
    """Honor explicit private paths; prefer private sibling for public paths.

    A bare filename can be supplied instead of the full config_sql/config_es path.
    No remote fetching, file mutation, or secret inspection is performed.
    """
    root = profile_directory(kind)
    requested = Path(config_path)
    candidates = [requested]
    if not requested.is_absolute():
        candidates.append(root / requested)

    for candidate in candidates:
        if candidate.is_file():
            # Do not redirect an explicitly specified /private/ file.
            if candidate.parent.name == kind:
                override = candidate.parent / "private" / candidate.name
                if override.is_file() and not override.is_symlink():
                    return override
            return candidate
    # Allow a YAML to name only a filename that exists in private/.
    if len(requested.parts) == 1:
        private = root / "private" / requested.name
        if private.is_file() and not private.is_symlink():
            return private
    raise FileNotFoundError("SQL/ES connection profile does not exist")
