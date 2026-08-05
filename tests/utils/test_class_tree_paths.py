from pathlib import Path

import pytest

from utils.class_tree_paths import resolve_class_tree_file, resolve_class_tree_files


def test_resolve_class_tree_file_prefers_explicit_root(tmp_path):
    class_tree_root = tmp_path / "class_trees"
    class_tree_root.mkdir()
    topic_tree = class_tree_root / "TopicTree.csv"
    topic_tree.write_text("parent,child,weight\n", encoding="utf-8")

    assert resolve_class_tree_file("TopicTree.csv", class_tree_root=class_tree_root) == str(topic_tree)


def test_resolve_class_tree_file_lists_searched_paths(tmp_path, monkeypatch):
    monkeypatch.delenv("CLASS_TREE_ROOT", raising=False)

    with pytest.raises(FileNotFoundError) as excinfo:
        resolve_class_tree_file("MissingTree.csv", class_tree_root=tmp_path / "missing")

    message = str(excinfo.value)
    assert "Searched paths:" in message
    assert str(tmp_path / "missing" / "MissingTree.csv") in message
    assert "config/class_trees/default/MissingTree.csv" in message
    assert "../TACA/DB/ZMRAND/Imported/MissingTree.csv" in message


def test_resolve_class_tree_files_preserves_order(tmp_path):
    for filename in ["TopicTree.csv", "TopicTree_AK4.csv"]:
        Path(tmp_path, filename).write_text("parent,child,weight\n", encoding="utf-8")

    assert resolve_class_tree_files(class_tree_root=tmp_path) == [
        str(tmp_path / "TopicTree.csv"),
        str(tmp_path / "TopicTree_AK4.csv"),
    ]
