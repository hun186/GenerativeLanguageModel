from .base_strategy import BaseMergeStrategy


class MixedStrategy(BaseMergeStrategy):
    def merge(self, extraction_results, context):
        return {
            "doc_type": "mixed",
            "items": extraction_results,
            "note": "Skeleton mixed merge result.",
        }
