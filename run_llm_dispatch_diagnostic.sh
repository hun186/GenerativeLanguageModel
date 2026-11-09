#!/usr/bin/env bash
# Local read-only metadata only.
set -uo pipefail
cd -- "$(dirname -- "$0")" || exit 2
if [[ -x .venv/bin/python ]]; then
  interpreter=.venv/bin/python
else
  interpreter=python3
fi
"$interpreter" scripts/diagnose_llm_dispatch_idle.py "$@"
