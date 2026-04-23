"""Entry point — `python mahjong.py [--layout NAME] [--seed N] [--ascii]`."""

from __future__ import annotations

import argparse
from pathlib import Path

from mahjong_tui.app import run, VENDOR_LAYOUTS, USER_LAYOUTS
from mahjong_tui.layout import available_layouts


def main() -> None:
    p = argparse.ArgumentParser(prog="mahjong-tui")
    p.add_argument("--layout", default=None,
                   help="layout name (e.g. 'default', 'pyramid') or a path to a .layout file")
    p.add_argument("--seed", type=int, default=None,
                   help="RNG seed for the deal (lets you replay the same game)")
    p.add_argument("--ascii", action="store_true",
                   help="use ASCII tile abbreviations instead of Unicode tiles")
    p.add_argument("--list-layouts", action="store_true",
                   help="print the names of all available layouts and exit")
    args = p.parse_args()

    if args.list_layouts:
        for name, path in available_layouts(USER_LAYOUTS, VENDOR_LAYOUTS):
            print(f"{name:20s} {path}")
        return

    layout_path: Path | None = None
    if args.layout:
        candidate = Path(args.layout)
        if candidate.is_file():
            layout_path = candidate
        else:
            # Treat as a stem name — look in user + vendor dirs.
            for d in (USER_LAYOUTS, VENDOR_LAYOUTS):
                maybe = d / f"{args.layout}.layout"
                if maybe.exists():
                    layout_path = maybe
                    break
            if layout_path is None:
                p.error(f"layout {args.layout!r} not found")

    run(layout_path, seed=args.seed, ascii_only=args.ascii)


if __name__ == "__main__":
    main()
