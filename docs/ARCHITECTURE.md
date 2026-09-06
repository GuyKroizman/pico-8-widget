# Architecture

This file explains how the PICO-8 Widget works, in pictures. It is aimed at
people who want to understand or extend the plugin, humans and AI agents
alike.

- [1. Component map](#1-component-map)
- [2. A day in the life (sequence)](#2-a-day-in-the-life-sequence)
- [3. CI quality gates](#3-ci-quality-gates)

Quick orientation before the diagrams:

- **`Pico8Games.qml`** is the UI: the bar icon, the popup, the timers and the
  retry logic. It is Quickshell QML and can only run inside the Omarchy
  shell (a Wayland session) — which is why it is tested manually, not in CI.
- **`JobQueue.js`** is the UI's pure logic: the serialized job queue and the
  interpretation of process end-states (including the exit-0-before-output
  signal race). It has no Qt dependencies and is unit-tested in Node.
- **`p8.py`** is the stateless helper: all fetching, parsing, picking and
  bookkeeping. It is pure Python (stdlib only) and is what the CI test stack
  covers.
- **Everything persistent** lives under `~/.local/share/guy.pico-8-widget/`.

---

## 1. Component map

```mermaid
flowchart TB
    subgraph UI["UI — Pico8Games.qml (Omarchy shell / Quickshell)"]
        icon["Bar icon (gamepad glyph)"]
        popup["Popup panel — cover, title, description, actions"]
        timers["Timers — hourly refresh, retry after failure"]
        queue["JobQueue.js — pure JS queue + exit logic (Node-tested)"]
        icon -->|"left/right click"| popup
        timers --> queue
        popup --> queue
    end

    subgraph HELPER["Helper — p8.py (python3, stdlib only)"]
        cmds["Commands: refresh · pick --roll N · favorite add/remove/list"]
        parser["pdat parser + description extractor (html.parser)"]
        pick["Daily pick — seeded by date, no repeats from last 30"]
        net["HTTPS — paced, short timeouts, gentle retries"]
        cmds --> parser
        cmds --> pick
        cmds --> net
    end

    subgraph DISK["Local data — ~/.local/share/guy.pico-8-widget"]
        pool["pool.json — cart memory + cached descriptions"]
        state["state.json — today's pick, roll, recent, last refresh"]
        favs["favs.json — bookmarks"]
        thumbs["thumbs/ — downloaded cover PNGs"]
    end

    subgraph SITE["Lexaloffle BBS (external)"]
        lucky["Listing pages — embedded pdat=[...] blob, 'lucky' sort"]
        cartpage["Per-game cart page — description text"]
        cover["Cover image"]
    end

    subgraph LAUNCH["User action"]
        browser["Default browser (xdg-open)"]
    end

    queue -->|"spawns: python3 p8.py &lt;command&gt;"| cmds
    net --> lucky
    net --> cartpage
    net --> cover
    cmds -->|"merge + prune"| pool
    cmds -->|"read / write"| state
    cmds -->|"read / write"| favs
    net -->|"cache to"| thumbs
    thumbs -->|"local file path"| popup
    popup -->|"Open in browser"| browser
```

### Where the code lives (the three locations)

```mermaid
flowchart LR
    repo["Repo — this git repository (source of truth)"]
    runtime["Runtime plugin dir — ~/.config/omarchy/plugins/guy.pico-8-widget"]
    data["User data — ~/.local/share/guy.pico-8-widget"]
    shellcfg["Bar layout — ~/.config/omarchy/shell.json"]

    repo -->|"symlink for development,<br/>or 'omarchy plugin add' for install"| runtime
    runtime -->|"placed in bar.layout"| shellcfg
    runtime -->|"reads and writes"| data
```

The shell only loads plugins from the runtime dir; the folder name must match
the `id` in `manifest.json`. User data lives outside the code so updates never
touch your picks and bookmarks.

---

## 2. A day in the life (sequence)

```mermaid
sequenceDiagram
    participant T as Timers (QML)
    participant W as Widget (Pico8Games.qml)
    participant H as p8.py
    participant D as Data files
    participant B as Lexaloffle BBS

    Note over T,B: Startup and hourly tick
    T->>H: refresh  (skips itself if already run today)
    H->>B: fetch 1-2 'lucky' listing pages
    B-->>H: pdat rows (title, tid, thumb, tags, flags)
    H->>D: merge playable non-WIP carts into pool.json, prune old

    T->>H: pick  (no --roll: restore today's state)
    H->>D: read state.json + pool.json
    alt Cached pick for today's date + roll
        H-->>W: today's game — no network needed
    else Cache miss (new day, first roll, or unknown game)
        H->>B: cart page for description
        B-->>H: description HTML
        H->>B: cover image
        B-->>H: image bytes
        H->>D: cache description and cover
        H-->>W: JSON: title, description, thumb path, url
    end
    W->>W: show cover, title, description

    Note over W,B: User clicks the icon
    W->>H: pick / favorite add / remove / list
    H-->>W: results (bookmarks never influence the pick)

    Note over W,B: Failure path — the site occasionally stalls
    W->>H: pick
    H--xW: helper error or watchdog timeout
    W->>W: retry twice ~4s apart, then show 'Try again' button
```

Notes: opening the game launches the default browser with the game's BBS page
via `xdg-open`. The QML layer talks to `p8.py` through a single serialized
`Process` (Quickshell can run one command at a time); the queueing and
process-end logic lives in `JobQueue.js`, so commands stay ordered and a
helper that exits 0 before its output arrives is never misreported as failed.

---

## 3. CI quality gates

Every push and pull request runs, in order, on GitHub Actions. Each layer
covers a different failure mode — and several have already caught real bugs
during development.

```mermaid
flowchart LR
    A["Unit tests — 73 offline (63 Python + 10 UI-glue JS), network mocked<br/>caught: WIP filter rejecting 'Wipeout Racers'"]
    B["Coverage — ~96% lines<br/>proves the tests actually ran the code"]
    C["CRAP gate — complexity vs. coverage per function"]
    D["Mutation testing — ~1,150 mutants, CI gate &gt;= 75%<br/>caught: HTML comments leaking into popup text"]
    E["Security — Bandit + CodeQL<br/>caught: bypassable HTML-stripping regex"]
    A --> B --> C --> D --> E
```

What is not in CI: the QML popup itself (needs a live Wayland session) and the
interaction with the real Lexaloffle site (tests mock the network; the widget
is deliberately gentle with the site — a handful of requests a day, cached
forever).
