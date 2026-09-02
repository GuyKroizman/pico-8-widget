"""Tests for fetch() retry behaviour — without touching the network."""

import pytest

import p8


class _Response:
    def __init__(self, body):
        self._body = body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self):
        return self._body


def test_fetch_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise OSError("connection reset")
        return _Response(b"ok")

    monkeypatch.setattr(p8.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(p8.time, "sleep", lambda _s: None)  # no real waiting
    assert p8.fetch("https://example.test/x") == b"ok"
    assert calls["n"] == 3


def test_fetch_gives_up_after_retries(monkeypatch):
    calls = {"n": 0}

    def always_down(request, timeout=None):
        calls["n"] += 1
        raise OSError("boom")

    monkeypatch.setattr(p8.urllib.request, "urlopen", always_down)
    monkeypatch.setattr(p8.time, "sleep", lambda _s: None)
    with pytest.raises(RuntimeError, match="GET https://example.test/x failed"):
        p8.fetch("https://example.test/x")
    assert calls["n"] == p8.REQUEST_RETRIES


def test_fetch_paces_requests(monkeypatch):
    """Requests must be spaced apart: the wait between two calls should be
    >= REQUEST_GAP unless that gap was already respected."""
    monkeypatch.setattr(p8, "REQUEST_GAP", 0.5)  # undo the autouse zeroing
    monkeypatch.setattr(p8, "_last_request_at", 0.0)  # last request was long ago
    sleeps = []
    monkeypatch.setattr(p8.time, "sleep", sleeps.append)

    def ok(request, timeout=None):
        return _Response(b"ok")

    monkeypatch.setattr(p8.urllib.request, "urlopen", ok)
    p8.fetch("https://example.test/a")
    # the second fetch right after the first must sleep to keep the gap
    p8.fetch("https://example.test/b")
    assert len(sleeps) == 1
    assert sleeps[0] >= 0.45
