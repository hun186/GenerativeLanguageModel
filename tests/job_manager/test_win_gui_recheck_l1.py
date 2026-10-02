import queue

from czjLLM.job_manager.win_gui import _GUIClient, format_recheck_stats


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
