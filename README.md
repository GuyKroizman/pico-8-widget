# PICO-8 Widget

[![CI](https://github.com/GuyKroizman/pico-8-widget/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/GuyKroizman/pico-8-widget/actions/workflows/ci.yml)
[![CodeQL](https://github.com/GuyKroizman/pico-8-widget/actions/workflows/codeql.yml/badge.svg?branch=main)](https://github.com/GuyKroizman/pico-8-widget/security/code-scanning)

> An Omarchy bar widget that puts a PICO-8 game on your desktop every day.

A single gamepad icon sits in the bar. Click it and you get today's
recommendation — cover image, title and description — with a clear
**Open in browser** link that takes you straight to the game on
[lexaloffle.com](https://www.lexaloffle.com/bbs/?cat=7#sub=2&mode=carts),
where it plays in your browser.

## Features

- **One game per day** — a deterministic, calendar-seeded pick from a pool of
  games the widget has collected for you. Stable all day and across restarts.
- **No unfinished work** — "WIP" carts are filtered out before they ever
  enter the pool.
- **Bookmarks** — heart a game to save it; right-click the icon for your list
  of saved games (tap one to open it). Bookmarks never influence the pick.
- **Roll another** — the ↻ button swaps today's game for a different one.
- **Light on the site** — a handful of requests a day, everything cached
  forever.

## Requirements

- Omarchy (Quattro-era shell)
- `python3` on `PATH` (stdlib only — no dependencies)

## Installation

The widget is a standard Omarchy shell plugin, installed from git:

```sh
omarchy plugin add https://github.com/GuyKroizman/pico-8-widget.git --enable
```

The installer asks where to place it (left / center / right of the bar).
Move it later any time:

```sh
omarchy bar move guy.pico-8-widget --section right
```

Verify it is loaded:

```sh
omarchy plugin list | grep pico
```

To uninstall:

```sh
omarchy plugin remove guy.pico-8-widget --yes
rm -rf ~/.local/share/guy.pico-8-widget   # optional: delete its data too
```

> Installing from git clones the repo into `~/.config/omarchy/plugins/` — no
> symlinks needed for regular use. See [Development](#development) for how to
> hack on it.

## How the recommendation works

Lexaloffle publishes no API or RSS feed for the cart BBS, but every listing
page embeds its full dataset in a `pdat=[...]` block. The widget works like
this:

1. **Lucky + memory** — once per day it pulls one or two pages of the BBS's
   built-in *lucky* (random) cart browsing mode and adds every playable,
   non-WIP cart it hasn't seen to a local memory pool (capped at 2500,
   oldest dropped — bookmarks are never dropped).
2. **Daily pick** — seeded by the calendar date, chosen from the pool,
   never repeating the last 30 picks. Stable for the whole day and across
   restarts; the ↻ button adds a roll counter that resets at midnight.
3. **On demand** — when a game is picked, its BBS page is fetched once for
   the description and its cover is downloaded once; both are cached forever.

## Data & storage

All persistent state lives under your XDG data dir in
`~/.local/share/guy.pico-8-widget/`:

| File | Contents | Typical size |
|---|---|---|
| `pool.json` | the cart pool: metadata for every cart ever seen, plus cached descriptions for picked ones | ~300 B per cart, ~1–2 MB at the 2500 cap |
| `state.json` | today's pick, roll counter, recent picks, last refresh date | < 1 KB |
| `favs.json` | your bookmarks | < 1 KB (only exists after the first bookmark) |
| `thumbs/` | downloaded cover images, one PNG per cart | ~15 KB each |

For context: after the first day of use (a pool of ~75 carts) the whole
folder is roughly 100–200 KB — most of it the downloaded covers.

### Growth model

- The pool gains ~40–80 new carts per day (two lucky pages) until it hits
  the **2500-cart cap**, at which point the oldest non-bookmarked carts are
  dropped every day. Bookmarked carts and their covers are never dropped.
- Covers of dropped carts are deleted too, so `thumbs/` stays bounded at
  ~2500 files: roughly **40 MB worst case**, typically far less.
- Network use is ~3–4 requests/day once the pool is warm: two lucky pages,
  plus the picked cart's description page (~200 KB) and cover (~15 KB) when
  it hasn't been cached. Requests are paced at ≥ 0.9 s apart and everything
  fetched once is cached forever.

### Starting over

```sh
rm -rf ~/.local/share/guy.pico-8-widget
```

The pool, picks and bookmarks are gone; the widget rebuilds the pool from
scratch on its next refresh.

## Development

The plugin's layout mirrors what `omarchy plugin add` clones into
`~/.config/omarchy/plugins/`, so you can develop straight from a clone of
this repo (folder name must match the `id` in `manifest.json`):

```sh
# from this repo
ln -s "$PWD" ~/.config/omarchy/plugins/guy.pico-8-widget
omarchy-shell shell rescanPlugins
```

Then add `{ "id": "guy.pico-8-widget" }` to a section in `bar.layout.*` in
`~/.config/omarchy/shell.json`.

Edit → sanity-check → reload:

```sh
python3 -m py_compile p8.py          # helper script
omarchy plugin validate .            # manifest/QML wiring
omarchy restart shell                # dependable reload (also applies shell.json)
```

Notes:

- The shell watches `~/.config/omarchy/plugins/` and *usually* hot-reloads
  saved files, but through a **symlinked** plugin dir that proved unreliable
  in testing — a full `omarchy restart shell` is the dependable step after
  code changes. It only restarts the bar; open windows are untouched.
- `omarchy-shell shell rescanPlugins` re-scans the plugin *set* — use it
  after creating/removing the symlink or enabling/disabling a plugin, not
  for plain code edits.
- Watch for QML errors after a change:
  `journalctl --user -f | grep -iE 'qml|pico'`
- Check the shell sees the plugin: `omarchy plugin list`.

## Testing & CI

The Python layer (`p8.py` — parser, WIP filter, deterministic pick,
bookmarks, pruning) is fully unit-tested **offline**: `p8.fetch` is mocked,
so the suite never touches the network or the Lexaloffle site. Real BBS
markup lives in `tests/fixtures/` (slimmed-down copies of listing pages and
cart pages).

```
tests/
  conftest.py            # isolated temp data dir per test, frozen clock, mock fetch
  fixtures/              # listing page + modern/embed-disabled cart pages
  test_parser.py         # pdat blob parsing + WIP/cart filtering
  test_extract.py        # description extraction & cleanup
  test_pool.py           # refresh, pruning, cover deletion, detail/thumb caching
  test_pick.py           # determinism, rolls, state restore, failure resilience
  test_favorites.py      # bookmarks
  test_fetch.py          # retry + pacing behaviour
  test_cli.py            # command-line entry point
```

Run everything locally (any python3 with pytest/pytest-cov/radon):

```sh
python -m pytest tests -q                        # the unit suite
python -m pytest tests --cov=p8 --cov-report=term-missing -q   # coverage
python -m pytest --cov=p8 --cov-report=json:coverage.json -q   # report for the gate
python tools/crap_gate.py --threshold 30         # CRAP gate (exits non-zero on failure)
```

**What the CRAP gate does:** CRAP (Change Risk Anti-Patterns) =
`complexity² × (1 − coverage)³ + complexity`, per function. A function only
scores over the default threshold of 30 when it is both complex *and*
under-covered — so the gate pushes you to either simplify a function or
cover it. Every function in `p8.py` currently passes with ~96% total line
coverage.

**Mutation testing** (`.github/workflows/mutation.yml`): line coverage only
proves code *ran*; mutation testing proves tests would *fail* if the code
misbehaved. mutmut applies ~1150 small mutations to `p8.py` and re-runs the
suite for each; the current score is ~79% (killed + timeout over all
non-skipped mutants). The CI gate fails below 75% — survivors are mostly
equivalent mutants (no behavior change, unkillable) and defensive/error
paths; real gaps it exposes should be fixed with tests, not by loosening the
gate. Run locally:

```sh
python tools/mutation_gate.py --threshold 75
```

(Results are cached in `./mutants/`, gitignored; delete it to force a full
run after changing tests.)

**GitHub Actions** runs on every push and pull request: the main CI job
installs the tooling on Python 3.12, runs the unit tests, collects coverage,
and fails if the CRAP gate trips; a second job runs the mutation gate; a
third runs CodeQL weekly. The QML popup is *not* covered by any of them —
Quickshell needs a Wayland session, so UI changes still need a manual check
on a real Omarchy box (see the reload notes above).

## Layout

```
manifest.json       plugin manifest (id: guy.pico-8-widget, kind: bar-widget)
Pico8Games.qml      bar icon + popup (Omarchy Panel / Quickshell QML)
p8.py               data helper (python3, stdlib only) — fetch, pick, cache
pyproject.toml      mutmut (mutation testing) configuration
tests/              offline unit tests + BBS fixtures (see "Testing & CI")
tools/crap_gate.py  CRAP metric gate for CI
tools/mutation_gate.py  mutation-score gate for CI
.github/workflows/  GitHub Actions CI (tests, mutation, CodeQL)
PUBLISHING.md       how to list this plugin on the Omarchy marketplace
README.md
LICENSE
```

`p8.py` can also be used from a terminal:

```sh
python3 p8.py refresh            # pull lucky pages into the pool
python3 p8.py pick               # today's game (restores current state)
python3 p8.py pick --roll 2      # a specific roll for today
python3 p8.py favorite list      # bookmarks
python3 p8.py favorite add 158939 "Rockhound"
python3 p8.py favorite remove 158939
```

## Notes / etiquette

- The Lexaloffle BBS is a small hobby site: the helper makes only a handful
  of requests a day, paced and retried gently, and caches everything it ever
  fetched.
- Descriptions are scraped from the BBS pages and lightly cleaned; some old
  carts or carts that disallow embedding will show a short or empty text.
- *PICO-8 is a trademark of Lexaloffle Games LLP; this widget is an
  unofficial community project and is not affiliated with Lexaloffle.*

## License

[MIT](LICENSE)
