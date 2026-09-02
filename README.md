# PICO-8 Widget — a daily game in your bar

An Omarchy bar widget that recommends one PICO-8 game per day.

The bar shows a single gamepad icon. Click it to see today's game — cover
image, title and description — with a clear **Open in browser** link (the
cover and title are clickable too), plus:

- **♥** bookmark the game so you can come back to it later
- **↻** roll another game for today

Right-click the icon for your saved games (a plain list; tap one to open it).
Bookmarks never influence the daily pick — they're just games you liked.

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

WIP ("work in progress") carts are filtered out by tag and title before they
ever enter the pool, so you never get handed a half-finished demo.

## Where the code lives — the development cycle

There are three separate locations, and it's worth keeping them straight:

| Location | Purpose |
|---|---|
| `/home/guy/code/pico-8-widget/` | **Source repo** (this folder, git). The code you edit. |
| `~/.config/omarchy/plugins/guy.pico-8-widget/` | **Runtime plugin dir**. A *symlink to the repo* — the Omarchy shell only loads plugins from here (the folder name must match the `id` in `manifest.json`). |
| `~/.local/share/guy.pico-8-widget/` | **User data** (pool, cache, bookmarks, covers). Never touched by updates; safe to delete to start over. |

The bar itself is configured in `~/.config/omarchy/shell.json`
(`bar.layout.*`), which is where the widget's placement lives.

### Editing and reloading

```sh
# 1. edit files in the repo, then sanity-check
python3 -m py_compile p8.py          # helper script
omarchy plugin validate .            # manifest/QML wiring

# 2. load the changes into the running shell
omarchy restart shell                # dependable, applies everything
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

### Installing elsewhere / publishing

The repo is laid out exactly like an installed plugin, so `omarchy plugin add`
can clone it straight into place on any machine (no symlink needed):

```sh
omarchy plugin add https://github.com/you/pico-8-widget.git --enable
```

## Data & storage

All persistent state is in `~/.local/share/guy.pico-8-widget/`:

| File | Contents | Typical size |
|---|---|---|
| `pool.json` | the cart pool: metadata for every cart ever seen, plus cached descriptions for picked ones | ~300 B per cart, ~1–2 MB at the 2500 cap |
| `state.json` | today's pick, roll counter, recent picks, last refresh date | < 1 KB |
| `favs.json` | your bookmarks | < 1 KB (only exists after the first bookmark) |
| `thumbs/` | downloaded cover images, one PNG per cart | ~15 KB each |

On this machine after the first day (76 carts in the pool) the whole folder
is ~130 KB — `pool.json` ≈ 27 KB and six covers ≈ 96 KB.

### Growth model

- The pool gains ~40–80 new carts per day (two lucky pages) until it hits
  the **2500-cart cap**, at which point the oldest non-bookmarked carts are
  dropped every day. Bookmarked carts and their covers are never dropped.
- Covers of dropped carts are deleted too, so `thumbs/` stays bounded at
  ~2500 files: roughly **40 MB worst case**, typically far less.
- Descriptions add ~1–4 KB per entry, only for carts that were picked.
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

## Layout

```
manifest.json       plugin manifest (id: guy.pico-8-widget, kind: bar-widget)
Pico8Games.qml      bar icon + popup (Omarchy Panel / Quickshell QML)
p8.py               data helper (python3, stdlib only) — fetch, pick, cache
README.md
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
