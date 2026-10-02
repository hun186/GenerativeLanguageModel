from czjLLM.reduction import ExecutionContext, ProcessingIdentity, executable_semantic_fingerprint


class Executable:
    def fingerprint_metadata(self, context):
        return {"task": context.reducer_context.get("task"), "reducer": {"top_k": 5}}


def test_processing_identity_uses_executable_metadata():
    first = executable_semantic_fingerprint(Executable(), ExecutionContext(reducer_context={"task": "a"}))
    again = executable_semantic_fingerprint(Executable(), ExecutionContext(reducer_context={"task": "a"}))
    changed = executable_semantic_fingerprint(Executable(), ExecutionContext(reducer_context={"task": "b"}))
    assert first == again and first != changed
    assert ProcessingIdentity(first).execution_fingerprint == first
