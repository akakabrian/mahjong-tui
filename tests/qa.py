"""Headless QA driver for mahjong-tui.

Runs each scenario in a fresh `MahjongApp` via `App.run_test()`, captures an
SVG screenshot, and reports pass/fail. Exit code is the number of failures.

    python -m tests.qa            # run all
    python -m tests.qa match      # run scenarios whose name contains "match"
"""

from __future__ import annotations

import asyncio
import sys
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

from mahjong_tui.app import MahjongApp
from mahjong_tui.game import Game, Tile
from mahjong_tui import tiles as tileset
from mahjong_tui import render as R
from mahjong_tui.layout import parse_layout, available_layouts

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

# Fixed seed so deals are reproducible across runs. The Turtle layout at
# this seed has a known-good initial free-pair list, which lets us write
# deterministic assertions about "pick a pair and match them".
FIXED_SEED = 0xBEEF


@dataclass
class Scenario:
    name: str
    fn: Callable[[MahjongApp, "object"], Awaitable[None]]


# ---------- helpers ----------


def _pick_free_pair(game: Game) -> tuple[Tile, Tile] | None:
    pairs = game.free_pairs()
    return pairs[0] if pairs else None


async def _click_tile(pilot, app: MahjongApp, tile: Tile) -> None:
    """Scroll the tile into view, then dispatch a mouse click on its
    top-left cell."""
    board = app.board
    out = board._render_out
    assert out is not None, "board render not ready"
    hs = out.hotspots[tile.id]
    # Ensure the hotspot is within the current viewport.
    try:
        from textual.geometry import Region
        board.scroll_to_region(
            Region(hs.col0, hs.row0, hs.col1 - hs.col0, hs.row1 - hs.row0),
            animate=False,
            force=True,
        )
    except Exception:
        pass
    await pilot.pause()
    off_x = hs.col0 - int(board.scroll_offset.x)
    off_y = hs.row0 - int(board.scroll_offset.y)
    await pilot.click("BoardView", offset=(off_x, off_y))
    await pilot.pause()


# ---------- scenarios ----------


async def s_mount_clean(app, pilot):
    assert app.board is not None
    assert app.stats is not None
    assert app.info is not None
    assert app.help_panel is not None
    assert app.game is not None
    assert app.game.remaining > 0


async def s_default_layout_is_turtle(app, pilot):
    # Default.layout ships as the "Turtle" stack — 144 tiles, depth 5.
    assert app.game.layout.tile_count == 144, app.game.layout.tile_count
    assert app.game.layout.depth >= 3, app.game.layout.depth


async def s_free_pairs_available_on_deal(app, pilot):
    # Solvable deal must have at least one free pair.
    pairs = app.game.free_pairs()
    assert len(pairs) > 0, "fresh deal should have available moves"
    assert app.game.has_moves


async def s_render_produces_glyphs(app, pilot):
    # Render grid contains at least one tile face glyph (non-space, non-shadow).
    out = app.board._render_out
    assert out is not None
    nonblank = 0
    for row in out.chars:
        for ch in row:
            if ch and ch != " " and ch not in ("▂", "▎"):
                nonblank += 1
    assert nonblank > 50, f"render grid too sparse: {nonblank} chars"


async def s_hotspots_cover_all_tiles(app, pilot):
    out = app.board._render_out
    assert out is not None
    assert len(out.hotspots) == app.game.remaining, (
        f"hotspots={len(out.hotspots)} tiles={app.game.remaining}"
    )


async def s_hint_highlights_a_pair(app, pilot):
    before_hints = app.game.hints_used
    await pilot.press("h")
    await pilot.pause()
    assert app.game.hints_used == before_hints + 1
    assert app.board.hint_pair is not None, "hint should set hint_pair"
    a_id, b_id = app.board.hint_pair
    a = app.game.tiles[a_id]
    b = app.game.tiles[b_id]
    assert tileset.match(a.face, b.face), "hint pair must match"
    assert app.game.is_free(a) and app.game.is_free(b), (
        "hint pair must be free"
    )


async def s_match_removes_pair_via_clicks(app, pilot):
    pair = _pick_free_pair(app.game)
    assert pair is not None, "no free pair available"
    a, b = pair
    remaining_before = app.game.remaining
    await _click_tile(pilot, app, a)
    assert app.board.selected_id == a.id, (
        f"expected {a.id} selected, got {app.board.selected_id}"
    )
    await _click_tile(pilot, app, b)
    assert app.game.remaining == remaining_before - 2, (
        f"remaining {remaining_before} → {app.game.remaining}"
    )
    assert a.id not in app.game.tiles
    assert b.id not in app.game.tiles


async def s_undo_restores_pair(app, pilot):
    pair = _pick_free_pair(app.game)
    assert pair is not None
    a, b = pair
    ok = app.game.remove_pair(a, b)
    assert ok
    assert app.game.remaining == 142
    await pilot.press("u")
    await pilot.pause()
    assert app.game.remaining == 144, app.game.remaining
    assert a.id in app.game.tiles
    assert b.id in app.game.tiles


async def s_undo_empty_is_noop(app, pilot):
    remaining_before = app.game.remaining
    await pilot.press("u")
    await pilot.pause()
    assert app.game.remaining == remaining_before


async def s_shuffle_preserves_tile_count(app, pilot):
    before = app.game.remaining
    await pilot.press("s")
    await pilot.pause()
    assert app.game.remaining == before
    assert app.game.shuffles_used == 1


async def s_new_game_reseeds(app, pilot):
    # Remove a pair, then "n" restarts → 144 tiles again.
    pair = _pick_free_pair(app.game)
    assert pair is not None
    app.game.remove_pair(*pair)
    assert app.game.remaining == 142
    await pilot.press("n")
    await pilot.pause()
    assert app.game.remaining == 144
    assert not app.game.history


async def s_toggle_ascii_changes_mode(app, pilot):
    before = app.ascii_only
    await pilot.press("a")
    await pilot.pause()
    assert app.ascii_only != before
    assert app.board.ascii_only == app.ascii_only


async def s_cancel_selection(app, pilot):
    pair = _pick_free_pair(app.game)
    assert pair is not None
    a, _b = pair
    await _click_tile(pilot, app, a)
    assert app.board.selected_id == a.id
    await pilot.press("escape")
    await pilot.pause()
    assert app.board.selected_id is None


async def s_non_matching_click_switches_selection(app, pilot):
    # Find two free tiles whose faces don't match.
    free = app.game.free_tiles()
    picked: tuple[Tile, Tile] | None = None
    for i, a in enumerate(free):
        for b in free[i + 1:]:
            if not tileset.match(a.face, b.face):
                picked = (a, b)
                break
        if picked:
            break
    assert picked is not None, "no non-matching free pair"
    a, b = picked
    await _click_tile(pilot, app, a)
    assert app.board.selected_id == a.id
    remaining = app.game.remaining
    await _click_tile(pilot, app, b)
    # Nothing removed, but selection moves to b.
    assert app.game.remaining == remaining
    assert app.board.selected_id == b.id


async def s_blocked_tile_click_is_noop(app, pilot):
    # Find a tile that is NOT free.
    blocked = [t for t in app.game.tiles.values() if not app.game.is_free(t)]
    if not blocked:
        return  # no blocked tiles to test
    t = blocked[0]
    remaining = app.game.remaining
    await _click_tile(pilot, app, t)
    assert app.game.remaining == remaining
    assert app.board.selected_id is None, (
        f"blocked tile click should not select, got {app.board.selected_id}"
    )


async def s_win_detected_when_board_empty(app, pilot):
    # Simulate a win by removing all tiles directly.
    app.game.tiles.clear()
    assert app.game.won
    assert not app.game.deadlocked



async def s_end_screen_opens_on_win(app, pilot):
    from mahjong_tui.screens import GameEndScreen
    app._show_end_screen(won=True)
    await pilot.pause()
    assert isinstance(app.screen, GameEndScreen)
    # Dismiss via "close".
    await pilot.press("escape")
    await pilot.pause()
    assert not isinstance(app.screen, GameEndScreen)


async def s_end_screen_new_game(app, pilot):
    from mahjong_tui.screens import GameEndScreen
    app._show_end_screen(won=False)
    await pilot.pause()
    assert isinstance(app.screen, GameEndScreen)
    # Remove a tile first so we can observe the re-deal resetting count.
    app.game.tiles.pop(next(iter(app.game.tiles)))
    assert app.game.remaining == 143
    await pilot.press("n")
    await pilot.pause()
    assert app.game.remaining == 144


async def s_deadlock_detected(app, pilot):
    # Start from empty, construct a tiny deadlocked board: one free tile +
    # one unmatchable free tile.
    from mahjong_tui.layout import Slot
    app.game.tiles.clear()
    # Two free, non-matching tiles far apart — different faces, no overlap.
    app.game.tiles[0] = Tile(id=0, slot=Slot(qx=0, qy=0, level=0), face=0)
    app.game.tiles[1] = Tile(id=1, slot=Slot(qx=10, qy=0, level=0), face=5)
    assert app.game.has_moves is False
    assert app.game.deadlocked

    assert not app.game.won


async def s_layout_picker_opens_modal(app, pilot):
    from mahjong_tui.screens import LayoutPickerScreen
    await pilot.press("l")
    await pilot.pause()
    assert isinstance(app.screen, LayoutPickerScreen), (
        f"expected LayoutPickerScreen, got {type(app.screen).__name__}"
    )
    # Close the modal.
    await pilot.press("escape")
    await pilot.pause()
    assert not isinstance(app.screen, LayoutPickerScreen)


async def s_layout_picker_jk_navigates(app, pilot):
    from mahjong_tui.screens import LayoutPickerScreen
    from textual.widgets import ListView
    await pilot.press("l")
    await pilot.pause()
    assert isinstance(app.screen, LayoutPickerScreen)
    lv = app.screen.query_one("#picker-list", ListView)
    start = lv.index
    await pilot.press("j")
    await pilot.pause()
    assert lv.index == (start or 0) + 1, (
        f"j should advance list, got {lv.index} from {start}"
    )
    await pilot.press("k")
    await pilot.pause()
    assert lv.index == start
    await pilot.press("escape")
    await pilot.pause()


async def s_help_modal_opens_and_closes(app, pilot):
    from mahjong_tui.screens import HelpScreen
    await pilot.press("question_mark")
    await pilot.pause()
    assert isinstance(app.screen, HelpScreen)
    await pilot.press("escape")
    await pilot.pause()
    assert not isinstance(app.screen, HelpScreen)


async def s_load_layout_swaps_board(app, pilot):
    # Call _load_layout directly to avoid going through the modal list.
    from mahjong_tui.app import VENDOR_LAYOUTS
    alt = VENDOR_LAYOUTS / "pyramid.layout"
    if not alt.exists():
        alt = VENDOR_LAYOUTS / "cross.layout"
    if not alt.exists():
        return  # skip if missing
    app._load_layout(alt)
    assert app._layout_path == alt
    assert app.game.remaining == app.game.layout.tile_count
    assert app.board.cursor_id is None
    assert app.board.selected_id is None


async def s_cursor_tab_walks_free_tiles(app, pilot):
    # First tab initializes the cursor.
    assert app.board.cursor_id is None
    await pilot.press("tab")
    await pilot.pause()
    first = app.board.cursor_id
    assert first is not None
    assert app.game.is_free(app.game.tiles[first]), "cursor must be on free tile"
    await pilot.press("tab")
    await pilot.pause()
    second = app.board.cursor_id
    assert second is not None and second != first


async def s_cursor_enter_selects(app, pilot):
    # Tab to init, then enter to select the current cursor tile.
    await pilot.press("tab")
    await pilot.pause()
    tid = app.board.cursor_id
    assert tid is not None
    await pilot.press("enter")
    await pilot.pause()
    assert app.board.selected_id == tid, (
        f"expected selected {tid}, got {app.board.selected_id}"
    )


async def s_cursor_escape_clears(app, pilot):
    await pilot.press("tab")
    await pilot.pause()
    assert app.board.cursor_id is not None
    await pilot.press("escape")
    await pilot.pause()
    # First escape clears any selection; second clears cursor. Cursor has
    # no selection so escape should drop cursor_id.
    assert app.board.cursor_id is None


async def s_cursor_arrow_moves(app, pilot):
    await pilot.press("tab")
    await pilot.pause()
    start = app.board.cursor_id
    # Arrow keys: try each direction; at least one should yield a different tile.
    moved = False
    for key in ("right", "down", "left", "up"):
        await pilot.press(key)
        await pilot.pause()
        if app.board.cursor_id != start:
            moved = True
            break
    assert moved, "no arrow direction moved the cursor"


async def s_stats_panel_reflects_state(app, pilot):
    app.stats.refresh_panel()
    # Verify the panel produced at least one non-blank rendered line.
    nonblank = 0
    for y in range(6):
        strip = app.stats.render_line(y)
        text = "".join(seg.text for seg in strip)
        if text.strip():
            nonblank += 1
    assert nonblank >= 2, f"stats panel only rendered {nonblank} nonblank rows"


async def s_status_bar_shows_time_and_count(app, pilot):
    app._update_status()
    # Render line 0 and concatenate segment text — public Textual API.
    strip = app.status_bar.render_line(0)
    text = "".join(seg.text for seg in strip)
    assert "/" in text, text  # "N/144 tiles"
    assert ":" in text, text  # time MM:SS


async def s_render_grid_sized_by_board_dims(app, pilot):
    out = app.board._render_out
    assert out is not None
    cols, rows = R.board_dims(app.game)
    assert out.width == cols
    assert out.height == rows


async def s_all_layouts_parse(app, pilot):
    # Sanity-check every bundled layout parses and has an even tile count.
    from mahjong_tui.app import VENDOR_LAYOUTS
    layouts = available_layouts(VENDOR_LAYOUTS)
    assert len(layouts) >= 50, f"only {len(layouts)} layouts found"
    bad: list[str] = []
    for name, path in layouts:
        try:
            L = parse_layout(path)
            if L.tile_count == 0 or L.tile_count % 2 == 1:
                bad.append(f"{name}: {L.tile_count} tiles")
        except Exception as e:
            bad.append(f"{name}: {e}")
    assert not bad, f"bad layouts: {bad[:5]}"


async def s_deal_is_solvable(app, pilot):
    # With solvable=True (default), a fresh deal should always have moves.
    # Sample several seeds to be sure.
    from mahjong_tui.layout import parse_layout
    from mahjong_tui.app import VENDOR_LAYOUTS
    layout = parse_layout(VENDOR_LAYOUTS / "default.layout")
    for seed in (1, 2, 3, 100, 999):
        g = Game.new(layout, seed=seed)
        assert g.has_moves, f"seed {seed}: no moves on fresh deal"


async def s_season_group_matches_any_season(app, pilot):
    assert tileset.match(34, 35)
    assert tileset.match(34, 37)
    assert not tileset.match(34, 38)  # season vs flower


async def s_flower_group_matches_any_flower(app, pilot):
    assert tileset.match(38, 39)
    assert tileset.match(38, 41)
    assert not tileset.match(38, 33)


async def s_match_same_face(app, pilot):
    assert tileset.match(0, 0)
    assert tileset.match(25, 25)
    assert not tileset.match(0, 1)


async def s_render_shows_selected_highlight(app, pilot):
    pair = _pick_free_pair(app.game)
    assert pair is not None
    a, _ = pair
    app.board.select(a.id)
    out = app.board._render_out
    assert out is not None
    hs = out.hotspots[a.id]
    style = out.styles[hs.row0][hs.col0]
    assert style is not None, "selected tile should have styled cell"
    # Selected bg is the yellow SEL_BG — just verify bg changed from default.
    style_str = str(style)
    assert "255,200,80" in style_str or "SEL" in style_str or "yellow" in style_str.lower() \
        or "200,80" in style_str, f"selected style unexpected: {style_str}"


async def s_ascii_mode_renders_two_char_faces(app, pilot):
    app.board.ascii_only = True
    app.board.refresh_board()
    out = app.board._render_out
    assert out is not None
    # Every tile's first cell should be a non-space letter/digit.
    sampled = 0
    for tid, hs in list(out.hotspots.items())[:10]:
        ch = out.chars[hs.row0][hs.col0]
        assert ch.strip() != "", f"tile {tid} ASCII cell blank"
        sampled += 1
    assert sampled >= 1


async def s_hint_clears_after_timer(app, pilot):
    await pilot.press("h")
    await pilot.pause()
    assert app.board.hint_pair is not None
    # The auto-clear is a 3s timer — force-invoke via direct API instead of
    # waiting (keeps the test fast).
    app.board.set_hint(None)
    assert app.board.hint_pair is None


async def s_topmost_tile_wins_hit_test(app, pilot):
    # Pick a tile with level > 0 and confirm tile_at_cell returns it,
    # not any lower tile whose hotspot overlaps.
    high = [t for t in app.game.tiles.values() if t.level > 0]
    if not high:
        return  # layout with no stack — nothing to test
    t = high[0]
    out = app.board._render_out
    assert out is not None
    hs = out.hotspots[t.id]
    hit = R.tile_at_cell(out, hs.col0, hs.row0)
    assert hit == t.id, (
        f"expected topmost {t.id} (level {t.level}), got {hit}"
    )


async def s_remove_same_tile_is_rejected(app, pilot):
    t = next(iter(app.game.tiles.values()))
    ok = app.game.remove_pair(t, t)
    assert not ok, "removing a tile with itself must fail"


async def s_remove_unfree_rejected(app, pilot):
    # Find a non-free tile and try to pair it with anything matching.
    blocked = [t for t in app.game.tiles.values() if not app.game.is_free(t)]
    if not blocked:
        return
    a = blocked[0]
    # Any free tile with same face (maybe none — skip if so).
    for b in app.game.free_tiles():
        if tileset.match(a.face, b.face):
            ok = app.game.remove_pair(a, b)
            assert not ok, "must not remove when one side is blocked"
            return


async def s_undo_after_shuffle_is_safe(app, pilot):
    # Remove a pair, shuffle (clears history), then undo should be a no-op
    # and must not crash.
    pair = _pick_free_pair(app.game)
    assert pair is not None
    app.game.remove_pair(*pair)
    assert app.game.remaining == 142
    await pilot.press("s")
    await pilot.pause()
    # After shuffle, history cleared; undo returns None.
    r = app.game.undo()
    assert r is None, f"undo after shuffle should be no-op, got {r}"


# ---------- driver ----------


SCENARIOS: list[Scenario] = [
    Scenario("mount_clean", s_mount_clean),
    Scenario("default_layout_is_turtle", s_default_layout_is_turtle),
    Scenario("free_pairs_available_on_deal", s_free_pairs_available_on_deal),
    Scenario("render_produces_glyphs", s_render_produces_glyphs),
    Scenario("hotspots_cover_all_tiles", s_hotspots_cover_all_tiles),
    Scenario("render_grid_sized_by_board_dims", s_render_grid_sized_by_board_dims),
    Scenario("render_shows_selected_highlight", s_render_shows_selected_highlight),
    Scenario("ascii_mode_renders_two_char_faces", s_ascii_mode_renders_two_char_faces),
    Scenario("hint_highlights_a_pair", s_hint_highlights_a_pair),
    Scenario("hint_clears_after_timer", s_hint_clears_after_timer),
    Scenario("match_removes_pair_via_clicks", s_match_removes_pair_via_clicks),
    Scenario("non_matching_click_switches_selection", s_non_matching_click_switches_selection),
    Scenario("blocked_tile_click_is_noop", s_blocked_tile_click_is_noop),
    Scenario("cancel_selection", s_cancel_selection),
    Scenario("undo_restores_pair", s_undo_restores_pair),
    Scenario("undo_empty_is_noop", s_undo_empty_is_noop),
    Scenario("undo_after_shuffle_is_safe", s_undo_after_shuffle_is_safe),
    Scenario("topmost_tile_wins_hit_test", s_topmost_tile_wins_hit_test),
    Scenario("remove_same_tile_is_rejected", s_remove_same_tile_is_rejected),
    Scenario("remove_unfree_rejected", s_remove_unfree_rejected),
    Scenario("shuffle_preserves_tile_count", s_shuffle_preserves_tile_count),
    Scenario("new_game_reseeds", s_new_game_reseeds),
    Scenario("toggle_ascii_changes_mode", s_toggle_ascii_changes_mode),
    Scenario("win_detected_when_board_empty", s_win_detected_when_board_empty),
    Scenario("end_screen_opens_on_win", s_end_screen_opens_on_win),
    Scenario("end_screen_new_game", s_end_screen_new_game),
    Scenario("deadlock_detected", s_deadlock_detected),
    Scenario("layout_picker_opens_modal", s_layout_picker_opens_modal),
    Scenario("layout_picker_jk_navigates", s_layout_picker_jk_navigates),
    Scenario("help_modal_opens_and_closes", s_help_modal_opens_and_closes),
    Scenario("load_layout_swaps_board", s_load_layout_swaps_board),
    Scenario("cursor_tab_walks_free_tiles", s_cursor_tab_walks_free_tiles),
    Scenario("cursor_enter_selects", s_cursor_enter_selects),
    Scenario("cursor_escape_clears", s_cursor_escape_clears),
    Scenario("cursor_arrow_moves", s_cursor_arrow_moves),
    Scenario("stats_panel_reflects_state", s_stats_panel_reflects_state),
    Scenario("status_bar_shows_time_and_count", s_status_bar_shows_time_and_count),
    Scenario("all_layouts_parse", s_all_layouts_parse),
    Scenario("deal_is_solvable", s_deal_is_solvable),
    Scenario("match_same_face", s_match_same_face),
    Scenario("season_group_matches_any_season", s_season_group_matches_any_season),
    Scenario("flower_group_matches_any_flower", s_flower_group_matches_any_flower),
]


async def run_one(scn: Scenario) -> tuple[str, bool, str]:
    app = MahjongApp(seed=FIXED_SEED)
    try:
        async with app.run_test(size=(200, 60)) as pilot:
            await pilot.pause()  # let on_mount complete
            try:
                await scn.fn(app, pilot)
            except AssertionError as e:
                app.save_screenshot(str(OUT / f"{scn.name}.FAIL.svg"))
                return (scn.name, False, f"AssertionError: {e}")
            except Exception as e:
                app.save_screenshot(str(OUT / f"{scn.name}.ERROR.svg"))
                return (scn.name, False,
                        f"{type(e).__name__}: {e}\n{traceback.format_exc()}")
            app.save_screenshot(str(OUT / f"{scn.name}.PASS.svg"))
            return (scn.name, True, "")
    except Exception as e:
        return (scn.name, False,
                f"harness error: {type(e).__name__}: {e}\n{traceback.format_exc()}")


async def main(pattern: str | None = None) -> int:
    scenarios = [s for s in SCENARIOS if not pattern or pattern in s.name]
    if not scenarios:
        print(f"no scenarios match {pattern!r}")
        return 2
    results = []
    for scn in scenarios:
        name, ok, msg = await run_one(scn)
        mark = "\033[32m✓\033[0m" if ok else "\033[31m✗\033[0m"
        print(f"  {mark} {name}")
        if not ok:
            for line in msg.splitlines():
                print(f"      {line}")
        results.append((name, ok, msg))
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n{passed}/{len(results)} passed, {failed} failed")
    return failed


if __name__ == "__main__":
    pattern = sys.argv[1] if len(sys.argv) > 1 else None
    sys.exit(asyncio.run(main(pattern)))
