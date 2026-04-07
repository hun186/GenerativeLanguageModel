from .base_strategy import BaseMergeStrategy


class ReportStrategy(BaseMergeStrategy):
    def merge(self, extraction_results, context):
        return {
            "doc_type": "report",
            "items": extraction_results,
            "note": "Skeleton report merge result.",
        }
