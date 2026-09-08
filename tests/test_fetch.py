"""Tests for fetch() retry behaviour — without touching the network."""

import pytest

import p8


class _Response:
    """Minimal fake urlopen response: consuming read(), optional headers and
    an optional tracker of how many bytes were handed out."""

    def __init__(self, body=b"", headers=None, delivered=None):
        self._body = body
        self._pos = 0
        self.headers = headers or {}
        self._delivered = delivered

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, size=-1):
        if size is None or size < 0:
            size = len(self._body) - self._pos
        data = self._body[self._pos:self._pos + size]
        self._pos += len(data)
        if self._delivered is not None:
            self._delivered.append(len(data))
        return data


def test_fetch_retries_then_succeeds(monkeypatch):
    calls = {"n": 0}

    def flaky(request, timeout=None):
        calls["n"] += 1
        if calls["n"] < p8.REQUEST_RETRIES:  # fail on every attempt but the last
            raise OSError("connection reset")
        return _Response(b"ok")

    monkeypatch.setattr(p8.urllib.request, "urlopen", flaky)
    monkeypatch.setattr(p8.time, "sleep", lambda _s: None)  # no real waiting
    assert p8.fetch("https://example.test/x") == b"ok"
    assert calls["n"] == p8.REQUEST_RETRIES


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


def _urlopen_for(monkeypatch, factory):
    """Install urlopen returning a fresh response per attempt; silence retry
    sleeps so the test runs instantly."""
    monkeypatch.setattr(p8.time, "sleep", lambda _s: None)

    def urlopen(request, timeout=None):
        return factory()

    monkeypatch.setattr(p8.urllib.request, "urlopen", urlopen)


def test_declared_oversized_response_refused_without_reading(monkeypatch):
    """A Content-Length above the cap is refused before any bytes are read."""
    delivered = []

    def make():
        return _Response(body=b"x" * 1000,
                         headers={"Content-Length": str(p8.MAX_PAGE_BYTES + 1)},
                         delivered=delivered)

    _urlopen_for(monkeypatch, make)
    with pytest.raises(RuntimeError, match="refused: declared"):
        p8.fetch("https://example.test/big")
    assert delivered == []  # the body was never touched


def test_chunked_oversized_response_aborted_at_cap(monkeypatch):
    """A body without a declared length is streamed and aborted the moment the
    cap is crossed — the full body is never buffered."""
    limit = 1000
    delivered = []
    full_body = b"x" * (100 * 1024)  # 100 KB body vs a 1 KB cap

    def make():
        return _Response(body=full_body, delivered=delivered)

    _urlopen_for(monkeypatch, make)
    with pytest.raises(RuntimeError, match="exceeds limit"):
        p8.fetch("https://example.test/huge", limit=limit)
    # every attempt aborts just past the cap; the retained/read amount stays
    # tiny compared to the 100 KB body
    assert sum(delivered) <= p8.REQUEST_RETRIES * (limit + 1)
    assert sum(delivered) < len(full_body) // 10


def test_response_at_exact_limit_is_accepted(monkeypatch):
    limit = 1000
    delivered = []

    def make():
        return _Response(body=b"x" * limit, delivered=delivered)

    _urlopen_for(monkeypatch, make)
    body = p8.fetch("https://example.test/exact", limit=limit)
    assert body == b"x" * limit
    assert sum(delivered) == limit


def test_small_chunked_body_below_limit_is_accepted(monkeypatch):
    delivered = []

    def make():
        return _Response(body=b"hello world", delivered=delivered)

    _urlopen_for(monkeypatch, make)
    assert p8.fetch("https://example.test/small", limit=1000) == b"hello world"
