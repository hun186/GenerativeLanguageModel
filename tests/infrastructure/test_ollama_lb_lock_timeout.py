from czjLLM.infrastructure import ollama_lb


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
