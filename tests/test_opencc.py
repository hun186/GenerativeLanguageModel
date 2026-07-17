import inspect
import os
import sys
import threading
import traceback

import opencc
from opencc import OpenCC


TEST_TEXT = "无主题相关内容：這是一段測試文字"


def same_code_as_combine():
    print(
        "\n[TEST-START]\n"
        f"pid={os.getpid()}\n"
        f"thread={threading.current_thread().name}\n"
        f"python={sys.executable}\n"
        f"opencc_module={opencc.__file__}\n"
        f"OpenCC_class={inspect.getfile(OpenCC)}",
        flush=True,
    )

    print("[1] before OpenCC('s2twp')", flush=True)

    converter = OpenCC("s2twp")

    print("[2] after OpenCC('s2twp')", flush=True)

    converted = converter.convert(TEST_TEXT.lstrip())

    print(
        "[3] after convert\n"
        f"input={TEST_TEXT!r}\n"
        f"output={converted!r}\n"
        f"starts_with={converted.startswith('無主題相關內容')}",
        flush=True,
    )


def thread_target():
    try:
        same_code_as_combine()
    except BaseException as ex:
        print(
            "\n[PYTHON-EXCEPTION]\n"
            f"type={type(ex).__module__}.{type(ex).__qualname__}\n"
            f"repr={ex!r}\n"
            f"{traceback.format_exc()}",
            flush=True,
        )
        raise


if __name__ == "__main__":
    print("=== 主執行緒測試 ===", flush=True)
    same_code_as_combine()

    print("\n=== 背景執行緒測試 ===", flush=True)

    thread = threading.Thread(
        target=thread_target,
        name="row_merger_watchdog_generic-test",
    )
    thread.start()
    thread.join()

    print("\nALL TESTS COMPLETED", flush=True)