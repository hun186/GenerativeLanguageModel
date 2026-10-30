#!/usr/bin/env python3
"""Copy operator-owned SQL/ES connection files to ignored private folders.

Run this on the workstation BEFORE updating/pulling the release that untracks
public-root config files. Default is DRY RUN; --apply writes private copies.
Never reads historical Git blobs, never prints/commits password values and
never deletes the original or overwrites a private destination.
"""
from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

SQL_NAMES = (
    "akconfig_test.py",
    "akconfig_test_to_excel.py",
    "akconfig_test_SRP.py",
    "akconfig_test_SRP - 複製.py",
)
ES_NAMES = (
    "akconfig_es_fishing.py",
    "akconfig_es_test.py",
    "akconfig_es_test_133.py",
    "akconfig_es_test_mil.py",
    "akconfig_es_test_nav_intel_sentences_133.py",
    "akconfig_es_test_satmeta_133.py",
    "akconfig_es_test_srp_133.py",
)


def file_digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def is_ignored(repo_root: Path, target: Path) -> bool:
    rel = target.relative_to(repo_root)
    p = subprocess.run(
        ["git", "check-ignore", "--no-index", "--quiet", "--", str(rel)],
        cwd=repo_root, capture_output=True, check=False,
    )
    return p.returncode == 0


def migrate(repo_root: Path, *, apply: bool) -> dict[str, int]:
    repo_root = repo_root.resolve()
    if not (repo_root / ".gitignore").is_file():
        raise RuntimeError("Expected a repository root containing .gitignore")
    summary = {"copied": 0, "would_copy": 0, "already_exists": 0, "source_missing": 0}
    for kind, names in (("config_sql", SQL_NAMES), ("config_es", ES_NAMES)):
        source_dir = repo_root / "czjLLM" / kind
        private_dir = source_dir / "private"
        if private_dir.is_symlink():
            raise RuntimeError("Private profile directory cannot be a symlink")
        for name in names:
            src, dst = source_dir / name, private_dir / name
            if src.is_symlink() or dst.is_symlink():
                raise RuntimeError("Connection profile symlinks are not supported")
            if not src.is_file():
                summary["source_missing"] += 1
                continue
            if not is_ignored(repo_root, dst):
                raise RuntimeError("Private destination is not Git ignored; refusing to copy")
            if dst.exists():
                if not dst.is_file():
                    raise RuntimeError("Private connection destination is not a regular file")
                # Never overwrite: the private version may already contain newer values.
                summary["already_exists"] += 1
                continue
            if not apply:
                summary["would_copy"] += 1
                continue
            private_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
            temp = None
            try:
                with tempfile.NamedTemporaryFile(dir=private_dir, prefix=".migrate-",
                                                 delete=False) as out:
                    temp = Path(out.name)
                    os.chmod(temp, 0o600)
                    with src.open("rb") as inp:
                        shutil.copyfileobj(inp, out)
                    out.flush()
                    os.fsync(out.fileno())
                if file_digest(src) != file_digest(temp):
                    raise RuntimeError("Private profile copy verification failed")
                # Existing destinations are never replaced, including on reruns.
                if dst.exists():
                    raise RuntimeError("Private destination appeared during copy")
                os.replace(temp, dst)
                temp = None
                summary["copied"] += 1
            finally:
                if temp is not None:
                    temp.unlink(missing_ok=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]),
                        help="Path to checked-out repository root")
    parser.add_argument("--apply", action="store_true",
                        help="Copy into ignored private dirs (never remove originals)")
    args = parser.parse_args()
    try:
        result = migrate(Path(args.root), apply=args.apply)
    except (OSError, RuntimeError) as exc:
        # Avoid logging exception internals, source content, or password-bearing paths.
        print("Migration blocked: verify Git ignore rules and local file permissions.")
        return 2
    print("Migration mode:", "COPY" if args.apply else "DRY RUN")
    for key, count in result.items():
        print(key + ":", count)
    print("Original tracked files were NOT deleted. Update source only after verifying private copies.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
