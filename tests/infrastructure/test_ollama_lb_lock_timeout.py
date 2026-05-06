from czjLLM.infrastructure import ollama_lb
from czjLLM.utilities.atomic_io import atomic_write_json


def test_select_idle_ollama_url_fallbacks_when_lock_timeout(monkeypatch):
    monkeypatch.setattr(
        ollama_lb,
        "_acquire_file_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("lock busy")),
    )
    monkeypatch.setattr(ollama_lb.random, "choice", lambda xs: xs[0])
    picked = ollama_lb.select_idle_ollama_url(["http://a/v1", "http://b/v1"], PGMSubDir=".")
    assert picked == "http://a/v1"


def test_release_url_load_returns_when_lock_timeout(monkeypatch):
    monkeypatch.setattr(
        ollama_lb,
        "_acquire_file_lock",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("lock busy")),
    )
    # 不應拋例外
    ollama_lb.release_url_load("http://a/v1", PGMSubDir=".")


def test_select_idle_ollama_url_resets_stale_load_state(tmp_path, monkeypatch):
    load_file = tmp_path / "logs" / "base_url_load.json"
    stale_lease_that_would_otherwise_block = 9_999.0
    atomic_write_json(
        load_file,
        {
            "http://a/v1": {
                "leases": [stale_lease_that_would_otherwise_block],
                "last_update": 1_000.0,
            },
            "http://b/v1": {"leases": [], "last_update": 1_000.0},
        },
    )
    monkeypatch.setattr(ollama_lb, "STALE_RESET_SECS", 1_200.0)
    monkeypatch.setattr(ollama_lb, "_now", lambda: 2_300.0)
    monkeypatch.setattr(ollama_lb, "EPSILON_EXPLORE", 0.0)
    monkeypatch.setattr(ollama_lb, "JITTER", 0.0)
    monkeypatch.setattr(ollama_lb.random, "random", lambda: 0.5)
    monkeypatch.setattr(ollama_lb.random, "choice", lambda xs: xs[0])

    picked = ollama_lb.select_idle_ollama_url(
        ["http://a/v1", "http://b/v1"], PGMSubDir=str(tmp_path)
    )

    assert picked == "http://a/v1"
    state = __import__("json").loads(load_file.read_text(encoding="utf-8"))
    assert stale_lease_that_would_otherwise_block not in state["http://a/v1"]["leases"]
    assert state["http://a/v1"]["last_update"] == 2_300.0
    assert state["http://b/v1"]["last_update"] == 2_300.0


def test_select_idle_ollama_url_keeps_state_when_any_url_recently_updated(tmp_path, monkeypatch):
    load_file = tmp_path / "logs" / "base_url_load.json"
    active_lease_on_old_url = 9_999.0
    atomic_write_json(
        load_file,
        {
            "http://a/v1": {
                "leases": [active_lease_on_old_url],
                "last_update": 1_000.0,
            },
            "http://b/v1": {"leases": [], "last_update": 2_200.0},
        },
    )
    monkeypatch.setattr(ollama_lb, "STALE_RESET_SECS", 1_200.0)
    monkeypatch.setattr(ollama_lb, "_now", lambda: 2_300.0)
    monkeypatch.setattr(ollama_lb, "EPSILON_EXPLORE", 0.0)
    monkeypatch.setattr(ollama_lb, "JITTER", 0.0)
    monkeypatch.setattr(ollama_lb.random, "random", lambda: 0.5)
    monkeypatch.setattr(ollama_lb.random, "choice", lambda xs: xs[0])

    picked = ollama_lb.select_idle_ollama_url(
        ["http://a/v1", "http://b/v1"], PGMSubDir=str(tmp_path)
    )

    assert picked == "http://b/v1"
    state = __import__("json").loads(load_file.read_text(encoding="utf-8"))
    assert active_lease_on_old_url in state["http://a/v1"]["leases"]
    assert state["http://a/v1"]["last_update"] == 1_000.0
    assert state["http://b/v1"]["last_update"] == 2_300.0


def test_select_idle_ollama_url_keeps_fresh_load_state(tmp_path, monkeypatch):
    load_file = tmp_path / "logs" / "base_url_load.json"
    active_lease = 2_000.0
    atomic_write_json(
        load_file,
        {
            "http://a/v1": {"leases": [active_lease], "last_update": 900.0},
            "http://b/v1": {"leases": [], "last_update": 900.0},
        },
    )
    monkeypatch.setattr(ollama_lb, "STALE_RESET_SECS", 1_200.0)
    monkeypatch.setattr(ollama_lb, "_now", lambda: 1_000.0)
    monkeypatch.setattr(ollama_lb, "EPSILON_EXPLORE", 0.0)
    monkeypatch.setattr(ollama_lb, "JITTER", 0.0)
    monkeypatch.setattr(ollama_lb.random, "random", lambda: 0.5)
    monkeypatch.setattr(ollama_lb.random, "choice", lambda xs: xs[0])

    picked = ollama_lb.select_idle_ollama_url(
        ["http://a/v1", "http://b/v1"], PGMSubDir=str(tmp_path)
    )

    assert picked == "http://b/v1"
    state = __import__("json").loads(load_file.read_text(encoding="utf-8"))
    assert active_lease in state["http://a/v1"]["leases"]
    assert state["http://a/v1"]["last_update"] == 900.0
