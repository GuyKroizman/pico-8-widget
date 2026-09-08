"""Tests for pool refresh, pruning and detail caching."""

from conftest import fixture

import p8


def seed_pool(n, first_seen="2026-01-01"):
    """Write a pool with n minimal carts (tids 1..n)."""
    carts = {}
    for i in range(1, n + 1):
        carts[str(i)] = {
            "tid": i, "title": f"game {i}", "author": "a", "cart_id": f"c{i}",
            "thumb": "", "created": "", "first_seen": first_seen,
        }
    p8.save_json(p8.pool_file(), {"carts": carts})
    return carts


# ---------------------------------------------------------------------------
# refresh_pool
# ---------------------------------------------------------------------------

def test_first_refresh_adds_only_playable_non_wip_carts(fixed_today, fake_fetch):
    calls = fake_fetch(fixture("listing.html"))
    result = p8.refresh_pool()
    assert result["ok"] and result["refreshed"]
    assert result["added"] == 2  # rows 0 and 2; WIP + thread rows skipped
    pool = p8.load_json(p8.pool_file(), {})["carts"]
    assert set(pool.keys()) == {"159011", "158976"}
    assert pool["158976"]["title"] == "Boxed Apart"
    assert calls and calls[0].endswith("orderby=lucky&page=1")


def test_refresh_skips_when_done_today(fixed_today, fake_fetch):
    seed_pool(20)  # >= 20 carts: the bootstrap threshold
    p8.save_json(p8.state_file(), {"last_refresh": "2026-09-02"})
    calls = fake_fetch("")  # would blow up only if reached
    result = p8.refresh_pool()
    assert result == {"ok": True, "refreshed": False, "size": 20}
    assert calls == []


def test_forced_refresh_merges_new_carts(fixed_today, fake_fetch):
    seed_pool(20)
    calls = fake_fetch(fixture("listing.html"))
    result = p8.refresh_pool(force=True)
    assert result["added"] == 2
    pool = p8.load_json(p8.pool_file(), {})["carts"]
    assert len(pool) == 22
    assert len(calls) == 1  # fixture page has < 30 rows -> no second page


def test_prune_drops_oldest_and_keeps_bookmarks(fixed_today, fake_fetch):
    carts = seed_pool(p8.POOL_CAP + 3, first_seen="2026-01-01")
    # give the three oldest tids distinct, oldest-first dates
    for i, tid in enumerate(("1", "2", "3")):
        carts[tid]["first_seen"] = f"2026-01-{i + 1:02d}"
    # bookmark the very oldest cart (tid 1): it must survive pruning
    p8.save_json(p8.favs_file(), {"favorites": [
        {"tid": 1, "title": "game 1", "added": "2026-01-01"}]})
    # fake covers for the oldest carts
    import os
    os.makedirs(p8.thumbs_dir(), exist_ok=True)
    for tid in ("1", "2", "3"):
        open(os.path.join(p8.thumbs_dir(), tid + ".png"), "wb").close()

    fake_fetch("")  # no rows on the lucky pages; prune still runs
    result = p8.refresh_pool(force=True)

    assert result["size"] == p8.POOL_CAP
    pool = p8.load_json(p8.pool_file(), {})["carts"]
    assert "1" in pool            # bookmarked oldest kept
    assert "2" not in pool        # dropped
    assert "3" not in pool
    thumbs = os.listdir(p8.thumbs_dir())
    assert "1.png" in thumbs      # bookmark cover kept
    assert "2.png" not in thumbs  # dropped cart's cover removed
    assert "3.png" not in thumbs


# ---------------------------------------------------------------------------
# detail caching
# ---------------------------------------------------------------------------

def test_ensure_detail_fetches_once_then_caches(fake_fetch):
    pool = {"carts": {"1": {"tid": 1, "title": "g", "author": "", "cart_id": "c",
                            "thumb": "", "created": ""}}}
    calls = fake_fetch(fixture("cart_page_modern.html"))
    p8.ensure_detail(pool, 1)
    p8.ensure_detail(pool, 1)
    assert len(calls) == 1  # second call served from cache
    assert "In short: traverse the maze" in pool["carts"]["1"]["desc"]


def test_ensure_thumb_downloads_once(fake_fetch):
    calls = fake_fetch(b"\x89PNG fake")
    entry = {"tid": 7, "thumb": "/bbs/thumbs/pico8_x-0.png"}
    path = p8.ensure_thumb(entry)
    assert path.endswith("thumbs/7.png")
    assert p8.ensure_thumb(entry) == path
    assert len(calls) == 1
    assert open(path, "rb").read() == b"\x89PNG fake"


def test_ensure_thumb_failure_returns_empty(monkeypatch):
    def boom(url, **kwargs):
        raise RuntimeError("no network")

    monkeypatch.setattr(p8, "fetch", boom)
    assert p8.ensure_thumb({"tid": 7, "thumb": "/bbs/thumbs/pico8_x-0.png"}) == ""


def test_ensure_thumb_refuses_unsafe_values(monkeypatch):
    """Covers come from remote data, so only safe relative /bbs/thumbs/ paths
    may ever reach the network."""

    def boom(url, **kwargs):
        raise AssertionError(f"fetch must never be called with {url!r}")

    monkeypatch.setattr(p8, "fetch", boom)
    bad = [
        "https://evil.example.com/x.png",        # absolute off-origin URL
        "http://www.lexaloffle.com/bbs/thumbs/x.png",
        "//evil.example.com/bbs/thumbs/x.png",   # protocol-relative
        "/bbs/thumbs/../../etc/passwd",          # traversal
        "/bbs/thumbs/x.png?u=1",                 # query/fragment tricks
        "/other/path.png",                       # not a thumbnail path
        "x.png",                                 # not a path at all
        "https://user:pass@www.lexaloffle.com/bbs/thumbs/x.png",
    ]
    for thumb in bad:
        assert p8.ensure_thumb({"tid": 1, "thumb": thumb}) == ""
    assert p8.ensure_thumb({"tid": 2, "thumb": ""}) == ""


def test_ensure_thumb_accepts_real_lexaloffle_path(fake_fetch):
    calls = fake_fetch(b"\x89PNG ok")
    path = p8.ensure_thumb({"tid": 9, "thumb": "/bbs/thumbs/pico8_rockhound-4.png"})
    assert path.endswith("thumbs/9.png")
    assert calls == ["https://www.lexaloffle.com/bbs/thumbs/pico8_rockhound-4.png"]
