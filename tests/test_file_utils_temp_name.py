from pathlib import Path

from czjLLM.utilities.file_utils import save_text_as_temp_file


def test_save_text_as_temp_file_includes_row_key(tmp_path):
    p = save_text_as_temp_file("國科會", str(tmp_path), 1, row_key="pk:5")
    name = Path(p).name
    assert name.startswith("excel_input_1_pk_5_")
    assert name.endswith(".txt")
