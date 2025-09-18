import os
from czjLLM.utilities import path_utils, logging_utils

def test_project_root_exists():
    root = path_utils.init_project_root()
    assert os.path.exists(root), "Project root should exist"

def test_logging_utils(tmp_path):
    log_file = tmp_path / "test.log"
    logger = logging_utils.get_logger("test", log_file)
    logger.info("Hello World")
    with open(log_file, "r") as f:
        content = f.read()
    assert "Hello World" in content
