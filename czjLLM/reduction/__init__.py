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
from .retention import (
    ArtifactLease,
    ReductionArtifactKind,
    ReductionRetentionPolicy,
    RetentionCandidate,
    RetentionReport,
    cleanup_completed_transient_runtime,
    parse_reduction_retention_policy,
    run_reduction_retention,
)
from .execution import (
    CancellationSignal, EventCancellationSignal, ExecutionObserver, NoOpExecutionObserver,
    Executable, ExecutableRegistry,
    ExecutableResult, ExecutionCancelled, ExecutionContext, ExecutionError, NeverCancelled,
    ExecutionNestingState, TaskCallResult, TaskExecutable, TaskRuntime,
    ProcessingIdentity, executable_semantic_fingerprint,
)
from .executable_pipeline import PipelineRefExecutable, StagePipelineExecutable
from .runtime_task import ProductionTaskRuntime, TaskPromptPreflight
from .stage import (
    MAX_MEMBER_FAILURE_DETAILS, MemberFailureRecord, PartialSuccessPolicy,
    PartialSuccessRejectedError, ReductionStage, ReductionStageResult, RoundPreparer,
    TokenizerRoundPreparer,
)
from .nested_execution import (
    IdentityInputPreparer, InputPreparer, ReductionStageExecutable, TokenizerInputPreparer,
)
from .stage_config import (
    ReductionStageConfig, parse_reduction_stage_config,
    parse_reduction_stage_executable_config,
)
from .persisted_freshness import (
    PersistedProcessingExecutable, bind_persisted_execution_fingerprint,
    effective_persisted_executable,
)
from .registry import (
    ReducerRegistry,
    get_default_registry,
    register_builtin_reducers,
    register_reducer,
)
from .production_control import (
    ProductionExecutionObserver, build_production_execution_context,
    ensure_execution_cancel_event, ensure_production_observer, execution_cancel_requested,
    production_cancellation_signal, raise_if_execution_cancelled,
    request_execution_cancel,
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
    "ArtifactLease", "ReductionArtifactKind", "ReductionRetentionPolicy",
    "RetentionCandidate", "RetentionReport", "cleanup_completed_transient_runtime",
    "parse_reduction_retention_policy", "run_reduction_retention",
    "derive_aggregate_output_id",
    "deterministic_scalar_order_key",
    "canonical_group_entries",
    "normalize_collection_window",
    "register_builtin_reducers",
    "register_reducer",
    "Executable", "ExecutableRegistry", "ExecutableResult", "ExecutionContext",
    "ExecutionNestingState",
    "ProcessingIdentity", "executable_semantic_fingerprint",
    "CancellationSignal", "NeverCancelled", "EventCancellationSignal",
    "ExecutionObserver", "NoOpExecutionObserver",
    "ExecutionError", "ExecutionCancelled", "TaskCallResult", "TaskExecutable", "TaskRuntime",
    "PipelineRefExecutable", "StagePipelineExecutable", "ProductionTaskRuntime",
    "TaskPromptPreflight",
    "ReductionStage", "ReductionStageResult", "RoundPreparer", "TokenizerRoundPreparer",
    "PartialSuccessPolicy", "PartialSuccessRejectedError", "MemberFailureRecord",
    "MAX_MEMBER_FAILURE_DETAILS",
    "InputPreparer", "IdentityInputPreparer", "TokenizerInputPreparer",
    "ReductionStageExecutable", "ReductionStageConfig", "parse_reduction_stage_config",
    "parse_reduction_stage_executable_config",
    "PersistedProcessingExecutable", "bind_persisted_execution_fingerprint",
    "effective_persisted_executable",
    "ProductionExecutionObserver", "build_production_execution_context",
    "ensure_execution_cancel_event", "execution_cancel_requested",
    "ensure_production_observer",
    "production_cancellation_signal", "raise_if_execution_cancelled",
    "request_execution_cancel",
]
