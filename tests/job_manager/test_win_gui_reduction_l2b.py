from types import SimpleNamespace

from czjLLM.job_manager.win_gui import (
    _GUIClient, _GuiEvents, format_reduction_stats, reduction_status_is_error,
)


class Queue:
    def __init__(self): self.items = []
    def put(self, item): self.items.append(item)


def test_reduction_snapshot_client_and_formatting():
    queue = Queue()
    event = SimpleNamespace(is_set=lambda: True)
    client = _GUIClient(queue, SimpleNamespace(is_alive=lambda: False), event)
    stats = {"stages_started": 2, "stages_completed": 1, "members_attempted": 4,
             "members_succeeded": 3, "members_failed": 1, "run_status": "cancelled"}
    client.update_reduction_stats(stats)
    assert queue.items == [(_GuiEvents.REDUCTION, stats)]
    assert client.cancellation_requested()
    rendered = format_reduction_stats(stats)
    assert "Stages: 1 / 2" in rendered and "Cancellation: Cancelled" in rendered
    assert reduction_status_is_error({"stages_failed": 1})
