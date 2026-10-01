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
]
