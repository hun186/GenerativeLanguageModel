"""Import-boundary regressions for the inactive Reduction package."""

import subprocess
import sys
from pathlib import Path


def test_reduction_import_preserves_utility_export_without_loading_combine_utils():
    repo_root = Path(__file__).resolve().parents[2]
    check = """
import sys

from czjLLM.utilities import merge_dict_slices
from czjLLM.utilities.slice_merge import merge_dict_slices as direct

assert merge_dict_slices is direct
assert "czjLLM.utilities.combine_utils" not in sys.modules

import czjLLM.reduction

assert "czjLLM.utilities.combine_utils" not in sys.modules
"""

    completed = subprocess.run(
        [sys.executable, "-c", check],
        cwd=repo_root,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
