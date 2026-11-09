#!/usr/bin/env bash
# Run only disposable, offline local Linux Queue fixture checks.
# Invoke with: bash run_linux_queue_local_acceptance.sh
set -uo pipefail
if [[ "$#" -ne 0 ]]; then
  echo "REVIEW_REQUIRED: UNSUPPORTED_ARGUMENTS"
  exit 2
fi
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || {
  echo "REVIEW_REQUIRED: REPO_UNAVAILABLE"
  exit 2
}
if [[ -x ".venv/bin/python" ]]; then
  PROBE_PY=".venv/bin/python"
else
  PROBE_PY="python3"
fi
if ! command -v "$PROBE_PY" >/dev/null 2>&1; then
  echo "REVIEW_REQUIRED: PYTHON_UNAVAILABLE"
  exit 2
fi
"$PROBE_PY" "scripts/verify_linux_queue_local.py"
status=$?
if [[ "$status" -ne 0 ]]; then
  echo "REVIEW_REQUIRED: see private queue-linux-acceptance-results report in HOME"
fi
exit "$status"
