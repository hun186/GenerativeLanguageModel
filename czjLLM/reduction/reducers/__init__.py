"""Built-in reducer implementations."""

from .legacy import ConcatJsonListReducer, ConcatTextReducer, LegacyJsonDeepMergeReducer
from .deterministic import (
    CompositeReducer, DedupReducer, DeterministicReducerError, EntityUnionReducer,
    GroupReducer, RankReducer, TopKReducer,
)
from .semantic import (
    SemanticCallResult, SemanticLLMReducer, SemanticReducerError, SemanticRuntime,
    semantic_content_envelope,
)
from .structured_relational import (
    EntitySetSpec, ReferenceSpec, StructuredRelationalError,
    StructuredRelationalReducer, validate_structured_relational_options,
)

__all__ = [
    "ConcatJsonListReducer",
    "ConcatTextReducer",
    "LegacyJsonDeepMergeReducer",
    "CompositeReducer", "DedupReducer", "DeterministicReducerError",
    "EntityUnionReducer", "GroupReducer", "RankReducer", "TopKReducer",
    "SemanticCallResult", "SemanticLLMReducer", "SemanticReducerError",
    "SemanticRuntime", "semantic_content_envelope",
    "EntitySetSpec", "ReferenceSpec", "StructuredRelationalError",
    "StructuredRelationalReducer", "validate_structured_relational_options",
]
