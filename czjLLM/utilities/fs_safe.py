# czjLLM/utils/fs_safe.py

from __future__ import annotations

import gc
import os
import shutil
import threading
import time
from pathlib import Path
from typing import Callable, TypeVar


T = TypeVar("T")

WINDOWS_RETRYABLE_ERRORS = {
    5,    # Access denied
    32,   # Sharing violation
    33,   # Lock violation
    145,  # Directory not empty
}


def extended_path(path: str | os.PathLike) -> str:
    """
    將一般路徑轉換為 Windows extended-length path。

    Windows:
        D:\\folder\\file
        -> \\\\?\\D:\\folder\\file

    非 Windows:
        回傳絕對路徑。
    """
    raw = os.path.abspath(os.fspath(path))

    if os.name != "nt":
        return raw

    raw = raw.replace("/", "\\")

    if raw.startswith("\\\\?\\"):
        return raw

    if raw.startswith("\\\\"):
        return "\\\\?\\UNC\\" + raw[2:]

    return "\\\\?\\" + raw


def path_diagnostic(
    label: str,
    path: str | os.PathLike,
) -> str:
    try:
        normal_path = os.path.abspath(os.fspath(path))
        access_path = extended_path(normal_path)

        return (
            f"{label}={normal_path!r}, "
            f"length={len(normal_path)}, "
            f"exists={os.path.exists(access_path)}, "
            f"is_file={os.path.isfile(access_path)}, "
            f"is_dir={os.path.isdir(access_path)}"
        )

    except Exception as ex:
        return (
            f"{label}={path!r}, "
            f"diagnostic_error={ex!r}"
        )


def retry_fs(
    operation: Callable[[], T],
    *,
    description: str,
    retries: int = 30,
    delay: float = 0.2,
    logger: Callable[[str], None] | None = None,
) -> T:
    """
    重試 Windows 短暫性的檔案鎖定錯誤。

    非 Windows 平台直接執行一次。
    """
    if os.name != "nt":
        return operation()

    last_error: OSError | None = None

    for attempt in range(1, retries + 1):
        try:
            return operation()

        except FileNotFoundError:
            raise

        except OSError as ex:
            last_error = ex
            winerror = getattr(ex, "winerror", None)

            retryable = (
                isinstance(ex, PermissionError)
                or winerror in WINDOWS_RETRYABLE_ERRORS
            )

            if not retryable:
                raise

            if logger is not None:
                logger(
                    "[windows-fs-retry] "
                    f"description={description}, "
                    f"attempt={attempt}/{retries}, "
                    f"winerror={winerror}, "
                    f"error={ex!r}"
                )

            if attempt >= retries:
                break

            gc.collect()
            time.sleep(delay)

    if last_error is None:
        raise RuntimeError(
            f"檔案操作失敗，但沒有取得例外：{description}"
        )

    raise last_error


def safe_read_text(
    path: str | os.PathLike,
    *,
    encoding: str = "utf-8",
    logger: Callable[[str], None] | None = None,
) -> str:
    access_path = extended_path(path)

    def operation() -> str:
        with open(access_path, "r", encoding=encoding) as fp:
            return fp.read()

    return retry_fs(
        operation,
        description=f"read_text path={os.fspath(path)!r}",
        logger=logger,
    )


def safe_mkdir(
    path: str | os.PathLike,
    *,
    logger: Callable[[str], None] | None = None,
) -> None:
    access_path = extended_path(path)

    retry_fs(
        lambda: os.makedirs(access_path, exist_ok=True),
        description=f"mkdir path={os.fspath(path)!r}",
        logger=logger,
    )


def safe_atomic_write_text(
    path: str | os.PathLike,
    text: str,
    *,
    encoding: str = "utf-8",
    logger: Callable[[str], None] | None = None,
) -> None:
    """
    先寫入同目錄暫存檔，再使用 os.replace 原子替換。

    可避免程式中止時留下只寫一半的正式輸出檔。
    """
    target_path = Path(path)

    safe_mkdir(
        target_path.parent,
        logger=logger,
    )

    temp_name = (
        f".{target_path.name}."
        f"{os.getpid()}."
        f"{threading.get_ident()}."
        "tmp"
    )

    temp_path = target_path.with_name(temp_name)

    long_temp = extended_path(temp_path)
    long_target = extended_path(target_path)

    try:
        def write_temp() -> None:
            with open(long_temp, "w", encoding=encoding) as fp:
                fp.write(text)
                fp.flush()

                try:
                    os.fsync(fp.fileno())
                except OSError:
                    # 網路磁碟或部分檔案系統可能不支援。
                    pass

        retry_fs(
            write_temp,
            description=f"write temp path={str(temp_path)!r}",
            logger=logger,
        )

        retry_fs(
            lambda: os.replace(long_temp, long_target),
            description=(
                f"replace temp={str(temp_path)!r}, "
                f"target={str(target_path)!r}"
            ),
            logger=logger,
        )

    finally:
        try:
            if os.path.exists(long_temp):
                os.remove(long_temp)
        except OSError:
            pass


def safe_rmtree(
    path: str | os.PathLike,
    *,
    retries: int = 30,
    delay: float = 0.2,
    logger: Callable[[str], None] | None = None,
    raise_on_failure: bool = False,
) -> bool:
    """
    嘗試刪除目錄。

    預設刪除失敗只回傳 False，不影響主要處理結果。
    """
    access_path = extended_path(path)

    for attempt in range(1, retries + 1):
        try:
            if not os.path.exists(access_path):
                return True

            shutil.rmtree(access_path)
            return True

        except FileNotFoundError:
            return True

        except OSError as ex:
            winerror = getattr(ex, "winerror", None)

            retryable = (
                isinstance(ex, PermissionError)
                or winerror in WINDOWS_RETRYABLE_ERRORS
            )

            if logger is not None:
                logger(
                    "[rmtree-retry] "
                    f"path={os.fspath(path)!r}, "
                    f"attempt={attempt}/{retries}, "
                    f"winerror={winerror}, "
                    f"retryable={retryable}, "
                    f"error={ex!r}"
                )

            if not retryable:
                if raise_on_failure:
                    raise
                return False

            if attempt < retries:
                gc.collect()
                time.sleep(delay)

    if raise_on_failure:
        raise PermissionError(
            f"無法刪除工作目錄：{os.fspath(path)}"
        )

    return False