"""Modal screens: Help / LayoutPicker / Win / Deadlock."""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static, ListView, ListItem, Label

from .layout import parse_layout, load_desktop_metadata, available_layouts


class HelpScreen(ModalScreen[None]):
    """Legend + controls reference."""

    BINDINGS = [
        Binding("escape,q,question_mark", "dismiss", "Close", priority=True),
    ]

    DEFAULT_CSS = """
    HelpScreen { align: center middle; }
    HelpScreen > Vertical {
        width: 70;
        height: auto;
        max-height: 90%;
        background: #0e0e10;
        border: round #6b4f2a;
        padding: 1 2;
    }
    HelpScreen .title {
        color: #f0c080;
        text-style: bold;
        content-align: center middle;
        width: 100%;
        margin-bottom: 1;
    }
    """

    def compose(self):
        with Vertical():
            yield Static("Mahjong Solitaire — HELP", classes="title")
            yield Static(Text.from_markup(
                "[bold]Goal[/]\n"
                "  Remove all 144 tiles by matching free pairs.\n\n"
                "[bold]A tile is FREE when[/]\n"
                "  · nothing sits on top, AND\n"
                "  · its left OR right side is clear.\n\n"
                "[bold]Matching[/]\n"
                "  Identical faces match. Any two seasons match each\n"
                "  other. Any two flowers match each other.\n\n"
                "[bold]Mouse[/]\n"
                "  click free tile → select\n"
                "  click matching free tile → remove pair\n\n"
                "[bold]Keys[/]\n"
                "  [yellow]arrows[/]  move cursor through free tiles\n"
                "  [yellow]enter/space[/]  select / confirm pair\n"
                "  [yellow]h[/]  hint — highlight a valid pair\n"
                "  [yellow]u[/]  undo last move\n"
                "  [yellow]s[/]  shuffle remaining tiles\n"
                "  [yellow]n[/]  new game (same layout)\n"
                "  [yellow]l[/]  layout picker\n"
                "  [yellow]a[/]  toggle ASCII/Unicode glyphs\n"
                "  [yellow]?[/]  this help\n"
                "  [yellow]q[/]  quit\n\n"
                "[dim]free = bright tile face    blocked = dim[/]\n\n"
                "[dim]Press escape to close.[/]"
            ))


class LayoutPickerScreen(ModalScreen[Path | None]):
    """Pick a layout from the bundled + user-dropped catalog."""

    BINDINGS = [
        Binding("escape,q", "dismiss(None)", "Cancel", priority=True),
        Binding("enter", "pick", "Pick", priority=True),
        # App has priority=True on arrows for board cursor nav — per the
        # tui-game-build skill, priority App bindings beat ModalScreen
        # bindings even if the modal also sets priority=True. Use j/k so
        # the player can still navigate the list without conflict.
        Binding("k", "nav(-1)", "Up", show=False),
        Binding("j", "nav(1)", "Down", show=False),
    ]

    DEFAULT_CSS = """
    LayoutPickerScreen { align: center middle; }
    LayoutPickerScreen > Vertical {
        width: 60;
        height: 30;
        background: #0e0e10;
        border: round #6b4f2a;
        padding: 1 2;
    }
    LayoutPickerScreen .title {
        color: #f0c080;
        text-style: bold;
        content-align: center middle;
        width: 100%;
    }
    LayoutPickerScreen ListView {
        height: 1fr;
        background: transparent;
    }
    LayoutPickerScreen ListItem {
        padding: 0 1;
    }
    """

    def __init__(self, user_dir: Path, vendor_dir: Path,
                 current: Path | None = None) -> None:
        super().__init__()
        self._user_dir = user_dir
        self._vendor_dir = vendor_dir
        self._current = current
        self._layouts = available_layouts(user_dir, vendor_dir)

    def compose(self):
        with Vertical():
            yield Static("Pick a Layout  (j/k move, enter pick, esc cancel)",
                         classes="title")
            items: list[ListItem] = []
            initial = 0
            for i, (name, path) in enumerate(self._layouts):
                # Read desktop metadata for a friendly name if available.
                meta = load_desktop_metadata(path.with_suffix(".desktop"))
                pretty = meta.get("Name", name)
                try:
                    lay = parse_layout(path)
                    label = f"{pretty:<22}  {lay.tile_count:>3} tiles  d{lay.depth}"
                except Exception:
                    label = f"{pretty:<22}  (parse failed)"
                items.append(ListItem(Label(label), id=f"ly-{i}"))
                if self._current and path == self._current:
                    initial = i
            lv = ListView(*items, initial_index=initial, id="picker-list")
            yield lv

    def action_pick(self) -> None:
        lv = self.query_one("#picker-list", ListView)
        idx = lv.index if lv.index is not None else 0
        if 0 <= idx < len(self._layouts):
            _n, path = self._layouts[idx]
            self.dismiss(path)
        else:
            self.dismiss(None)

    def action_nav(self, delta: int) -> None:
        lv = self.query_one("#picker-list", ListView)
        cur = lv.index if lv.index is not None else 0
        new = max(0, min(len(self._layouts) - 1, cur + delta))
        lv.index = new

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Double-click / enter on the list — same as action_pick."""
        idx = self.query_one("#picker-list", ListView).index
        if idx is not None and 0 <= idx < len(self._layouts):
            _n, path = self._layouts[idx]
            self.dismiss(path)


class GameEndScreen(ModalScreen[str]):
    """Shown on win OR deadlock. Offers New Game / Shuffle / Close.

    Returns the action string ("new", "shuffle", "close") so the app can
    react appropriately.
    """

    BINDINGS = [
        Binding("n", "dismiss('new')", "New", priority=True),
        Binding("s", "dismiss('shuffle')", "Shuffle", priority=True),
        Binding("escape,q", "dismiss('close')", "Close", priority=True),
    ]

    DEFAULT_CSS = """
    GameEndScreen { align: center middle; }
    GameEndScreen > Vertical {
        width: 60;
        height: auto;
        background: #0e0e10;
        border: round #6b4f2a;
        padding: 1 2;
    }
    GameEndScreen .title {
        text-style: bold;
        content-align: center middle;
        width: 100%;
    }
    """

    def __init__(self, *, won: bool, elapsed_s: int,
                 hints: int, shuffles: int, remaining: int) -> None:
        super().__init__()
        self._won = won
        self._elapsed = elapsed_s
        self._hints = hints
        self._shuffles = shuffles
        self._remaining = remaining

    def compose(self):
        mm, ss = divmod(self._elapsed, 60)
        with Vertical():
            if self._won:
                yield Static(Text.from_markup(
                    "[bold green]YOU WIN![/]\n"
                    f"Cleared in [bold]{mm:02d}:{ss:02d}[/]"
                ), classes="title")
                body = (
                    f"\nHints used:    {self._hints}\n"
                    f"Shuffles used: {self._shuffles}\n\n"
                    "[yellow]n[/] new game   "
                    "[yellow]esc[/] back to board"
                )
            else:
                yield Static(Text.from_markup(
                    "[bold red]DEADLOCK[/]\n"
                    f"{self._remaining} tiles remain  ·  "
                    f"no free matching pair."
                ), classes="title")
                body = (
                    "\n[yellow]s[/] shuffle (re-deal remaining)\n"
                    "[yellow]n[/] new game\n"
                    "[yellow]esc[/] back to board (undo allowed)"
                )
            yield Static(Text.from_markup(body))


__all__ = ["HelpScreen", "LayoutPickerScreen", "GameEndScreen"]
