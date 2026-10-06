from types import SimpleNamespace

from czjLLM.job_manager.win_gui import (
    _GUIClient, _GuiEvents, format_reduction_stats, format_reduction_summary,
    reduction_status_is_error,
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


def test_terminal_snapshot_is_enqueued_before_close():
    queue = Queue()
    gui = _GUIClient(queue, SimpleNamespace(is_alive=lambda: False))
    for status in ("completed", "cancelled", "failed"):
        queue.items.clear()
        gui.update_reduction_stats({"run_status": status}, final=True)
        gui.close()
        assert queue.items == [
            (_GuiEvents.REDUCTION, {"run_status": status}),
            (_GuiEvents.CLOSE, None),
        ]



def test_legacy_merge_status_is_mode_aware_and_collapsible():
    stats = {
        "activity_mode": "legacy_merge_slices",
        "legacy_merges_started": 79,
        "legacy_merges_completed": 74,
        "legacy_merges_failed": 0,
        "run_status": "running",
    }
    rendered = format_reduction_stats(stats)
    assert "Mode: Legacy merge_slices" in rendered
    assert "Merge attempts: 74 / 79" in rendered
    assert "Stages: 0 / 0" not in rendered
    assert format_reduction_summary(stats) == (
        "Legacy merge_slices · Merged 74/79 · Errors 0"
    )
    assert reduction_status_is_error({**stats, "legacy_merges_failed": 1})

    import inspect
    from czjLLM.job_manager import win_gui
    source = inspect.getsource(win_gui._gui_proc_main)
    assert "reduction_frame.pack_forget()" in source
    assert "cancel_button = ttk.Button(reduction_header" in source
