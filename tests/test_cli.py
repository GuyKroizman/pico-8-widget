"""Tests for the p8.py command-line entry point."""

import json
import sys

import pytest

from conftest import fixture

import p8


def run_cli(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["p8.py", *argv])
    rc = p8.main()
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_unknown_command_fails(monkeypatch, capsys):
    rc, payload = run_cli(monkeypatch, capsys, "explode")
    assert rc == 1
    assert payload == {"ok": False, "error": "unknown command: explode"}


def test_no_command_fails(monkeypatch, capsys):
    rc, payload = run_cli(monkeypatch, capsys)
    assert rc == 1
    assert payload["ok"] is False


def test_pick_empty_pool_reports_error(monkeypatch, capsys, fixed_today):
    rc, payload = run_cli(monkeypatch, capsys, "pick")
    assert rc == 1
    assert payload == {"ok": False, "error": "pool empty"}


def test_favorite_roundtrip_through_cli(monkeypatch, capsys, fixed_today):
    rc, payload = run_cli(monkeypatch, capsys, "favorite", "add", "158939", "Rockhound")
    assert rc == 0 and payload["ok"] is True
    rc, payload = run_cli(monkeypatch, capsys, "favorite", "list")
    assert [f["tid"] for f in payload["favorites"]] == [158939]


def test_pick_bad_roll_argument_fails(monkeypatch, capsys, fixed_today):
    with pytest.raises(ValueError):
        run_cli(monkeypatch, capsys, "pick", "--roll", "abc")


def test_refresh_and_refresh_now_through_cli(monkeypatch, capsys, fixed_today, fake_fetch):
    fake_fetch(fixture("listing.html"))
    rc, payload = run_cli(monkeypatch, capsys, "refresh")
    assert rc == 0 and payload["refreshed"] is True
    rc, payload = run_cli(monkeypatch, capsys, "refresh-now")
    assert rc == 0 and payload["ok"] is True


def test_pick_through_cli_prints_game(monkeypatch, capsys, fixed_today, fake_fetch):
    import p8 as p8mod
    carts = {
        str(i): {"tid": i, "title": f"g{i}", "author": "a", "cart_id": f"c{i}",
                 "thumb": "", "created": "", "first_seen": "2026-01-01",
                 "desc": f"description of game {i}"}
        for i in range(1, 6)
    }
    p8mod.save_json(p8mod.pool_file(), {"carts": carts})
    fake_fetch(b"")  # never reached
    rc, payload = run_cli(monkeypatch, capsys, "pick")
    assert rc == 0 and payload["ok"] is True
    assert payload["pool_size"] == 5


def test_favorite_remove_and_usage_through_cli(monkeypatch, capsys, fixed_today):
    run_cli(monkeypatch, capsys, "favorite", "add", "1", "game one")
    rc, payload = run_cli(monkeypatch, capsys, "favorite", "remove", "1")
    assert rc == 0 and payload["favorites"] == []
    rc, payload = run_cli(monkeypatch, capsys, "favorite", "frobnicate")
    assert rc == 0 and payload["ok"] is False
