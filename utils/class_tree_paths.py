import os
from pathlib import Path


DEFAULT_CLASS_TREE_FILENAMES = (
    "TopicTree.csv",
    "TopicTree_AK4.csv",
)

DEFAULT_RESTRICTED_CLASS_TREE_FILENAME = "TopicTree_PAK.txt"
PROJECT_CLASS_TREE_ROOT = Path("config") / "class_trees" / "default"
LEGACY_TACA_CLASS_TREE_ROOT = Path("..") / "TACA" / "DB" / "ZMRAND" / "Imported"
ENV_CLASS_TREE_ROOT = "CLASS_TREE_ROOT"


def _candidate_roots(class_tree_root=None):
    roots = []
    if class_tree_root:
        roots.append(Path(class_tree_root))

    env_root = os.environ.get(ENV_CLASS_TREE_ROOT, "")
    if env_root:
        roots.append(Path(env_root))

    roots.append(PROJECT_CLASS_TREE_ROOT)
    roots.append(LEGACY_TACA_CLASS_TREE_ROOT)

    deduped = []
    seen = set()
    for root in roots:
        key = os.path.normcase(os.path.abspath(os.fspath(root)))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(root)
    return deduped


def resolve_class_tree_file(filename, class_tree_root=None):
    searched_paths = []
    filename_path = Path(filename)
    if filename_path.is_absolute() or filename_path.parent != Path("."):
        searched_paths.append(filename_path)
        if filename_path.is_file():
            return os.fspath(filename_path)
    else:
        for root in _candidate_roots(class_tree_root=class_tree_root):
            candidate = root / filename
            searched_paths.append(candidate)
            if candidate.is_file():
                return os.fspath(candidate)

    searched_text = "\n".join(f"- {path}" for path in searched_paths)
    raise FileNotFoundError(
        "Class-tree file not found. Provide it through an explicit class-tree "
        f"root, {ENV_CLASS_TREE_ROOT}, project-local {PROJECT_CLASS_TREE_ROOT}, "
        f"or the legacy TACA fallback. Missing file: {filename}\n"
        f"Searched paths:\n{searched_text}"
    )


def resolve_class_tree_files(filenames=DEFAULT_CLASS_TREE_FILENAMES, class_tree_root=None):
    return [
        resolve_class_tree_file(filename, class_tree_root=class_tree_root)
        for filename in filenames
    ]
