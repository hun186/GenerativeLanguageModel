# tests/test_paths.py
import os
#import sys
import pytest
from utils.utilities_path import clean_path_end_chars
@pytest.mark.parametrize(
    "input_path, expected_parts",
    [
        # 單檔案結尾多個點
        ("file.txt...", ["file.txt"]),
        # 多層資料夾結尾多個點
        ("folder/subfolder/...file.txt...", ["folder", "subfolder", "...file.txt"]),
        # 路徑結尾多個斜線
        ("folder/subfolder///", ["folder", "subfolder"]),
        ("folder\\subfolder\\\\\\", ["folder", "subfolder"]),
        # 混合多個點和斜線
        ("folder/subfolder...\\file.txt...", ["folder", "subfolder", "file.txt"]),
        # 根目錄結尾多個斜線
        ("/", []),
        ("C:\\", ["C:"]),
        # 根目錄 + 多個點
        ("/...", []),
        ("C:\\...", ["C:"]),
    ]
)

def test_clean_path_end_dots(input_path, expected_parts):
    cleaned = clean_path_end_chars(input_path)
    # 使用 os.path.sep 斷開實際清理後的結果
    actual_parts = cleaned.split(os.path.sep)

    # 去掉空字串（如果有開頭 / 或 C:\）
    actual_parts = [p for p in actual_parts if p]

    assert actual_parts == expected_parts, f"cleaned path parts mismatch: {actual_parts} != {expected_parts}"

def test_clean_path_preserves_root():
    if os.name == "nt":
        path = "C:\\Users\\Me\\file.txt"
        cleaned = clean_path_end_chars(path)
        # Windows 開頭保持 drive
        assert cleaned.startswith("C:")
    else:
        path = "/home/user/file.txt"
        cleaned = clean_path_end_chars(path)
        # Posix 開頭保持 /
        assert cleaned.startswith(os.path.sep)
        