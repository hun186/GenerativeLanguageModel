"""Print aggregate GLM MultiDim search-field capabilities from GitHub templates."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from czjLLM.common.multidim_search_field_capabilities import inspect_checked_in_template


if __name__ == "__main__":
    print(json.dumps(inspect_checked_in_template(), ensure_ascii=False, sort_keys=True))
