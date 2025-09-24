from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]  # 專案根
env_file = ROOT / "LLM_API.env"
load_dotenv(env_file, override=False)
