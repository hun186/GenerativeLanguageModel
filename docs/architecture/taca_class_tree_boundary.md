# TACA class-tree boundary plan

## Problem

The text classification project currently depends on class hierarchy edge CSV files that are stored in a sibling TACA project, typically through paths such as `../TACA/DB/ZMRAND/Imported/TopicTree.csv`.
This worked when TACA was the shared topology-editing workspace, but it makes the text classification project depend on a parent-directory checkout and mixes two module boundaries:

- TACA owns topology drawing, editing, and visualization tools.
- The text classification project owns training, testing, dataset conversion, and label semantics for classifiers.

## Recommended boundary

Treat the class hierarchy CSV as a text-classification configuration artifact, not as an implementation detail owned by TACA.
TACA may remain an authoring and visualization tool, but runtime classification should read hierarchy files from this project first.

Suggested ownership:

| Artifact or behavior | Owning project |
| --- | --- |
| CSV edge authoring UI / visualization | TACA |
| Runtime class-tree edge CSV consumed by DataConverter / label loading | Text classification project |
| Export/import bridge between TACA and classifier config | Explicit sync script or documented copy step |
| Model-specific train/test dataset and output dirs | Text classification project |

## Target directory layout

Use an in-repository class-tree config directory, for example:

```text
config/
  class_trees/
    default/
      TopicTree.csv
      TopicTree_AK4.csv
      TopicTree_PAK.txt
```

The exact filenames can stay compatible with the existing loaders, but their root should be controlled by this project.

## Migration strategy

1. Add a project-level setting for the class-tree root, such as `--ClassTreeRoot`, `CLASS_TREE_ROOT`, or a YAML key.
2. Resolve class-tree files in this order:
   1. explicit CLI / YAML / environment setting;
   2. project-local `config/class_trees/default/`;
   3. legacy `../TACA/DB/ZMRAND/Imported/` fallback during migration only.
3. When a file is missing, fail fast with a message that lists every searched path.
4. Keep TACA out of runtime imports. TACA should export CSVs; this project should only consume CSV files.
5. After all deployments are migrated, remove the legacy sibling-project fallback.

## Why not keep `../TACA` as the default runtime source?

Sibling-project paths make the classifier non-portable: a clean checkout, CI job, container, or another developer machine may not have TACA in the expected parent directory. Moving runtime CSVs under this repository makes releases reproducible while still allowing TACA to remain the editing tool.

## Operational guidance for the current failure

The observed failure means the classifier could not find `TopicTree.csv` at the legacy sibling-project location. For the current code, either restore/copy the expected CSV to the configured legacy location or migrate it into a project-local class-tree config directory and update the loader to search that directory first.

## Implementation status in this checkout

`utils/class_tree_paths.py` implements the resolver described above for code paths present in this repository. `RawAndPredictionMerger.GetInfoScoreTable()` now resolves `TopicTree.csv` and `TopicTree_AK4.csv` before calling the existing tree loader.

The Windows traceback also references `ClassesTree/ClassesTree_utils.py::SetTreeFiles()`, but that file is not present in this checkout. The actual `text-category-profiler` repository should wire the same resolver into `SetTreeFiles()` so `DatasetConverter/DataConverter.py::loadLabels()` gets the same project-local-first behavior.
