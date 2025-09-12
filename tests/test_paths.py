# tests/test_paths.py
import sys
from czjLLM.utils.paths import clean_path_end_chars

def test_clean_path_posix_no_strip_leading_slash():
    p = "/mntCZJ/Topic/GenerativeLanguageModel/TODO/0.txt"
    assert clean_path_end_chars(p).startswith("/"), "must keep leading slash on Posix"
