from __future__ import annotations

import os
from pathlib import Path

from dotenv import dotenv_values

_ENV_FILE_LOADED = False


def czjllm_env_file_priority(base_dir: str | None = None) -> list[Path]:
    """
    由低到高優先序（後者可覆蓋前者）：
    1) .env
    2) .env.<CZJLLM_ENV>
    3) .env.local
    """
    root = Path(base_dir or os.getcwd())
    env_name = str(os.getenv("CZJLLM_ENV", "")).strip()
    files: list[Path] = [root / ".env"]
    if env_name:
        files.append(root / f".env.{env_name}")
    files.append(root / ".env.local")
    return files


def load_czjllm_env_files_once(base_dir: str | None = None) -> None:
    """
    將 env 檔內容載入 os.environ（僅補缺，不覆蓋既有環境變數）：
    - 檔案優先序：.env < .env.<CZJLLM_ENV> < .env.local
    - 系統/命令列 export 的環境變數最高優先，永不被覆蓋
    """
    global _ENV_FILE_LOADED
    if _ENV_FILE_LOADED:
        return
    protected_keys = set(os.environ.keys())
    for env_fp in czjllm_env_file_priority(base_dir=base_dir):
        if not env_fp.is_file():
            continue
        for key, value in dotenv_values(env_fp).items():
            if not key or value is None:
                continue
            k = str(key)
            if k in protected_keys:
                continue
            os.environ[k] = str(value)
    _ENV_FILE_LOADED = True


def env_bool(name: str) -> bool | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    val = str(raw).strip().lower()
    if val in {"1", "true", "yes", "on"}:
        return True
    if val in {"0", "false", "no", "off"}:
        return False
    return None


def env_int(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except Exception:
        return None

