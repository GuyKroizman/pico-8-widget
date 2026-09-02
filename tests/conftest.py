"""Shared pytest fixtures for the p8.py helper.

p8.py is a single module at the repo root; it keeps its state under a
module-level DATA_DIR, so every test gets a private, empty temp dir and a
fixed "today" when it needs one. Network access is never allowed in tests:
p8.fetch is faked wherever a test could reach it.
"""

import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import p8  # noqa: E402

FIXED_TODAY = "2026-09-02"
FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    """Read a fixture file from tests/fixtures."""
    with open(os.path.join(FIXTURES, name), "r", encoding="utf-8") as handle:
        return handle.read()


class _FakeDate:
    """Stand-in for datetime.date with a fixed, frozen 'today'."""

    @classmethod
    def today(cls):
        return cls()

    @classmethod
    def isoformat(cls):
        return FIXED_TODAY


@pytest.fixture(autouse=True)
def isolated_data(tmp_path, monkeypatch):
    """Every test gets its own empty data dir and no network pacing."""
    monkeypatch.setattr(p8, "DATA_DIR", str(tmp_path))
    monkeypatch.setattr(p8, "REQUEST_GAP", 0.0)


@pytest.fixture
def fixed_today(monkeypatch):
    """Freeze p8's clock at FIXED_TODAY."""
    monkeypatch.setattr(p8, "date", _FakeDate)
    return FIXED_TODAY


@pytest.fixture
def fake_fetch(monkeypatch):
    """Replace p8.fetch. Install a canned body (bytes/str) or a callable;
    returns the recorder list of requested URLs."""

    def install(body=b""):
        calls = []

        def fetch(url):
            calls.append(url)
            if callable(body):
                return body(url)
            if isinstance(body, str):
                return body.encode("utf-8")
            return body if body is not None else b""

        monkeypatch.setattr(p8, "fetch", fetch)
        return calls

    return install
