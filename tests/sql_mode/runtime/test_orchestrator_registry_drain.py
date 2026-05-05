from czjLLM.sql_mode.runtime.orchestrator import _is_reg_drained


class _RegistryWithListOnly:
    def __init__(self, items):
        self._items = items

    def list_items(self):
        return dict(self._items)


def test_is_reg_drained_uses_list_items_when_stats_missing():
    reg = _RegistryWithListOnly({"job/a": {"pk": "1101.TW"}})
    assert _is_reg_drained(reg) is False


def test_is_reg_drained_true_when_list_items_empty():
    reg = _RegistryWithListOnly({})
    assert _is_reg_drained(reg) is True
