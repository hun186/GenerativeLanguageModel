# Default class-tree CSV directory

Place the runtime class hierarchy edge files for this text classification project here when migrating away from the legacy sibling TACA checkout.

Expected files for the existing loaders include:

- `TopicTree.csv`
- `TopicTree_AK4.csv`
- `TopicTree_PAK.txt` when restricted-label mode is used

`utils.class_tree_paths.resolve_class_tree_file()` searches class-tree files in this order:

1. explicit `class_tree_root` argument;
2. `CLASS_TREE_ROOT` environment variable;
3. this project-local directory: `config/class_trees/default/`;
4. legacy fallback: `../TACA/DB/ZMRAND/Imported/`.

During migration, copying the above files from TACA into this directory is enough for code paths wired to `utils.class_tree_paths` to prefer the project-local copies. Keep the CSV contents out of git if they contain private or environment-specific taxonomy data.
