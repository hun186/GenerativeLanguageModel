from .base_strategy import BaseMergeStrategy


class ProfileStrategy(BaseMergeStrategy):
    def merge(self, extraction_results, context):
        return {
            "doc_type": "profile",
            "items": extraction_results,
            "note": "Skeleton profile merge result.",
        }
