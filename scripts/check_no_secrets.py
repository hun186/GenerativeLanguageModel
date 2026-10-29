#!/usr/bin/env python3
"""Reject new plaintext credentials in staged changes or a Git commit range.

This is a changed-lines gate, NOT a complete historical repository audit.
"""
import argparse
import re
import subprocess
import sys

KEY = re.compile(r"(?<![A-Za-z0-9])" + "sk" + r"-[A-Za-z0-9_-]{20,}")
PRIVATE_KEY = re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----")
LITERAL = re.compile(
    r"""\b(?:password|api[_-]?key|access[_-]?token|secret|auth[_-]?token)\s*=\s*(['"])([^'"]{6,})\1""",
    re.I,
)
PLACEHOLDER = re.compile(r"^(?:example|sample|placeholder|redacted|dummy|changeme|your[_-])", re.I)


def detect(line):
    if KEY.search(line):
        return "literal key-style token"
    if PRIVATE_KEY.search(line):
        return "private key"
    match = LITERAL.search(line)
    if match and not PLACEHOLDER.search(match.group(2)):
        return "quoted credential assignment"
    return None


def added_lines(diff):
    filename = "unknown"
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            filename = line[6:]
        elif line.startswith("+") and not line.startswith("+++"):
            yield filename, line[1:]


def main(argv=None):
    parser = argparse.ArgumentParser()
    option = parser.add_mutually_exclusive_group(required=True)
    option.add_argument("--staged", action="store_true")
    option.add_argument("--base")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    command = ["git", "diff", "--no-ext-diff", "--unified=0"]
    command.extend(["--cached"] if args.staged else [args.base, args.head])
    command.append("--")
    try:
        diff = subprocess.run(command, capture_output=True, text=True, check=True).stdout
    except subprocess.CalledProcessError:
        print("Unable to inspect Git changes; denying secret scan.", file=sys.stderr)
        return 2
    results = [(name, issue) for name, line in added_lines(diff) if (issue := detect(line))]
    for name, issue in results:
        print(f"Potential credential in added line of {name}: {issue}; content withheld.", file=sys.stderr)
    if results:
        return 1
    print("Changed-line secret scan PASS; historical audit remains outstanding.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
