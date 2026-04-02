from .base_strategy import BaseMergeStrategy


class InterviewStrategy(BaseMergeStrategy):
    def merge(self, extraction_results, context):
        return {
            "doc_type": "interview",
            "items": extraction_results,
            "note": "Skeleton interview merge result.",
        }
