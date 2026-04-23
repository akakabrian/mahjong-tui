# mahjong-tui — decisions

One page. Short. Update as we go.

## What this is

Mahjong **Solitaire** (tile-matching) as a Textual TUI. Not the 4-player
game. 144 tiles on a 3D stack rendered in 2D ASCII with Unicode
box-drawing to suggest depth.

## Engine / content vendored

**KDE KMahjongg** (GPL-2+) provides the **layout format** and the
**72 stock layouts** under `vendor/kmahjongg/layouts/`. The layouts are
`.layout` files with a `.desktop` sidecar for metadata (name,
description, author). The game rules (free-and-visible pair matching,
suit grouping for seasons/flowers) are well known and codified in
[KDE's kmahjongg handbook](https://docs.kde.org/stable5/en/kmahjongg/kmahjongg/index.html);
we re-implement those from scratch in Python — no C++ engine to bind to.

### Layout format (v1.0 / v1.1)

First line: `kmahjongg-layout-v1.0` or `v1.1`. v1.1 adds optional
`w<n>`, `h<n>`, `d<n>` comments for board width/height in **quarter
tiles** and depth in levels; v1.0 hardcodes `w=32 h=16`. Then `# Level
<n>` markers separate each depth layer. Each level is a grid of
characters where:

- `.` = empty
- `1` / `2` / `3` / `4` = the four quarter-tile corners of a full tile
  - `1` top-left, `2` top-right, `3` bottom-right, `4` bottom-left

A full tile spans a 2×2 block of quarter-cells: top-row reads `12`,
bottom-row reads `43`. Internally we **collapse quarter coordinates to
tile coordinates** on load: `tile_x = qx // 2, tile_y = qy // 2`, with
sub-quarter positions validating that all four corners are present.
Tiles on level N are considered stacked on top of the level N-1
footprint when their tile-coords overlap.

### License

KMahjongg layouts are **GPL-2+**. This wrapper is therefore **GPL-2+**.
LICENSE at repo root will be GPLv2. We will **bundle** the layouts
because GPL-2+ permits it when the whole work is also GPL-2+; users can
also drop custom `.layout` files into `~/.local/share/mahjong-tui/layouts/`
(loader scans this dir alongside the vendor dir).

## Tile set — what the player sees

144 tiles, standard mahjong composition:
- 36 **dots/circles** (1–9 × 4 copies)
- 36 **bamboo** (1–9 × 4 copies)
- 36 **characters** (1–9 × 4 copies)
- 16 **winds** (E/S/W/N × 4)
- 12 **dragons** (red/green/white × 4)
- 4 **seasons** (spring/summer/autumn/winter) — any season matches any other
- 4 **flowers** (plum/orchid/chrysanthemum/bamboo) — any flower matches any other

**Visual representation.** We try Unicode mahjong block first
(U+1F000–U+1F021), fall back to 2-letter ASCII abbreviations (`1B`,
`E1`, `DR`, etc.) for terminals where those glyphs render as boxes or
mis-width. Evaluation script: `tests/tile_test.py` prints both and lets
user eyeball which reads.

Unicode tiles are typically **double-width**, which we exploit: each
logical tile is rendered as a 2-char wide cell, matching the geometry
KMahjongg encodes (each tile = 2 quarter-columns).

## 3D-in-2D rendering

Each tile shows as a 2-char-wide × 2-row-tall box with a depth-shaded
right edge + bottom edge. Higher layers offset up-and-right by 1 cell
(classic isometric-ish cheat). Bottom layer of a covered region paints
first; higher layers overpaint. Unicode box-drawing provides:

- `┌─┐` / `│ │` / `└─┘` for tile outline
- `▌` / `▐` for depth shading on right/bottom edges of lower layers
  when an upper-layer tile sits on top

Selected tile: inverted colors. Free-and-available tiles: bright bg.
Blocked tiles: dim. Hint highlight: yellow flash.

## Matching rules (the game)

A tile is **free** iff:
1. It has **no tile on top** (no tile at same (x,y) in a higher level),
   AND
2. Its **left OR right side is clear** (no tile adjacent at the same
   level, considering the 2-quarter width).

The player clicks two free tiles; if they **match** (same face, or
same group for seasons/flowers), both are removed. Win = all 144
gone. Deadlock = no free pairs left (detector runs on each move
for hint eligibility too).

## Features (target)

- [x] 3+ layouts (Turtle/default, Pyramid, Dragon, Cross) — have 72
- [ ] Click to select; click-to-match pair
- [ ] Keyboard cursor mode (arrows + enter)
- [ ] **Hint** — highlight a valid free pair
- [ ] **Undo** — full history stack
- [ ] **Shuffle** — re-deal remaining tiles (with guarantee of solvability
      via backtracking generator)
- [ ] Time tracker (MM:SS in status bar)
- [ ] Win detection + win screen
- [ ] Deadlock detection + "no more moves" screen
- [ ] Legend / help / layout picker (modals)

## Structure

Mirrors simcity-tui:

```
mahjong-tui/
├── mahjong.py           # entry
├── pyproject.toml
├── Makefile
├── DECISIONS.md
├── LICENSE              # GPLv2
├── vendor/kmahjongg/    # .layout files + COPYRIGHT
├── mahjong_tui/
│   ├── __init__.py
│   ├── tiles.py         # face defs, unicode/ASCII, groups, match rule
│   ├── layout.py        # .layout parser
│   ├── game.py          # pure game state (no UI) — tiles, deal, free(),
│   │                    #   match(), undo, shuffle, solvable deal
│   ├── render.py        # 3D→2D render helpers (depth shading)
│   ├── app.py           # Textual App + BoardView widget
│   ├── screens.py       # Help/Legend/LayoutPicker/WinScreen
│   └── tui.tcss
└── tests/
    ├── qa.py            # Pilot scenarios
    ├── perf.py
    └── tile_test.py     # unicode vs ASCII visual check
```

## Rejections / non-goals

- No sound yet (will add Phase D if time).
- No agent/REST API (nice-to-have, after core).
- No 4-player mahjong. Different game entirely.
- No riichi / scoring — solitaire is pair-match only.
