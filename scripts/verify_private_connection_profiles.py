#!/usr/bin/env python3
"""Read-only, value-free readiness check for restored private SQL/ES profiles.

Never executes Python profiles, prints credentials, connects to a database,
copies files or modifies Git. Syntactic readiness is NOT a live login test.
"""
from __future__ import annotations

import argparse
import ast
import os
from pathlib import Path
import subprocess

KINDS = {"sql": "config_sql", "es": "config_es"}
EXTENSIONS = {".py", ".yaml", ".yml"}
LIMIT_BYTES = 1024 * 1024
REQUIRED = {"sql": ("server", "username", "password", "database_name", "table_name"),
            "es": ("es_user", "es_pass", "es_index")}
HOST_FIELDS = ("es_host", "hosts")


def _git_ok(root: Path, args: list[str]) -> bool:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, check=False,
        stdin=subprocess.DEVNULL,
    )
    return result.returncode == 0


def _check_python(path: Path, kind: str) -> list[str]:
    """Parse syntax and field presence only; do not evaluate or print values."""
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename="<private profile>")
    except (OSError, UnicodeError, SyntaxError, ValueError):
        return ["INVALID_PYTHON_SYNTAX"]
    fields = {}
    for stmt in tree.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    fields[target.id] = stmt.value
        elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            fields[stmt.target.id] = stmt.value
    missing = [field for field in REQUIRED[kind] if field not in fields]
    if kind == "es" and not any(field in fields for field in HOST_FIELDS):
        missing.append("es_host_or_hosts")
    issues = ["MISSING_FIELD:" + field for field in missing]
    for name in REQUIRED[kind] + (HOST_FIELDS if kind == "es" else ()):
        if name not in fields:
            continue
        expr = fields[name]
        if isinstance(expr, ast.Constant) and (
            expr.value is None or isinstance(expr.value, str) and not expr.value.strip()
        ):
            issues.append("EMPTY_FIELD:" + name)
        elif isinstance(expr, (ast.List, ast.Tuple)) and not expr.elts:
            issues.append("EMPTY_FIELD:" + name)
    return issues


def check_one(root: Path, path: Path, kind: str) -> list[str]:
    """Return only safe finding codes, never values, paths or secrets."""
    issues = []
    private = root / "czjLLM" / KINDS[kind] / "private"
    if private.is_symlink() or path.is_symlink():
        return ["SYMLINK_NOT_ALLOWED"]
    if not path.is_file():
        return ["FILE_MISSING"]
    if path.suffix.lower() not in EXTENSIONS:
        return ["UNSUPPORTED_EXTENSION"]
    try:
        # Avoid following hardlinks to a shared sensitive file.
        stat = path.stat()
        if stat.st_nlink != 1:
            return ["HARDLINK_NOT_ALLOWED"]
        if stat.st_size == 0 or stat.st_size > LIMIT_BYTES:
            return ["INVALID_FILE_SIZE"]
        relative = path.relative_to(root)
    except (OSError, ValueError):
        return ["UNSAFE_PATH"]
    if not _git_ok(root, ["check-ignore", "--no-index", "--quiet", "--", str(relative)]):
        issues.append("NOT_IGNORED")
    if _git_ok(root, ["ls-files", "--error-unmatch", "--", str(relative)]):
        issues.append("STILL_TRACKED")
    if path.suffix.lower() == ".py":
        issues += _check_python(path, kind)
    # YAML is checked only for location and Git hygiene; not parsed or executed.
    return issues


def inspect(root: Path, *, kind: str = "both", profile: str | None = None):
    """Return non-sensitive summary and errors; no mutation or network access."""
    root = root.resolve()
    if not _git_ok(root, ["rev-parse", "--is-inside-work-tree"]):
        return {}, ["NOT_A_GIT_WORKTREE"]
    if profile is not None and (
        kind == "both" or Path(profile).name != profile or profile in {"", ".", ".."}
    ):
        return {}, ["INVALID_PROFILE_SELECTION"]
    summaries = {}
    failures = []
    kinds = ("sql", "es") if kind == "both" else (kind,)
    for one_kind in kinds:
        directory = root / "czjLLM" / KINDS[one_kind] / "private"
        if directory.is_symlink():
            failures.append(one_kind + ":PRIVATE_DIRECTORY_SYMLINK")
            summaries[one_kind] = {"profiles": 0, "checked": 0, "yaml_manual": 0}
            continue
        if profile is not None:
            paths = [directory / profile]
        elif directory.is_dir():
            paths = sorted(x for x in directory.iterdir() if x.suffix.lower() in EXTENSIONS)
        else:
            paths = []
        summary = {"profiles": len(paths), "checked": 0, "yaml_manual": 0}
        if not paths:
            failures.append(one_kind + ":NO_PRIVATE_PROFILE")
        for idx, path in enumerate(paths, 1):
            # Index is ordinal; avoid exposing host, account or sensitive path.
            errors = check_one(root, path, one_kind)
            if errors:
                failures.extend(one_kind + ":PROFILE_" + str(idx) + ":" + e for e in errors)
            else:
                summary["checked"] += 1
                if path.suffix.lower() in {".yml", ".yaml"}:
                    summary["yaml_manual"] += 1
        summaries[one_kind] = summary
    return summaries, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]),
                        help="Local checkout root (not a URL)")
    parser.add_argument("--kind", choices=("both", "sql", "es"), default="both")
    parser.add_argument("--profile", help="One .py/.yaml/.yml basename; requires --kind")
    args = parser.parse_args()
    try:
        report, errors = inspect(Path(args.root), kind=args.kind, profile=args.profile)
    except (OSError, ValueError):
        report, errors = {}, ["LOCAL_INSPECTION_ERROR"]
    for kind, summary in report.items():
        print(kind.upper() + ": " + str(summary["checked"]) + "/" +
              str(summary["profiles"]) + " profiles passed structural/ignore checks; " +
              str(summary["yaml_manual"]) + " YAML profiles need manual field inspection")
    for code in errors:
        print("BLOCKED:", code)
    print("No connection made. No credential values read into logs or executed.")
    print("Successful checks do NOT verify account validity, TLS, or actual SQL/ES login.")
    return 2 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
