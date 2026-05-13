# tests/conftest.py
from pathlib import Path
from importlib.util import find_spec
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))  # 專案根目錄

if find_spec("dotenv") is not None:
    from dotenv import load_dotenv

    load_dotenv(ROOT / "LLM_API.env", override=True, encoding="utf-8")
