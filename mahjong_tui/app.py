"""Textual app — 3-panel Mahjong Solitaire."""

from __future__ import annotations

import random
import time
from pathlib import Path

from rich.text import Text
from rich.style import Style
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.geometry import Size
from textual.reactive import reactive
from textual.scroll_view import ScrollView
from textual.strip import Strip
from textual.widgets import Footer, Header, Static

from . import render as R
from . import tiles as tileset
from .game import Game, Tile
from .layout import Layout, parse_layout, available_layouts, load_desktop_metadata
from .screens import HelpScreen, LayoutPickerScreen, GameEndScreen


VENDOR_LAYOUTS = Path(__file__).resolve().parent.parent / "vendor" / "kmahjongg" / "layouts"
USER_LAYOUTS = Path.home() / ".local" / "share" / "mahjong-tui" / "layouts"


def default_layout_path() -> Path:
    """The Turtle layout — the canonical starter."""
    return VENDOR_LAYOUTS / "default.layout"


class BoardView(ScrollView):
    """Renders the tile stack + handles clicks."""

    DEFAULT_CSS = """
    BoardView { padding: 0; }
    """

    # A small cursor for keyboard play — walks through free tiles.
    cursor_id: reactive[int | None] = reactive(None)

    def __init__(self, game: Game, *, ascii_only: bool = False) -> None:
        super().__init__()
        self.game = game
        self.ascii_only = ascii_only
        self.selected_id: int | None = None
        self.hint_pair: tuple[int, int] | None = None
        # Cached render output — rebuilt when state changes.
        self._render_out: R.RenderOutput | None = None
        self._virtual_sized = False

    # ---- lifecycle -----------------------------------------------------

    def on_mount(self) -> None:
        self._rebuild()

    def _rebuild(self) -> None:
        """Rebuild the char + style grid from current game state."""
        self._render_out = R.render_board(
            self.game,
            ascii_only=self.ascii_only,
            selected_id=self.selected_id,
            hint_ids=self.hint_pair,
            cursor_id=self.cursor_id,
        )
        if not self._virtual_sized:
            self.virtual_size = Size(
                self._render_out.width, self._render_out.height
            )
            self._virtual_sized = True
        self.refresh()

    def refresh_board(self) -> None:
        self._rebuild()

    # ---- rendering -----------------------------------------------------

    def render_line(self, y: int) -> Strip:
        width = self.size.width
        if self._render_out is None:
            return Strip.blank(width)
        tile_y = y + int(self.scroll_offset.y)
        segments = R.strip_for_row(self._render_out, tile_y, max_width=width)
        return Strip(segments, width)

    # ---- selection -----------------------------------------------------

    def select(self, tile_id: int | None) -> None:
        """Highlight a tile. Called by the App when the user clicks or
        moves the keyboard cursor."""
        self.selected_id = tile_id
        self._rebuild()

    def set_hint(self, pair: tuple[int, int] | None) -> None:
        self.hint_pair = pair
        self._rebuild()

    # ---- mouse ---------------------------------------------------------

    def on_click(self, event: events.Click) -> None:
        if self._render_out is None:
            return
        # Widget-relative coords + scroll offset → virtual grid coords.
        col = event.x + int(self.scroll_offset.x)
        row = event.y + int(self.scroll_offset.y)
        # tile_at_cell breaks ties by level (topmost wins).
        best_id = R.tile_at_cell(self._render_out, col, row)
        if best_id is None:
            return
        # Post a message the App handles — keeps mouse + keyboard unified.
        self.post_message(self.TileClicked(best_id))

    class TileClicked(events.Message):
        def __init__(self, tile_id: int) -> None:
            self.tile_id = tile_id
            super().__init__()


class StatsPanel(Static):
    """Tiles remaining, matches made, elapsed time."""

    def __init__(self, game: Game) -> None:
        super().__init__()
        self.game = game
        self.border_title = "STATS"
        self._last_tuple: tuple | None = None

    def refresh_panel(self) -> None:
        g = self.game
        total = g.layout.tile_count
        removed = total - g.remaining()
        pairs_removed = removed // 2
        total_pairs = total // 2
        elapsed = int(g.elapsed())
        mm, ss = divmod(elapsed, 60)
        snap = (g.remaining(), pairs_removed, elapsed // 5, g.hints_used,
                g.shuffles_used, g.layout.name)
        if snap == self._last_tuple:
            return
        self._last_tuple = snap
        t = Text()
        t.append(f"Layout   {g.layout.name}\n", style="bold cyan")
        t.append(f"Tiles    {g.remaining()}/{total}\n")
        t.append(f"Pairs    {pairs_removed}/{total_pairs}\n")
        t.append(f"Time     {mm:02d}:{ss:02d}\n", style="bold")
        t.append(f"Hints    {g.hints_used}\n", style="dim")
        t.append(f"Shuffles {g.shuffles_used}\n", style="dim")
        self.update(t)


class InfoPanel(Static):
    """Selected tile + status messages."""

    def __init__(self) -> None:
        super().__init__()
        self.border_title = "INFO"
        self._msg: str = (
            "Click a free (bright) tile to select. Click a matching free "
            "tile to remove the pair."
        )

    def show(self, msg: str) -> None:
        self._msg = msg
        self.update(Text.from_markup(self._msg))

    def refresh_panel(self) -> None:
        self.update(Text.from_markup(self._msg))


class HelpPanel(Static):
    """Keybindings legend."""

    def __init__(self) -> None:
        super().__init__()
        self.border_title = "CONTROLS"

    def refresh_panel(self) -> None:
        t = Text.from_markup(
            "[bold]Mouse[/]\n"
            "  click free tile → select\n"
            "  click matching free tile → remove pair\n\n"
            "[bold]Keys[/]\n"
            "  [yellow]h[/]  hint — highlight a valid pair\n"
            "  [yellow]u[/]  undo last move\n"
            "  [yellow]s[/]  shuffle remaining tiles\n"
            "  [yellow]n[/]  new game (same layout)\n"
            "  [yellow]l[/]  change layout\n"
            "  [yellow]a[/]  toggle ASCII/Unicode glyphs\n"
            "  [yellow]q[/]  quit\n\n"
            "[dim]free = bright tile face[/]\n"
            "[dim]blocked = dim tile face[/]"
        )
        self.update(t)


class MahjongApp(App):
    CSS_PATH = "tui.tcss"
    TITLE = "Mahjong Solitaire — Terminal"

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("h", "hint", "Hint"),
        Binding("u", "undo", "Undo"),
        Binding("s", "shuffle", "Shuffle"),
        Binding("n", "new_game", "New"),
        Binding("l", "layout_picker", "Layout"),
        Binding("a", "toggle_ascii", "ASCII"),
        Binding("question_mark", "help", "Help"),
        Binding("up", "cursor_move('up')", "↑", show=False, priority=True),
        Binding("down", "cursor_move('down')", "↓", show=False, priority=True),
        Binding("left", "cursor_move('left')", "←", show=False, priority=True),
        Binding("right", "cursor_move('right')", "→", show=False, priority=True),
        Binding("tab", "cursor_move('next')", "Next free", show=False, priority=True),
        Binding("shift+tab", "cursor_move('prev')", "Prev free", show=False, priority=True),
        Binding("enter", "cursor_confirm", "Pick", show=False, priority=True),
        Binding("space", "cursor_confirm", "Pick", show=False, priority=True),
        Binding("escape", "cancel_selection", "Cancel", show=False),
    ]

    def __init__(
        self,
        layout_path: str | Path | None = None,
        *,
        seed: int | None = None,
        ascii_only: bool = False,
    ) -> None:
        super().__init__()
        self._layout_path = Path(layout_path) if layout_path else default_layout_path()
        self._seed = seed if seed is not None else random.randint(0, 2**31 - 1)
        self.ascii_only = ascii_only
        layout = parse_layout(self._layout_path)
        # Friendly name from .desktop sidecar, fall back to file stem.
        meta = load_desktop_metadata(self._layout_path.with_suffix(".desktop"))
        layout.name = meta.get("Name", layout.name)
        self.game = Game.new(layout, seed=self._seed)
        self.board = BoardView(self.game, ascii_only=ascii_only)
        self.stats = StatsPanel(self.game)
        self.info = InfoPanel()
        self.help_panel = HelpPanel()
        self.status_bar = Static(" ", id="status-bar")

    # ---- layout --------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="board-col"):
                yield self.board
                yield self.status_bar
            with Vertical(id="side"):
                yield self.stats
                yield self.info
                yield self.help_panel
        yield Footer()

    async def on_mount(self) -> None:
        self.board.border_title = (
            f"{self.game.layout.name}  —  "
            f"{self.game.layout.tile_count} tiles"
        )
        self.stats.refresh_panel()
        self.info.refresh_panel()
        self.help_panel.refresh_panel()
        self._update_status()
        self.set_interval(0.5, self._tick)

    def _tick(self) -> None:
        self.stats.refresh_panel()
        self._update_status()

    def _update_status(self) -> None:
        g = self.game
        total = g.layout.tile_count
        removed = total - g.remaining()
        elapsed = int(g.elapsed())
        mm, ss = divmod(elapsed, 60)
        moves = "free pair available" if g.has_moves() else "[red]DEADLOCK[/]"
        self.status_bar.update(Text.from_markup(
            f"[bold]{g.layout.name}[/]  ·  {g.remaining()}/{total} tiles  ·  "
            f"{mm:02d}:{ss:02d}  ·  {moves}"
        ))

    # ---- actions -------------------------------------------------------

    def action_hint(self) -> None:
        pairs = self.game.free_pairs()
        if not pairs:
            self.info.show("[red]No moves available — try shuffle.[/]")
            return
        a, b = pairs[0]
        self.game.hints_used += 1
        self.board.set_hint((a.id, b.id))
        self.info.show(
            f"[cyan]Hint:[/] [bold]{tileset.FACES[a.face].name}[/] at "
            f"({a.qx},{a.qy},L{a.level}) + ({b.qx},{b.qy},L{b.level})"
        )
        # Clear the hint after a short delay so it doesn't linger.
        self.set_timer(3.0, lambda: (
            self.board.set_hint(None), self.info.refresh_panel()
        ))

    def action_undo(self) -> None:
        r = self.game.undo()
        if r is None:
            self.info.show("[yellow]Nothing to undo.[/]")
            return
        self.board.select(None)
        self.board.refresh_board()
        self.info.show(f"[green]Undo:[/] restored tiles #{r[0]} & #{r[1]}.")
        self.stats.refresh_panel()

    def action_shuffle(self) -> None:
        self.game.shuffle()
        self.board.select(None)
        self.board.set_hint(None)
        self.board.refresh_board()
        self.info.show(
            f"[cyan]Shuffled.[/] ({self.game.shuffles_used} used) — history cleared."
        )
        # Shuffle invalidates history — we keep it for undo-past-shuffle,
        # but the restored tile positions may not align with the new face
        # assignments. Clear to keep undo honest.
        self.game.history.clear()
        self.game._removed.clear()
        self.stats.refresh_panel()

    def action_new_game(self) -> None:
        self.game = Game.new(self.game.layout, seed=random.randint(0, 2**31 - 1))
        self.board.game = self.game
        self.stats.game = self.game
        self.board.select(None)
        self.board.set_hint(None)
        self.board._virtual_sized = False  # may change size across layouts
        self.board.refresh_board()
        self.info.show("[green]New game dealt.[/]")
        self.stats.refresh_panel()

    def action_layout_picker(self) -> None:
        """Open a modal picker over all bundled + user layouts."""

        def _picked(path: Path | None) -> None:
            if path is None:
                return
            self._load_layout(path)

        self.push_screen(
            LayoutPickerScreen(USER_LAYOUTS, VENDOR_LAYOUTS,
                               current=self._layout_path),
            _picked,
        )

    def _load_layout(self, path: Path) -> None:
        """Swap the current layout and re-deal. Used by the layout picker."""
        self._layout_path = path
        layout = parse_layout(path)
        meta = load_desktop_metadata(path.with_suffix(".desktop"))
        layout.name = meta.get("Name", layout.name)
        self.game = Game.new(layout, seed=random.randint(0, 2**31 - 1))
        self.board.game = self.game
        self.stats.game = self.game
        self.board.select(None)
        self.board.set_hint(None)
        self.board.cursor_id = None
        self.board._virtual_sized = False
        self.board.refresh_board()
        self.board.border_title = (
            f"{self.game.layout.name}  —  {self.game.layout.tile_count} tiles"
        )
        self.info.show(f"[cyan]Layout:[/] {self.game.layout.name}")
        self.stats.refresh_panel()

    def action_toggle_ascii(self) -> None:
        self.ascii_only = not self.ascii_only
        self.board.ascii_only = self.ascii_only
        self.board.refresh_board()
        mode = "ASCII" if self.ascii_only else "Unicode"
        self.info.show(f"[cyan]Glyphs:[/] {mode}")

    def action_cancel_selection(self) -> None:
        if self.board.selected_id is not None:
            self.board.select(None)
            self.info.show("Selection cleared.")
        elif self.board.cursor_id is not None:
            self.board.cursor_id = None
            self.board.refresh_board()

    # ---- keyboard cursor ----------------------------------------------

    def action_cursor_move(self, direction: str) -> None:
        """Walk through free tiles by direction.

        'next'/'prev' step through the free-tile list in ID order.
        'up'/'down'/'left'/'right' pick the nearest free tile in that
        direction in grid coordinates.
        """
        free = sorted(self.game.free_tiles(),
                      key=lambda t: (t.qy, t.qx, t.level))
        if not free:
            return
        cur_id = self.board.cursor_id
        cur_tile = self.game.tiles.get(cur_id) if cur_id is not None else None
        if cur_tile is None or cur_id not in {t.id for t in free}:
            # No cursor yet — anchor at the first free tile.
            self.board.cursor_id = free[0].id
            self.board.refresh_board()
            return
        if direction in ("next", "prev"):
            ids = [t.id for t in free]
            i = ids.index(cur_id)
            step = 1 if direction == "next" else -1
            self.board.cursor_id = ids[(i + step) % len(ids)]
        else:
            # Nearest free tile in the given direction by grid position.
            cx, cy, cl = cur_tile.qx, cur_tile.qy, cur_tile.level
            candidates: list[Tile] = []
            for t in free:
                if t.id == cur_id:
                    continue
                dx, dy = t.qx - cx, t.qy - cy
                if direction == "up" and dy < 0:
                    candidates.append(t)
                elif direction == "down" and dy > 0:
                    candidates.append(t)
                elif direction == "left" and dx < 0:
                    candidates.append(t)
                elif direction == "right" and dx > 0:
                    candidates.append(t)
            if not candidates:
                return
            # Pick closest by manhattan distance (y-weighted so up/down
            # prefers tiles in the same column).
            if direction in ("up", "down"):
                candidates.sort(key=lambda t: (abs(t.qy - cy), abs(t.qx - cx)))
            else:
                candidates.sort(key=lambda t: (abs(t.qx - cx), abs(t.qy - cy)))
            self.board.cursor_id = candidates[0].id
        self.board.refresh_board()

    def action_cursor_confirm(self) -> None:
        """Enter/Space on the cursor: treat like a click on the current
        cursor tile."""
        tid = self.board.cursor_id
        if tid is None:
            # Initialize cursor instead.
            self.action_cursor_move("next")
            return
        if tid not in self.game.tiles:
            return
        self.post_message(BoardView.TileClicked(tid))

    # ---- modals --------------------------------------------------------

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def _show_end_screen(self, *, won: bool) -> None:
        def _done(action: str | None) -> None:
            if action == "new":
                self.action_new_game()
            elif action == "shuffle":
                self.action_shuffle()
            # "close" / None: just dismiss — player keeps the board open.

        g = self.game
        self.push_screen(
            GameEndScreen(
                won=won,
                elapsed_s=int(g.elapsed()),
                hints=g.hints_used,
                shuffles=g.shuffles_used,
                remaining=g.remaining(),
            ),
            _done,
        )

    # ---- message handlers ---------------------------------------------

    def on_board_view_tile_clicked(self, message: BoardView.TileClicked) -> None:
        tid = message.tile_id
        tile = self.game.tiles.get(tid)
        if tile is None:
            return
        if not self.game.is_free(tile):
            self.info.show(
                f"[red]Blocked:[/] {tileset.FACES[tile.face].name} is not free."
            )
            return
        sel = self.board.selected_id
        if sel is None:
            self.board.select(tid)
            self.info.show(
                f"[yellow]Selected[/] [bold]{tileset.FACES[tile.face].name}[/] "
                f"at ({tile.qx},{tile.qy},L{tile.level})"
            )
            return
        if sel == tid:
            self.board.select(None)
            self.info.show("Deselected.")
            return
        sel_tile = self.game.tiles[sel]
        if self.game.remove_pair(sel_tile, tile):
            self.board.select(None)
            self.board.set_hint(None)
            # Cursor may be on a just-removed tile — clear.
            if self.board.cursor_id in (sel_tile.id, tile.id):
                self.board.cursor_id = None
            self.board.refresh_board()
            self.info.show(
                f"[green]Pair removed:[/] "
                f"{tileset.FACES[sel_tile.face].name} + "
                f"{tileset.FACES[tile.face].name}"
            )
            self.stats.refresh_panel()
            if self.game.won():
                self._show_end_screen(won=True)
            elif self.game.deadlocked():
                self._show_end_screen(won=False)
        else:
            # Not a match — switch selection to the new tile.
            self.board.select(tid)
            self.info.show(
                f"[red]No match.[/] Selected "
                f"[bold]{tileset.FACES[tile.face].name}[/] instead."
            )


def run(layout_path: str | Path | None = None, *, seed: int | None = None,
        ascii_only: bool = False) -> None:
    app = MahjongApp(layout_path, seed=seed, ascii_only=ascii_only)
    try:
        app.run()
    finally:
        import sys
        sys.stdout.write(
            "\033[?1000l\033[?1002l\033[?1003l\033[?1006l\033[?1015l\033[?25h"
        )
        sys.stdout.flush()
