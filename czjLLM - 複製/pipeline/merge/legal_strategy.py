from .base_strategy import BaseMergeStrategy


class LegalStrategy(BaseMergeStrategy):
    def merge(self, extraction_results, context):
        return {
            "doc_type": "legal",
            "items": extraction_results,
            "note": "Skeleton legal merge result.",
        }
