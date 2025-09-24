# tests/conftest.py
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # 專案根目錄
load_dotenv(ROOT / "LLM_API.env", override=True, encoding="utf-8")
