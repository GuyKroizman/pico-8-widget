"""Tests for bookmarks (favorites)."""

import p8


def test_add_and_list(fixed_today, monkeypatch):
    p8.favorite_add(158939, "Rockhound")  # added 2026-09-02

    class NextDay:
        @classmethod
        def today(cls):
            return cls()

        @classmethod
        def isoformat(cls):
            return "2026-09-03"

    monkeypatch.setattr(p8, "date", NextDay)
    p8.favorite_add(47124, "Something Else")  # added 2026-09-03

    result = p8.favorite_list()
    assert result["ok"] is True
    tids = [fav["tid"] for fav in result["favorites"]]
    assert tids == [47124, 158939]  # newest first


def test_add_is_idempotent():
    p8.favorite_add(158939, "Rockhound")
    p8.favorite_add(158939, "Rockhound")
    assert len(p8.favorite_list()["favorites"]) == 1


def test_remove(fixed_today):
    p8.favorite_add(158939, "Rockhound")
    result = p8.favorite_remove(158939)
    assert result["favorites"] == []
    assert p8.favorite_remove(158939)["ok"] is True  # removing again is fine


def test_invalid_tid_rejected():
    result = p8.favorite_add("not-a-number", "X")
    assert result["ok"] is False
    assert p8.favorite_list()["favorites"] == []
    assert p8.favorite_remove("nope")["ok"] is False


def test_persisted_to_disk(fixed_today):
    p8.favorite_add(158939, "Rockhound")
    # a fresh read from disk (no in-memory state anywhere) sees the bookmark
    assert [f["tid"] for f in p8._favorites()["favorites"]] == [158939]
