"""Tests for the deterministic daily pick and state restoration."""

from conftest import fixture

import p8


def seed_pool(n):
    """Write a pool of n carts (tids 1..n) with descriptions pre-cached, so
    the pick itself performs no network access."""
    carts = {}
    for i in range(1, n + 1):
        carts[str(i)] = {
            "tid": i, "title": f"game {i}", "author": "a", "cart_id": f"c{i}",
            "thumb": "", "created": "", "first_seen": "2026-01-01",
            "desc": f"description of game {i}",
        }
    p8.save_json(p8.pool_file(), {"carts": carts})
    return carts


def pick_tid(pick):
    return pick["tid"]


def test_empty_pool_returns_none(fixed_today):
    assert p8.compute_pick(0) is None


def test_pick_is_deterministic(fixed_today):
    seed_pool(10)
    assert pick_tid(p8.compute_pick(0)) == pick_tid(p8.compute_pick(0))


def test_different_rolls_pick_different_games(fixed_today):
    seed_pool(10)
    first = pick_tid(p8.compute_pick(0))
    second = pick_tid(p8.compute_pick(1))
    assert first != second  # roll 1 excludes the roll-0 game via "recent"


def test_pick_remembers_recent(fixed_today):
    seed_pool(10)
    first = pick_tid(p8.compute_pick(0))
    state = p8.load_json(p8.state_file(), {})
    assert first in [int(t) for t in state.get("recent", [])]


def test_plain_pick_restores_last_roll(fixed_today):
    seed_pool(10)
    rolled = p8.compute_pick(2)
    restored = p8.compute_pick(None)  # e.g. a widget restart mid-day
    assert restored["roll"] == 2
    assert pick_tid(restored) == pick_tid(rolled)


def test_plain_pick_without_state_starts_at_roll_zero(fixed_today):
    seed_pool(10)
    pick = p8.compute_pick(None)
    assert pick["roll"] == 0


def test_roll_resets_on_new_day(monkeypatch):
    seed_pool(10)
    p8.save_json(p8.state_file(), {
        "pick": {"date": "2026-09-01", "roll": 5, "tid": 3},
        "last_roll": 5,
        "recent": [3],
    })

    class DayTwo:
        @classmethod
        def today(cls):
            return cls()

        @classmethod
        def isoformat(cls):
            return "2026-09-02"

    monkeypatch.setattr(p8, "date", DayTwo)
    pick = p8.compute_pick(None)
    assert pick["roll"] == 0  # a fresh day starts at the first roll
    assert pick["tid"] != 3   # yesterday's pick still sits in "recent"
    state = p8.load_json(p8.state_file(), {})
    assert state["last_roll"] == 0
    assert state["pick"]["date"] == "2026-09-02"


def test_recent_games_are_not_re_picked_until_pool_exhausted(fixed_today):
    seed_pool(3)
    picks = {pick_tid(p8.compute_pick(roll)) for roll in range(6)}
    # with 3 carts and a recent buffer, all three must still appear over time
    assert picks == {1, 2, 3}


def test_pick_output_shape(fixed_today, fake_fetch):
    seed_pool(5)
    fake_fetch(b"")  # never actually reached (desc + no thumb needed)
    result = p8.compute_pick(0)
    assert result["tid"] in range(1, 6)
    assert result["date"] == "2026-09-02"
    assert result["roll"] == 0
    assert result["url"] == f"https://www.lexaloffle.com/bbs/?tid={result['tid']}"
    assert result["description"].startswith("description of game")
    assert result["favorite"] is False
    assert result["pool_size"] == 5


def test_pick_is_golden(fixed_today):
    """Golden test: for a fixed pool and date, the seeded pick is fully
    deterministic down to the exact game. Guards the seed string, the sort
    order and the choice mechanism against accidental changes."""
    seed_pool(5)
    assert pick_tid(p8.compute_pick(0)) == 3
    assert pick_tid(p8.compute_pick(1)) == 2
    assert pick_tid(p8.compute_pick(2)) == 1


def test_path_helpers(fixed_today):
    """Pure path helpers must keep their file names (kills trivial string
    mutations in them)."""
    assert p8.pool_file().endswith("pool.json")
    assert p8.state_file().endswith("state.json")
    assert p8.favs_file().endswith("favs.json")
    assert p8.thumbs_dir().endswith("thumbs")
    assert p8.pool_file().startswith(str(p8.DATA_DIR))


def test_cached_pick_resyncs_stale_last_roll(fixed_today):
    seed_pool(5)
    # state says roll 2 / tid 3 but last_roll drifted; an explicit roll 2
    # request must serve the cache and repair last_roll.
    p8.save_json(p8.state_file(), {
        "pick": {"date": "2026-09-02", "roll": 2, "tid": 3},
        "last_roll": 9,
        "recent": [],
    })
    result = p8.compute_pick(2)
    assert result["tid"] == 3
    state = p8.load_json(p8.state_file(), {})
    assert state["last_roll"] == 2


def test_pick_survives_detail_fetch_failure(fixed_today, monkeypatch):
    seed_pool(3)
    # remove the cached description of tid 2 so the pick must fetch it
    pool = p8.load_json(p8.pool_file(), {})
    del pool["carts"]["2"]["desc"]
    p8.save_json(p8.pool_file(), pool)
    p8.save_json(p8.state_file(), {
        "pick": {"date": "2026-09-02", "roll": 0, "tid": 2},
        "last_roll": 0,
        "recent": [],
    })

    def down(url):
        raise RuntimeError("no network")

    monkeypatch.setattr(p8, "fetch", down)
    result = p8.compute_pick(None)
    assert result["tid"] == 2
    assert result["description"] == ""  # graceful degradation, no crash


def test_pick_survives_pool_save_failure(fixed_today, monkeypatch):
    seed_pool(3)
    original = p8.save_json

    def save_json_fails_for_pool(path, obj):
        if path == p8.pool_file():
            raise OSError("disk full")
        return original(path, obj)

    monkeypatch.setattr(p8, "save_json", save_json_fails_for_pool)
    result = p8.compute_pick(0)
    assert result["tid"] in range(1, 4)
    assert result["pool_size"] == 3


def test_pick_flags_bookmarked_game(fixed_today):
    seed_pool(5)
    picked = p8.compute_pick(0)
    p8.favorite_add(picked["tid"], picked["title"])
    again = p8.compute_pick(0)
    assert again["favorite"] is True


def test_pick_can_create_missing_pool_entry(fixed_today, fake_fetch):
    """A cached pick whose cart vanished from the pool re-fetches its detail
    and recreates a (minimal) entry instead of dying."""
    seed_pool(3)
    p8.save_json(p8.state_file(), {
        "pick": {"date": "2026-09-02", "roll": 0, "tid": 999},
        "last_roll": 0,
        "recent": [],
    })
    calls = fake_fetch(fixture("cart_page_modern.html"))
    result = p8.compute_pick(None)
    assert result["tid"] == 999
    assert "In short: traverse the maze" in result["description"]
    pool = p8.load_json(p8.pool_file(), {})
    assert "999" in pool["carts"]
    assert calls


def test_pick_missing_entry_with_failed_fetch(fixed_today, monkeypatch):
    seed_pool(3)
    p8.save_json(p8.state_file(), {
        "pick": {"date": "2026-09-02", "roll": 0, "tid": 999},
        "last_roll": 0,
        "recent": [],
    })

    def down(url):
        raise RuntimeError("no network")

    monkeypatch.setattr(p8, "fetch", down)
    result = p8.compute_pick(None)
    assert result["tid"] == 999
    assert result["description"] == ""
    assert result["title"] == ""
