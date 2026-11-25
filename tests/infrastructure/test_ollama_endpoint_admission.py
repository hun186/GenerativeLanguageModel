import json
from concurrent.futures import ThreadPoolExecutor

import pytest

from czjLLM.infrastructure import ollama_lb as lb


def claim(urls, path, cap=1, timeout=0):
    return lb.select_idle_ollama_url(
        urls, PGMSubDir=str(path), return_lease_token=True,
        max_concurrent_per_endpoint=cap, admission_timeout_sec=timeout,
    )


def test_exploration_only_chooses_available_endpoint(tmp_path, monkeypatch):
    urls = ["http://a.invalid/v1", "http://b.invalid/v1"]
    monkeypatch.setattr(lb, "EPSILON_EXPLORE", 1.0)
    monkeypatch.setattr(lb.random, "choice", lambda choices: choices[0])
    first, token = claim(urls, tmp_path)
    second, _ = claim(urls, tmp_path)
    assert (first, second) == tuple(urls)
    with pytest.raises(lb.EndpointCapacityUnavailable):
        claim(urls, tmp_path)
    lb.release_url_load(first, PGMSubDir=str(tmp_path), lease_token=token)
    assert claim(urls, tmp_path)[0] == first


def test_concurrent_claims_never_exceed_shared_file_capacity(tmp_path):
    urls = [f"http://gpu{i}.invalid/v1" for i in range(4)]

    def attempt(_):
        try:
            return claim(urls, tmp_path)
        except lb.EndpointCapacityUnavailable:
            return None

    with ThreadPoolExecutor(max_workers=12) as pool:
        results = list(pool.map(attempt, range(12)))
    successes = [x for x in results if x is not None]
    assert len(successes) == 4
    assert {url for url, _ in successes} == set(urls)
    state = json.loads((tmp_path / "logs" / "base_url_load.json").read_text())
    assert all(len(state[url]["leases"]) == 1 for url in urls)


def test_cap_two_and_wait_until_release(tmp_path, monkeypatch):
    url = "http://a.invalid/v1"
    first, token = claim(url, tmp_path, cap=2)
    claim(url, tmp_path, cap=2)
    def release_on_wait(_):
        lb.release_url_load(first, PGMSubDir=str(tmp_path), lease_token=token)
    monkeypatch.setattr(lb.time, "sleep", release_on_wait)
    assert claim(url, tmp_path, cap=2, timeout=1)[0] == url


def test_capped_lock_contention_never_randomly_dispatches(tmp_path, monkeypatch):
    def busy(*args, **kwargs):
        raise TimeoutError("lock busy")
    monkeypatch.setattr(lb, "_acquire_file_lock", busy)
    with pytest.raises(lb.EndpointCapacityUnavailable):
        claim(["http://a.invalid/v1"], tmp_path)


def test_corrupt_lease_file_fails_closed(tmp_path):
    path = tmp_path / "logs" / "base_url_load.json"
    path.parent.mkdir()
    path.write_text("{bad", encoding="utf-8")
    with pytest.raises(ValueError):
        claim(["http://a.invalid/v1"], tmp_path)
    assert path.read_text() == "{bad"


def test_cap_requires_owned_tokens(tmp_path):
    with pytest.raises(ValueError, match="owned lease"):
        lb.select_idle_ollama_url(["a"], PGMSubDir=str(tmp_path),
                                  max_concurrent_per_endpoint=1)


def test_capped_admission_does_not_reset_live_stale_lease(tmp_path, monkeypatch):
    url = "http://a.invalid/v1"
    path = tmp_path / "logs" / "base_url_load.json"
    path.parent.mkdir()
    path.write_text(json.dumps({url: {"leases": [9999.0], "last_update": 1000.0}}))
    monkeypatch.setattr(lb, "_now", lambda: 3000.0)
    monkeypatch.setattr(lb, "STALE_RESET_SECS", 1200)
    with pytest.raises(lb.EndpointCapacityUnavailable):
        claim(url, tmp_path)
    assert json.loads(path.read_text())[url]["leases"] == [9999.0]
