"""Deterministic local-fs coverage of in-flight owned endpoint lease renewal.

No live LLM provider or GPU. Wall-clock sleeps only test the isolated helper.
"""
import json
import time

from czjLLM.infrastructure import ollama_lb
from czjLLM.utilities.atomic_io import atomic_write_json


def _claim(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_lb, "EPSILON_EXPLORE", 0.0)
    monkeypatch.setattr(ollama_lb, "JITTER", 0.0)
    monkeypatch.setattr(ollama_lb.random, "random", lambda: 0.5)
    monkeypatch.setattr(ollama_lb.random, "choice", lambda urls: urls[0])
    url = "http://worker.invalid/v1"
    picked, token = ollama_lb.select_idle_ollama_url(
        [url], PGMSubDir=str(tmp_path), return_lease_token=True,
    )
    assert picked == url and type(token) is float
    return url, token, tmp_path / "logs" / "base_url_load.json"


def test_renew_only_owned_lease_and_match_later_release(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(ollama_lb, "_now", lambda: clock[0])
    url, first, file = _claim(tmp_path, monkeypatch)
    _, peer = ollama_lb.select_idle_ollama_url(
        [url], PGMSubDir=str(tmp_path), return_lease_token=True,
    )
    assert first != peer
    clock[0] = 1100.0
    refreshed = ollama_lb.renew_url_load(
        url, PGMSubDir=str(tmp_path), lease_token=first,
    )
    assert refreshed > first
    state = json.loads(file.read_text(encoding="utf-8"))[url]
    assert state["leases"] == [refreshed, peer]
    assert state["last_update"] == clock[0]
    ollama_lb.release_url_load(url, PGMSubDir=str(tmp_path), lease_token=first)
    assert json.loads(file.read_text(encoding="utf-8"))[url]["leases"] == [refreshed, peer]
    ollama_lb.release_url_load(url, PGMSubDir=str(tmp_path), lease_token=refreshed)
    assert json.loads(file.read_text(encoding="utf-8"))[url]["leases"] == [peer]


def test_expired_or_removed_lease_never_resurrects(tmp_path, monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(ollama_lb, "_now", lambda: clock[0])
    url, lease, file = _claim(tmp_path, monkeypatch)
    clock[0] = lease + 1.0
    before = file.read_bytes()
    assert ollama_lb.renew_url_load(
        url, PGMSubDir=str(tmp_path), lease_token=lease,
    ) is None
    assert file.read_bytes() == before
    clock[0] = 1000.0
    atomic_write_json(file, {url: {"leases": [lease + 500.0], "last_update": 1000.0}})
    before = file.read_bytes()
    assert ollama_lb.renew_url_load(
        url, PGMSubDir=str(tmp_path), lease_token=lease,
    ) is None
    assert file.read_bytes() == before


def test_corrupt_or_missing_claim_fails_closed(tmp_path, monkeypatch):
    url, token, file = _claim(tmp_path, monkeypatch)
    file.write_text("{incomplete", encoding="utf-8")
    assert ollama_lb.renew_url_load(
        url, PGMSubDir=str(tmp_path), lease_token=token,
    ) is None
    assert file.read_text(encoding="utf-8") == "{incomplete"
    file.unlink()
    assert ollama_lb.renew_url_load(
        url, PGMSubDir=str(tmp_path), lease_token=token,
    ) is None
    assert not file.exists()


def test_lock_contention_never_writes_or_steals_lease(tmp_path, monkeypatch):
    url, token, file = _claim(tmp_path, monkeypatch)
    initial = file.read_bytes()
    monkeypatch.setattr(
        ollama_lb, "_acquire_file_lock",
        lambda *a, **kw: (_ for _ in ()).throw(TimeoutError("busy")),
    )
    # Same token communicates a missed tick; it is NOT a renewed TTL.
    assert ollama_lb.renew_url_load(
        url, PGMSubDir=str(tmp_path), lease_token=token,
    ) == token
    assert file.read_bytes() == initial


def test_keeper_renews_during_call_and_stops_before_owned_release(tmp_path, monkeypatch):
    monkeypatch.setattr(ollama_lb, "LEASE_SECS", 0.18)
    url, original, file = _claim(tmp_path, monkeypatch)
    with ollama_lb.maintain_url_load_lease(
        url, PGMSubDir=str(tmp_path), lease_token=original,
        interval_seconds=0.015, max_elapsed_seconds=0.3,
    ) as keeper:
        deadline = time.monotonic() + 0.6
        while keeper.lease_token == original and time.monotonic() < deadline:
            time.sleep(0.005)
        assert keeper.lease_token > original
        assert keeper._thread.is_alive()
    last = keeper.lease_token
    assert not keeper._thread.is_alive()
    time.sleep(0.04)
    assert keeper.lease_token == last
    ollama_lb.release_url_load(url, PGMSubDir=str(tmp_path), lease_token=last)
    assert json.loads(file.read_text(encoding="utf-8"))[url]["leases"] == []


def test_keeper_is_noop_for_untracked_random_fallback(monkeypatch):
    def unsafe_renew(*a, **kw):
        raise AssertionError("Must never renew an untracked endpoint")
    monkeypatch.setattr(ollama_lb, "renew_url_load", unsafe_renew)
    with ollama_lb.maintain_url_load_lease(
        "http://fallback.invalid", lease_token=None, interval_seconds=0.01,
    ) as keeper:
        time.sleep(0.03)
    assert keeper.lease_token is None
    assert keeper._thread is None


def test_keeper_heartbeat_has_hard_elapsed_cap(monkeypatch):
    counts = []
    def fake_renew(*a, **kw):
        counts.append(1)
        return kw["lease_token"] + 1.0
    monkeypatch.setattr(ollama_lb, "renew_url_load", fake_renew)
    with ollama_lb.maintain_url_load_lease(
        "http://worker.invalid", lease_token=1800000000.0,
        interval_seconds=0.01, max_elapsed_seconds=0.065,
    ) as keeper:
        time.sleep(0.11)
        frozen = len(counts)
        time.sleep(0.03)
        assert len(counts) == frozen
    assert 1 <= frozen <= 7
    assert not keeper._thread.is_alive()
