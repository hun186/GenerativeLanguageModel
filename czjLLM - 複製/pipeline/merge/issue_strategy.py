from .base_strategy import BaseMergeStrategy


class IssueStrategy(BaseMergeStrategy):
    def merge(self, extraction_results, context):
        return {
            "doc_type": "issue",
            "items": extraction_results,
            "note": "Skeleton issue merge result.",
        }
