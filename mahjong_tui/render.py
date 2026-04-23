"""3D-in-2D board rendering helpers.

Each tile is drawn as a 2-char-wide × 2-row-tall cell. Higher levels are
drawn as offset overlays: each stacked tile is shifted up-and-right by
one cell per level, giving the classic "stair-stepped" mahjong-solitaire
look when tiles sit on top of other tiles.

Terminal geometry:

    A single tile looks like:

        .─┐
        XX│       row 0: top-left corner + face-char pair
        ══╝       row 1: bottom edge

    Stacked (tile above it, shifted right and up):

         .─┐
        .─│         <- level 1 starts here, 1 col right, 1 row up
        XX│         bottom half of the level-0 tile peeks in
         XX│
         ═╝
         ══╝

We don't try to produce pixel-accurate isometric lines — the goal is
legible 2-char faces with a hint of depth shading.

Rendering algorithm:

  1. Allocate a 2D char + style grid sized to
     (rows = board_height_q * 2 + max_depth, cols = board_width_q * 2 + max_depth * 2).
     Quarter-cell coords (qx, qy) → terminal (col, row) = (qx*2, qy*2)
     on level 0, plus (+2, -1) per level.
  2. For each level bottom-up, paint each tile into the grid — face chars,
     border, depth shading.
  3. A hotspot table `(qx, qy, level) -> (col_range, row_range)` is
     produced as a side-effect so mouse / cursor code can map tile
     positions back to terminal cells.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from rich.style import Style
from rich.segment import Segment

from .game import Game, Tile
from . import tiles as tileset


# Per-level offset — each level above 0 shifts (+COL_STEP, -ROW_STEP).
# Chosen so a 3-level stack is unambiguously readable without the top
# peak vanishing off the top of a reasonable-size terminal.
COL_STEP = 1
ROW_STEP = 1
# Tile footprint in terminal cells.
TILE_W = 2
TILE_H = 2

# Set at the start of render_board() so _paint_tile can position tiles
# relative to a consistent top margin. Not thread-safe, but Textual's
# rendering is single-threaded so that's fine.
_TOP_MARGIN: int = 1


@dataclass
class Hotspot:
    """Maps a tile back to the terminal cells it occupies."""
    tile_id: int
    col0: int
    row0: int
    col1: int   # exclusive
    row1: int   # exclusive
    level: int = 0


@dataclass
class RenderOutput:
    width: int
    height: int
    # chars[row][col], styles[row][col] — parallel grids. Style is a
    # prebuilt rich.style.Style or None for "default".
    chars: list[list[str]]
    styles: list[list[Style | None]]
    # Map from tile_id to Hotspot for hit-testing + cursor.
    hotspots: dict[int, Hotspot]


def board_dims(game: Game) -> tuple[int, int]:
    """Terminal dims needed to render the board. Account for the max
    level's diagonal shift."""
    layout = game.layout
    cols = layout.width_q * TILE_W + (layout.depth + 1) * COL_STEP + 2
    rows = layout.height_q * TILE_H + (layout.depth + 1) * ROW_STEP + 2
    return cols, rows


# ---- palette ------------------------------------------------------------

# Tile face color — pre-parsed rich Style per face ID, with a common
# cream background for the tile face. Selected / free / blocked apply
# overlays on top.

_BASE_BG = "rgb(245,230,195)"     # cream tile face
_EDGE = "rgb(80,55,25)"            # tile border
_SHADOW_RIGHT = "rgb(160,120,70)"  # right-edge shadow (depth)
_SHADOW_BOT = "rgb(130,95,50)"     # bottom-edge shadow (depth)
_DIM_BG = "rgb(160,150,125)"       # dim (blocked) face bg
_FREE_BG = "rgb(255,245,215)"      # bright (free) face bg
_SEL_BG = "rgb(255,200,80)"        # yellow selected bg
_CUR_BG = "rgb(120,220,140)"       # green cursor bg
_HINT_BG = "rgb(180,220,255)"      # blue hint bg
_FG_EDGE_STYLE = Style.parse(f"{_EDGE} on {_BASE_BG}")


def _face_style(face: int, *, bg: str, dim: bool = False) -> Style:
    fg = tileset.FACES[face].color
    if dim:
        # Darken unprintable backgrounds so blocked tiles don't vanish.
        return Style.parse(f"{fg} on {bg}")
    return Style.parse(f"bold {fg} on {bg}")


# ---- main render --------------------------------------------------------

def render_board(
    game: Game,
    *,
    ascii_only: bool = False,
    selected_id: int | None = None,
    hint_ids: tuple[int, int] | None = None,
    cursor_id: int | None = None,
) -> RenderOutput:
    """Produce a char + style grid ready for a Textual Strip per-row.

    Selected / hint / cursor highlight is applied after base paint so it
    wins over depth shading. `ascii_only` swaps Unicode tile glyphs for
    the 2-char ASCII fallbacks — useful on terminals where the Unicode
    mahjong block renders as tofu or wrong width.
    """
    cols, rows = board_dims(game)
    chars = [[" "] * cols for _ in range(rows)]
    styles: list[list[Style | None]] = [[None] * cols for _ in range(rows)]
    hotspots: dict[int, Hotspot] = {}
    # Top margin — enough room for the tallest stack to paint up from a
    # level-0 anchor at row `qy*TILE_H + top_margin`.
    global _TOP_MARGIN
    _TOP_MARGIN = (game.layout.depth + 1) * ROW_STEP + 1

    # Sort tiles bottom-up, and for tiles on the same level, left-to-right
    # / top-to-bottom so rightward/downward tiles don't shadow-overwrite
    # their left/upper neighbours. Stable.
    tiles_sorted = sorted(
        game.tiles.values(),
        key=lambda t: (t.level, t.qy, t.qx),
    )

    free_set = {t.id for t in game.free_tiles()}
    hint_set = set(hint_ids or ())

    for t in tiles_sorted:
        _paint_tile(
            chars, styles, t,
            is_free=(t.id in free_set),
            is_selected=(t.id == selected_id),
            is_hint=(t.id in hint_set),
            is_cursor=(t.id == cursor_id),
            ascii_only=ascii_only,
            hotspots=hotspots,
        )
    return RenderOutput(width=cols, height=rows, chars=chars, styles=styles,
                        hotspots=hotspots)


def _paint_tile(chars, styles, tile: Tile, *, is_free: bool, is_selected: bool,
                is_hint: bool, is_cursor: bool, ascii_only: bool,
                hotspots: dict) -> None:
    """Overwrite a 2×2 region (plus right/bottom shadow cells on the
    row/col beyond) for this tile.

    Stacking: each level shifts +COL_STEP to the right and -ROW_STEP
    upward. The grid has a top margin of (max_depth * ROW_STEP) + 1 so
    the highest tile still fits; we express `row` as
    (qy * TILE_H) + top_margin + (-level * ROW_STEP).
    """
    # chars is a list[list[str]] with rows >= 0. To guarantee the top
    # level's row fits, callers must size the grid to include a top
    # margin large enough for the deepest stack. We compute that margin
    # from the actual chars array size vs. the layout dimensions.
    n_rows = len(chars)
    n_cols = len(chars[0]) if chars else 0
    # Reserve 1 bottom row too for the shadow strip.
    top_margin = max(1, n_rows - (tile.qy + 1) * TILE_H - 1)
    # Actually we want the top margin to be CONSTANT across the render
    # pass so all tiles align. Retrieve it from the first chars row:
    # easier to just compute once outside — but since we don't want to
    # plumb a "layout depth" through, we instead use a fixed top margin
    # of (max_level_possible * ROW_STEP). The caller (board_dims) sized
    # the grid to (layout.height_q*2 + (depth+1)*ROW_STEP + 2), so the
    # top margin is fixed at (n_rows - layout.height_q*2 - 1 = depth+1).
    # We can recover depth from (n_rows - height_q*2 - 1) / ROW_STEP, but
    # we don't know height_q here. Simplest: use a large enough fixed
    # margin. Since board_dims computes `rows = height_q*2 + (depth+1)+2`,
    # and we want row 0 at the TOP, the per-tile offset is
    # (depth - level) * ROW_STEP. We approximate depth by saying the
    # grid's FIRST usable row is 1, and each increment of level shifts
    # up by ROW_STEP. Use `n_rows - 2 - tile.qy*TILE_H` as the level-0
    # row (tile bottom-aligned to its qy) and subtract (level * ROW_STEP).
    col = tile.qx * TILE_W + tile.level * COL_STEP + 1
    # Compute the row for this tile: we render top-down in the grid, so
    # qy=0 is near the top. Stacking shifts level>0 tiles upward — that
    # means SMALLER row index. Level 0 tiles anchor at
    # row = qy*TILE_H + top_pad, and each level above subtracts ROW_STEP.
    # top_pad is set to leave enough room: (max_level * ROW_STEP) + 1.
    # We don't know max_level here, so we use the grid height to derive
    # how much room is above qy*TILE_H.
    # Simpler + correct: use module-global _paint_top_margin set by the
    # render_board function before any tile is painted.
    global _TOP_MARGIN
    row = tile.qy * TILE_H + _TOP_MARGIN - tile.level * ROW_STEP
    # Clip to grid.
    if row < 0 or row + 1 >= n_rows:
        return
    if col < 0 or col + 1 >= n_cols:
        return

    # Face text — 2 chars wide, matching the tile footprint.
    face = tileset.FACES[tile.face]
    glyph = face.glyph_ascii if ascii_only else face.glyph_unicode
    # Unicode mahjong tiles are typically double-width — one character
    # occupies our 2 terminal cells. For ASCII (2 chars), we write them
    # as-is. Normalise to exactly 2-cell width.
    if len(glyph) == 1:
        # Double-width unicode — draw char in col, pad col+1 with empty
        # (terminal will auto-consume the next cell for the wide glyph).
        face_chars = [glyph, ""]  # empty 2nd cell — wide char takes both
    else:
        # ASCII 2-char.
        face_chars = [glyph[0], glyph[1] if len(glyph) > 1 else " "]

    # Background colour depends on state. Selection wins over cursor,
    # which wins over hint, which wins over free-vs-blocked base tint.
    if is_selected:
        bg = _SEL_BG
    elif is_cursor:
        bg = _CUR_BG
    elif is_hint:
        bg = _HINT_BG
    elif is_free:
        bg = _FREE_BG
    else:
        bg = _BASE_BG

    face_style = _face_style(tile.face, bg=bg, dim=not is_free)

    # Draw 2×2 block:
    #   top    row: face chars (col, col+1)
    #   bottom row: bottom edge chars (═ or -), in shadow style.
    chars[row][col] = face_chars[0]
    chars[row][col + 1] = face_chars[1] if face_chars[1] else " "
    styles[row][col] = face_style
    styles[row][col + 1] = face_style

    # Bottom row of the tile — a subtle underline / shadow.
    bot_row = row + 1
    if bot_row < len(chars):
        shadow_style = Style.parse(f"{_EDGE} on {_SHADOW_BOT}")
        chars[bot_row][col] = "▂"
        chars[bot_row][col + 1] = "▂"
        styles[bot_row][col] = shadow_style
        styles[bot_row][col + 1] = shadow_style

    # Right-edge shadow — occupies the column immediately right of the
    # tile. Only draw if nothing visually important sits there.
    right_col = col + 2
    if right_col < len(chars[row]):
        shadow_style_r = Style.parse(f"{_EDGE} on {_SHADOW_RIGHT}")
        # Half-block for right edge.
        chars[row][right_col] = "▎"
        styles[row][right_col] = shadow_style_r

    hotspots[tile.id] = Hotspot(
        tile_id=tile.id,
        col0=col, row0=row,
        col1=col + TILE_W, row1=row + TILE_H,
        level=tile.level,
    )


def strip_for_row(out: RenderOutput, row: int, *, max_width: int) -> list[Segment]:
    """Run-length-encode one row's chars + styles into rich Segments for
    a Textual Strip. `max_width` truncates (padded with spaces) so the
    Strip matches the viewport width the widget promises."""
    if row < 0 or row >= out.height:
        return [Segment(" " * max_width)]
    chars = out.chars[row]
    styles = out.styles[row]
    segments: list[Segment] = []
    run: list[str] = []
    run_style: Style | None = None
    width = min(len(chars), max_width)
    for i in range(width):
        ch = chars[i] or " "
        st = styles[i]
        if st is run_style:
            run.append(ch)
        else:
            if run:
                segments.append(Segment("".join(run), run_style))
            run = [ch]
            run_style = st
    if run:
        segments.append(Segment("".join(run), run_style))
    remaining = max_width - width
    if remaining > 0:
        segments.append(Segment(" " * remaining))
    return segments


def tile_at_cell(out: RenderOutput, col: int, row: int) -> int | None:
    """Hit-test: return the tile ID at (col, row), or None. Breaks ties
    by level — the topmost (highest level) tile wins when stacked tiles
    overlap the same cell."""
    best: int | None = None
    best_level: int = -1
    for hs in out.hotspots.values():
        if hs.col0 <= col < hs.col1 and hs.row0 <= row < hs.row1:
            if hs.level > best_level:
                best = hs.tile_id
                best_level = hs.level
    return best


__all__ = [
    "RenderOutput", "Hotspot",
    "render_board", "board_dims", "strip_for_row", "tile_at_cell",
    "TILE_W", "TILE_H", "COL_STEP", "ROW_STEP",
]
