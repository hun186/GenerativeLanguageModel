class BaseMergeStrategy:
    def merge(self, extraction_results, context):
        raise NotImplementedError("Subclasses must implement merge().")
