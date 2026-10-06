import queue

from czjLLM.job_manager.win_gui import (
    _GUIClient, format_recheck_stats, format_recheck_summary, recheck_status_is_error,
)


class Proc:
    def is_alive(self): return False


def test_recheck_format_and_thread_safe_queue_contract():
    rendered = format_recheck_stats({"checked": 10, "already_completed": 8, "pending": 2,
                                     "semantic_stale_count": 1, "errors": 3})
    assert "80.0%" in rendered and "Semantic stale: 1" in rendered and "Recheck Errors: 3" in rendered
    events = queue.Queue()
    client = _GUIClient(events, Proc())
    snapshot = {"checked": 1}
    client.update_recheck_stats(snapshot)
    snapshot["checked"] = 99
    event, payload = events.get_nowait()
    assert event == "recheck" and payload == {"checked": 1}


def test_recheck_fixed_status_zero_normal_and_error_presentations():
    zero = format_recheck_stats({})
    assert "Checked: 0" in zero and "Skipped: 0 (0.0%)" in zero
    normal = {"checked": 4, "already_completed": 3, "pending": 1,
              "semantic_stale_count": 2, "errors": 0}
    assert "75.0%" in format_recheck_stats(normal)
    assert "Semantic stale: 2" in format_recheck_stats(normal)
    assert recheck_status_is_error(normal) is False
    assert recheck_status_is_error({**normal, "errors": 1}) is True


def test_repeated_recheck_events_are_detached_cumulative_snapshots():
    events = queue.Queue()
    client = _GUIClient(events, Proc())
    client.update_recheck_stats({"checked": 1})
    client.update_recheck_stats({"checked": 2})
    assert events.get_nowait()[1] == {"checked": 1}
    assert events.get_nowait()[1] == {"checked": 2}



def test_recheck_collapsed_header_summary_and_source_contract():
    assert format_recheck_summary({
        "checked": 79, "pending": 74, "already_completed": 5, "errors": 0,
    }) == "Checked 79 · Need 74 · Skipped 5 · Errors 0"

    import inspect
    from czjLLM.job_manager import win_gui
    source = inspect.getsource(win_gui._gui_proc_main)
    assert "recheck_frame.pack_forget()" in source
    assert "Recheck Status —" in source
