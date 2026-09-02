#!/usr/bin/env python3
"""
p8.py - data helper for the PICO-8 Widget (Omarchy bar plugin).

The Lexaloffle BBS has no official API or feed, so this script talks to its
public pages and parses the `pdat=[...]` JavaScript blob each listing embeds.
All state lives on disk under the XDG data dir, keeping the QML widget
stateless:

    <data>/pool.json   - the "lucky + memory" pool of seen carts + descriptions
    <data>/state.json  - today's pick, roll counter, recent picks, last refresh
    <data>/favs.json   - bookmarked games
    <data>/thumbs/     - downloaded cover images

Every command prints exactly one JSON object on stdout, e.g.:

    python3 p8.py refresh                 # pull lucky pages into the pool
    python3 p8.py pick                    # today's game (restores current state)
    python3 p8.py pick --roll 3           # roll N for today (the "another" button)
    python3 p8.py favorite list
    python3 p8.py favorite add 158939 "Rockhound"
    python3 p8.py favorite remove 158939

Network etiquette (the site is a small hobby server):
  * one request per >=0.9s, globally paced
  * retries with backoff on failure
  * everything fetched once is cached forever
"""

import fcntl
import html
import json
import os
import random
import re
import sys
import time
import urllib.request
from datetime import date

# ---------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------

BASE = "https://www.lexaloffle.com"
LIST_URL = BASE + "/bbs/?cat=7&sub=3&mode=carts&orderby=lucky&page={page}"
TID_URL = BASE + "/bbs/?tid={tid}"

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) p8-daily-widget/1.0"
REQUEST_GAP = 0.9      # minimum seconds between network requests
REQUEST_TIMEOUT = 25   # seconds before a request is abandoned
REQUEST_RETRIES = 3    # attempts per URL before giving up
POOL_CAP = 2500        # max carts remembered at once
RECENT_MAX = 30        # picks remembered so they are not repeated too soon
DESC_MAX = 6000        # description length cap, in characters
LUCKY_PAGES = (1, 2)   # how many lucky pages to pull per refresh

DATA_DIR = os.environ.get("P8_DATA_DIR") or os.path.join(
    os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share"),
    # Deliberately NOT "pico-8": that directory is the real PICO-8 install's
    # own data dir (pico8.dat, carts/, ...). Plugin state gets its own
    # namespaced folder instead.
    "guy.pico-8-widget",
)

_last_request_at = 0.0


# ---------------------------------------------------------------------------
# paths + atomic disk helpers
# ---------------------------------------------------------------------------

def pool_file():
    return os.path.join(DATA_DIR, "pool.json")


def state_file():
    return os.path.join(DATA_DIR, "state.json")


def favs_file():
    return os.path.join(DATA_DIR, "favs.json")


def thumbs_dir():
    return os.path.join(DATA_DIR, "thumbs")


def load_json(path, default):
    """Read JSON, returning `default` when the file is missing or corrupt."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return default


def save_json(path, obj):
    """Write JSON atomically (temp file + rename) so readers never see a
    half-written state."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=1)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


class FileLock:
    """Advisory cross-process lock so concurrent helper runs cannot corrupt
    the JSON files. Used as a context manager."""

    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self._handle = open(path, "w")
        fcntl.flock(self._handle, fcntl.LOCK_EX)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        fcntl.flock(self._handle, fcntl.LOCK_UN)
        self._handle.close()


def emit(obj):
    """Print one JSON object on stdout (the widget parses this)."""
    print(json.dumps(obj, ensure_ascii=False))


# ---------------------------------------------------------------------------
# network
# ---------------------------------------------------------------------------

def fetch(url):
    """GET with pacing, a UA header and a few gentle retries."""
    global _last_request_at
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    for attempt in range(REQUEST_RETRIES):
        wait = REQUEST_GAP - (time.time() - _last_request_at)
        if wait > 0:
            time.sleep(wait)
        try:
            with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
                body = response.read()
            _last_request_at = time.time()
            return body
        except Exception as exc:  # noqa: BLE001 - keep the widget alive
            _last_request_at = time.time()
            if attempt == REQUEST_RETRIES - 1:
                raise RuntimeError(f"GET {url} failed: {exc}") from exc
            time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"GET {url} failed")  # pragma: no cover


# ---------------------------------------------------------------------------
# pdat parser
#
# Listing pages embed their rows in a JavaScript array that is *almost* JSON:
# strings may be backtick-quoted and contain raw text, empty fields appear as
# nothing at all ("a,,b"), and tags are nested arrays. This is a tiny
# recursive-descent parser for exactly that shape.
# ---------------------------------------------------------------------------

def _skip(s, i):
    """Advance past whitespace."""
    while i < len(s) and s[i] in " \t\r\n":
        i += 1
    return i


def _bare(s, i):
    """Parse an unquoted token (number or bare word; empty between commas)."""
    j = i
    while j < len(s) and s[j] not in ",] \t\r\n":
        j += 1
    token = s[i:j].strip()
    if token == "":
        return "", j
    if re.fullmatch(r"-?\d+", token):
        return int(token), j
    try:
        return float(token), j
    except ValueError:
        return token, j


def _string(s, i):
    """Parse a quoted string; handles ' " ` quoting and backslash escapes."""
    quote = s[i]
    i += 1
    out = []
    while i < len(s):
        char = s[i]
        if char == quote:
            return "".join(out), i + 1
        if char == "\\" and i + 1 < len(s):
            nxt = s[i + 1]
            if nxt == "u" and i + 5 < len(s):  # \uXXXX escape
                out.append(chr(int(s[i + 2:i + 6], 16)))
                i += 6
                continue
            out.append(nxt)
            i += 2
            continue
        out.append(char)
        i += 1
    return "".join(out), i


def _value(s, i):
    """Parse one value: an array, a string, or a bare token."""
    i = _skip(s, i)
    if i >= len(s):
        return None, i
    char = s[i]
    if char == "[":
        i += 1
        arr = []
        while True:
            i = _skip(s, i)
            if i >= len(s):
                break
            if s[i] == "]":
                return arr, i + 1
            value, i = _value(s, i)
            arr.append(value)
            i = _skip(s, i)
            if i < len(s) and s[i] == ",":
                i += 1
    elif char in "'\"`":
        return _string(s, i)
    else:
        return _bare(s, i)
    return None, i


def parse_pdat(html_text):
    """Return the list of rows from a page's embedded `pdat=[...]` blob."""
    start = html_text.find("pdat=[")
    if start < 0:
        return []
    rows, _ = _value(html_text, start + 5)  # index of the '[' opening the array
    return rows if isinstance(rows, list) else []


# ---------------------------------------------------------------------------
# cart rows -> pool entries
# ---------------------------------------------------------------------------

def row_to_cart(row):
    """Map one pdat row onto the fields we care about.

    Returns None for anything that must never be recommended: posts that are
    not playable carts, carts without an id, and unfinished ("WIP") work.
    """
    if not isinstance(row, list) or len(row) < 23:
        return None

    flags = row[19]
    cart_id = str(row[22] or "").strip()
    if not (isinstance(flags, int) and (flags & 2)):  # bit 1: "show as cart"
        return None
    if not cart_id:
        return None

    title = html.unescape(str(row[2] or "")).strip()
    if not title:
        return None

    tags = {str(tag).lower() for tag in (row[18] or []) if tag}
    haystack = (title + " " + cart_id).lower()
    if "wip" in tags or "wip" in haystack or "work in progress" in haystack:
        return None  # unfinished carts never get recommended

    return {
        "tid": int(row[1]),
        "title": title,
        "author": html.unescape(str(row[8] or "")).strip(),
        "cart_id": cart_id,
        "thumb": str(row[3] or "").strip(),
        "created": str(row[6] or "").strip(),
    }


def refresh_pool(force=False):
    """Pull a couple of lucky pages into the memory pool.

    Runs at most once per day (unless forced); merges new carts in, prunes
    the oldest ones past POOL_CAP (bookmarks are never dropped).
    """
    with FileLock(pool_file() + ".lock"):
        pool = load_json(pool_file(), {})
        if not isinstance(pool, dict) or "carts" not in pool:
            pool = {"carts": {}}
        state = load_json(state_file(), {})
        today = date.today().isoformat()

        if not force and state.get("last_refresh") == today and len(pool["carts"]) >= 20:
            return {"ok": True, "refreshed": False, "size": len(pool["carts"])}

        before = len(pool["carts"])
        added = 0
        # The lucky sort has no stable page count, so stop at the first page
        # that comes back empty or short.
        for page in LUCKY_PAGES:
            html_text = fetch(LIST_URL.format(page=page)).decode("utf-8", "replace")
            rows = parse_pdat(html_text)
            if not rows:
                break
            for row in rows:
                cart = row_to_cart(row)
                if cart and cart["tid"] not in pool["carts"]:
                    cart["first_seen"] = today
                    pool["carts"][str(cart["tid"])] = cart
                    added += 1
            if len(rows) < 30:  # last page reached
                break

        # Prune the oldest carts (bookmarks are never dropped) and remove
        # their cached covers so storage stays bounded.
        carts = pool["carts"]
        fav_tids = {str(fav["tid"]) for fav in _favorites()["favorites"]}
        dropped = []
        over = len(carts) - POOL_CAP
        for tid in sorted(carts, key=lambda key: carts[key].get("first_seen", "")):
            if over <= 0:
                break
            if tid not in fav_tids:
                del carts[tid]
                dropped.append(tid)
                over -= 1
        for tid in dropped:
            try:
                os.remove(os.path.join(thumbs_dir(), tid + ".png"))
            except OSError:
                pass

        state["last_refresh"] = today
        save_json(state_file(), state)
        save_json(pool_file(), pool)
        return {
            "ok": True,
            "refreshed": True,
            "added": added,
            "size": len(carts),
            "before": before,
        }


# ---------------------------------------------------------------------------
# cart detail: description + cover (fetched once, cached forever)
# ---------------------------------------------------------------------------

def extract_description(html_text):
    """Pull the first-post description text out of a cart's BBS page."""
    page = re.sub(
        r"(?is)<script.*?</script>|<style.*?</style>|<textarea.*?</textarea>",
        " ",
        html_text,
    )

    # Everything before the comments anchor belongs to the opening post.
    cut = page.find("id=comments")
    if cut >= 0:
        page = page[:cut]

    # The embed/code instruction ends the player chrome, and the description
    # paragraphs come right after it. Newer pages always carry this marker;
    # older ones (or carts that disallow embedding) don't, so fall back to
    # the whole region and filter chrome lines out below.
    marker = page.rfind("Copy and paste the snippet below")
    if marker >= 0:
        page = page[marker:]

    # Tag chips: <a ...#tag=...><span class="tag">...</span></a>
    page = re.sub(r"(?is)<a[^>]*#tag=[^>]*>.*?</a>", " ", page)

    lines = []
    for line in html.unescape(re.sub(r"<[^>]+>", "\n", page)).splitlines():
        line = " ".join(line.split())
        if line:
            lines.append(line)

    for i, line in enumerate(lines):
        if "Copy and paste the snippet below" in line:
            lines = lines[i + 1:]
            break

    # Drop chrome that survives the tag/chip removal: player notices,
    # license rows, rate-button digits, tag-marker fragments cut by the
    # comments anchor.
    chrome = {
        "code", "embed", "no license", "mark as spam", "mark as abuse",
        "pin to profile", "link will be included instead.",
        "copy and paste the snippet below into your html.",
    }
    clean = []
    for line in lines:
        line = line.replace("<br", " ").replace("</p", " ").replace("</div", " ")
        line = " ".join(line.split())
        if not line:
            continue
        lower = line.lower()
        if lower in chrome or lower.startswith("note: this cartridge's settings"):
            continue
        if re.fullmatch(r"[\d\s,.•\-]+", line):  # bare like-count leftovers
            continue
        clean.append(line)

    # Old pages strip into a wall of tiny lines; collapse those into prose.
    description = "\n".join(clean)
    if len(clean) > 40:
        description = re.sub(r"\n+", " ", description)
    return description[:DESC_MAX].strip()


def ensure_detail(pool, tid):
    """Fetch and cache the description for one cart; returns the pool."""
    key = str(tid)
    entry = pool["carts"].get(key)
    if entry is None or not entry.get("desc"):
        page = fetch(TID_URL.format(tid=tid)).decode("utf-8", "replace")
        if entry is None:
            entry = {"tid": tid, "title": "", "author": "", "cart_id": "", "thumb": ""}
            pool["carts"][key] = entry
        entry["desc"] = extract_description(page)
    return pool


def ensure_thumb(entry):
    """Download the cover once; returns an absolute local path ("" on failure)."""
    rel = entry.get("thumb") or ""
    path = os.path.join(thumbs_dir(), str(entry["tid"]) + ".png")
    if not os.path.exists(path) and rel:
        os.makedirs(thumbs_dir(), exist_ok=True)
        try:
            body = fetch(BASE + rel if rel.startswith("/") else rel)
            with open(path, "wb") as handle:
                handle.write(body)
        except RuntimeError:
            return ""
    return path if os.path.exists(path) else ""


# ---------------------------------------------------------------------------
# the daily pick
# ---------------------------------------------------------------------------

def compute_pick(roll=None):
    """Deterministic per-(date, roll) pick over the sorted pool.

    roll=None restores the day's current state: the roll most recently used
    today (so a shell restart keeps showing the same game), or 0 if the day
    rolled over.
    """
    with FileLock(pool_file() + ".lock"):
        pool = load_json(pool_file(), {})
        if not isinstance(pool, dict) or "carts" not in pool:
            pool = {"carts": {}}
        state = load_json(state_file(), {})
        today = date.today().isoformat()
        fav_tids = {int(fav["tid"]) for fav in _favorites()["favorites"]}
        pick = state.get("pick")

        if roll is None:
            same_day = isinstance(pick, dict) and pick.get("date") == today
            roll = state.get("last_roll", 0) if same_day else 0

        if (isinstance(pick, dict) and pick.get("date") == today
                and pick.get("roll") == roll and pick.get("tid")):
            tid = int(pick["tid"])
        else:
            candidates = sorted(pool["carts"].values(), key=lambda cart: int(cart["tid"]))
            recent = {int(tid) for tid in state.get("recent", [])}
            fresh = [cart for cart in candidates if int(cart["tid"]) not in recent]
            fresh = fresh or candidates
            if not fresh:
                state["pick"] = {"date": today, "roll": roll, "tid": None}
                save_json(state_file(), state)
                return None

            chosen = random.Random(f"{today}#{roll}").choice(fresh)
            tid = int(chosen["tid"])
            recent = [tid] + [int(t) for t in state.get("recent", [])]
            state["pick"] = {"date": today, "roll": roll, "tid": tid}
            state["last_roll"] = roll
            state["recent"] = recent[:RECENT_MAX]
            save_json(state_file(), state)

        if state.get("last_roll") != roll:
            state["last_roll"] = roll
            save_json(state_file(), state)

        # Description and cover are nice-to-haves; a fetch failure must not
        # kill the pick.
        try:
            pool = ensure_detail(pool, tid)
        except RuntimeError:
            pass
        try:
            save_json(pool_file(), pool)
        except OSError:
            pass

        entry = pool["carts"].get(str(tid)) or {"tid": tid, "title": "", "desc": ""}
        return {
            "date": today,
            "roll": roll,
            "tid": tid,
            "title": entry.get("title", ""),
            "description": entry.get("desc", "") or "",
            "thumb": ensure_thumb(entry),
            "url": TID_URL.format(tid=tid),
            "favorite": tid in fav_tids,
            "pool_size": len(pool["carts"]),
        }


# ---------------------------------------------------------------------------
# favorites (bookmarks)
# ---------------------------------------------------------------------------

def _favorites():
    """Load the favorites document; always returns {"favorites": [...]}."""
    data = load_json(favs_file(), {})
    if not isinstance(data, dict) or "favorites" not in data:
        data = {"favorites": []}
    return data


def _favorite_list_sorted():
    """Favorites newest-first for display."""
    favorites = _favorites()["favorites"]
    return sorted(favorites, key=lambda fav: fav.get("added", ""), reverse=True)


def favorite_add(tid, title):
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"invalid tid: {tid!r}"}
    with FileLock(favs_file() + ".lock"):
        data = _favorites()
        favorites = data["favorites"]
        if not any(int(fav["tid"]) == tid for fav in favorites):
            favorites.append({
                "tid": tid,
                "title": title,
                "added": date.today().isoformat(),
            })
            save_json(favs_file(), data)
    return {"ok": True, "favorites": _favorite_list_sorted()}


def favorite_remove(tid):
    try:
        tid = int(tid)
    except (TypeError, ValueError):
        return {"ok": False, "error": f"invalid tid: {tid!r}"}
    with FileLock(favs_file() + ".lock"):
        data = _favorites()
        data["favorites"] = [fav for fav in data["favorites"] if int(fav["tid"]) != tid]
        save_json(favs_file(), data)
    return {"ok": True, "favorites": _favorite_list_sorted()}


def favorite_list():
    return {"ok": True, "favorites": _favorite_list_sorted()}


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    args = sys.argv[1:]
    if not args:
        emit({"ok": False, "error": "no command"})
        return 1
    command = args[0]

    if command == "refresh":
        emit(refresh_pool(force=False))
    elif command == "refresh-now":
        emit(refresh_pool(force=True))
    elif command == "pick":
        roll = None
        if "--roll" in args:
            roll = int(args[args.index("--roll") + 1])
        try:
            result = compute_pick(roll)
        except RuntimeError as exc:
            emit({"ok": False, "error": str(exc)})
            return 1
        if result is None:
            emit({"ok": False, "error": "pool empty"})
            return 1
        emit({"ok": True, **result})
    elif command == "favorite" and len(args) >= 2:
        subcommand = args[1]
        if subcommand == "add" and len(args) >= 4:
            emit(favorite_add(args[2], args[3]))
        elif subcommand == "remove" and len(args) >= 3:
            emit(favorite_remove(args[2]))
        elif subcommand == "list":
            emit(favorite_list())
        else:
            emit({"ok": False, "error":
                  "usage: favorite add <tid> <title> | favorite remove <tid> | favorite list"})
    else:
        emit({"ok": False, "error": f"unknown command: {command}"})
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
