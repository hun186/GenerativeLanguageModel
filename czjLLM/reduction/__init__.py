"""Reduction Engine contracts, strict config, and one-pass routing."""

from .config import ReductionConfig, ReductionConfigError, parse_reduction_config
from .collection import (
    COLLECTION_MANIFEST_CONTRACT_VERSION,
    CollectionManifest,
    CollectionManifestError,
    CollectionManifestValidationError,
    LogicalWorkUnit,
)
from .contracts import Reducer, ReducerResult
from .reducers import (
    CompositeReducer, DedupReducer, DeterministicReducerError, EntityUnionReducer,
    GroupReducer, RankReducer, TopKReducer,
    SemanticCallResult, SemanticLLMReducer, SemanticReducerError, SemanticRuntime,
    EntitySetSpec, ReferenceSpec, StructuredRelationalError, StructuredRelationalReducer,
)
from .aggregate import (
    AGGREGATE_OUTPUT_CONTRACT_VERSION,
    AggregateOutput,
    CollectionManifestStore,
    derive_aggregate_output_id,
    deterministic_scalar_order_key,
    canonical_group_entries,
    normalize_collection_window,
)
from .engine import reduce_single_pass
from .controllers import AdaptiveHierarchicalController, FixedRoundsController
from .hierarchical import reduce_hierarchical_text
from .execution import (
    Executable, ExecutableRegistry, ExecutableResult, ExecutionContext, ExecutionError,
    ExecutionNestingState, TaskCallResult, TaskExecutable, TaskRuntime,
    ProcessingIdentity, executable_semantic_fingerprint,
)
from .executable_pipeline import PipelineRefExecutable, StagePipelineExecutable
from .runtime_task import ProductionTaskRuntime, TaskPromptPreflight
from .stage import ReductionStage, ReductionStageResult, RoundPreparer, TokenizerRoundPreparer
from .nested_execution import (
    IdentityInputPreparer, InputPreparer, ReductionStageExecutable, TokenizerInputPreparer,
)
from .stage_config import (
    ReductionStageConfig, parse_reduction_stage_config,
    parse_reduction_stage_executable_config,
)
from .registry import (
    ReducerRegistry,
    get_default_registry,
    register_builtin_reducers,
    register_reducer,
)

__all__ = [
    "Reducer",
    "AGGREGATE_OUTPUT_CONTRACT_VERSION",
    "AggregateOutput",
    "COLLECTION_MANIFEST_CONTRACT_VERSION",
    "CollectionManifest",
    "CollectionManifestError",
    "CollectionManifestValidationError",
    "LogicalWorkUnit",
    "CollectionManifestStore",
    "ReductionConfig",
    "ReductionConfigError",
    "ReducerRegistry",
    "ReducerResult",
    "CompositeReducer", "DedupReducer", "DeterministicReducerError",
    "EntityUnionReducer", "GroupReducer", "RankReducer", "TopKReducer",
    "SemanticCallResult", "SemanticLLMReducer", "SemanticReducerError", "SemanticRuntime",
    "EntitySetSpec", "ReferenceSpec", "StructuredRelationalError", "StructuredRelationalReducer",
    "AdaptiveHierarchicalController",
    "FixedRoundsController",
    "get_default_registry",
    "parse_reduction_config",
    "reduce_single_pass",
    "reduce_hierarchical_text",
    "derive_aggregate_output_id",
    "deterministic_scalar_order_key",
    "canonical_group_entries",
    "normalize_collection_window",
    "register_builtin_reducers",
    "register_reducer",
    "Executable", "ExecutableRegistry", "ExecutableResult", "ExecutionContext",
    "ExecutionNestingState",
    "ProcessingIdentity", "executable_semantic_fingerprint",
    "ExecutionError", "TaskCallResult", "TaskExecutable", "TaskRuntime",
    "PipelineRefExecutable", "StagePipelineExecutable", "ProductionTaskRuntime",
    "TaskPromptPreflight",
    "ReductionStage", "ReductionStageResult", "RoundPreparer", "TokenizerRoundPreparer",
    "InputPreparer", "IdentityInputPreparer", "TokenizerInputPreparer",
    "ReductionStageExecutable", "ReductionStageConfig", "parse_reduction_stage_config",
    "parse_reduction_stage_executable_config",
]
