from .base_strategy import BaseMergeStrategy


class EventStrategy(BaseMergeStrategy):
    def merge(self, extraction_results, context):
        return {
            "doc_type": "event",
            "items": extraction_results,
            "note": "Skeleton event merge result.",
        }
