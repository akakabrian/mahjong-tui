"""Pexpect-driven playtest: boots `make run` in a pty, drives a short
keyboard session, and saves SVG snapshots at each step to tests/out/.

Goal: smoke-test the real binary end-to-end in a real terminal — this
catches regressions that Textual's `run_test` pilot can miss (e.g. ANSI
escape bugs, resize handling, startup crashes).
"""
from __future__ import annotations

import os
import sys
import time
from html import escape
from pathlib import Path

import pexpect
import pyte

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "tests" / "out"
OUT.mkdir(parents=True, exist_ok=True)
COLS, ROWS = 200, 60


def _snapshot_svg(screen: pyte.Screen, path: Path) -> None:
    lines = [escape(line.rstrip()) for line in screen.display]
    char_w, line_h = 8, 16
    w = char_w * screen.columns
    h = line_h * screen.lines
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'font-family="monospace" font-size="13" viewBox="0 0 {w} {h}">',
        f'<rect width="{w}" height="{h}" fill="#111"/>',
    ]
    for i, text in enumerate(lines):
        y = (i + 1) * line_h - 4
        parts.append(f'<text x="0" y="{y}" fill="#eee" xml:space="preserve">{text}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts), encoding="utf-8")


def _drain(child: pexpect.spawn, screen: pyte.Screen, stream: pyte.Stream,
           settle: float = 0.4) -> None:
    end = time.time() + settle
    while time.time() < end:
        try:
            chunk = child.read_nonblocking(size=65536, timeout=0.1)
        except pexpect.TIMEOUT:
            continue
        except pexpect.EOF:
            return
        stream.feed(chunk)


def main() -> int:
    os.environ["TERM"] = "xterm-256color"
    os.environ["LINES"] = str(ROWS)
    os.environ["COLUMNS"] = str(COLS)
    child = pexpect.spawn(
        str(ROOT / ".venv" / "bin" / "python"),
        ["mahjong.py", "--seed", "48879"],
        cwd=str(ROOT), encoding="utf-8", dimensions=(ROWS, COLS),
        timeout=10,
    )
    screen = pyte.Screen(COLS, ROWS)
    stream = pyte.Stream(screen)

    steps = [
        ("boot",      None,       1.2),
        ("arrows",    ["\x1b[C", "\x1b[C", "\x1b[B"], 0.5),  # right, right, down
        ("hint",      ["h"],      0.6),  # highlight a valid free pair
        ("pick_a",    ["\t"],     0.4),  # tab to a free tile
        ("pick_b",    ["\r"],     0.4),  # enter → select it
        ("pick_c",    ["\t", "\r"], 0.5),  # next free + enter (attempt match)
        ("undo",      ["u"],      0.4),
        ("layout_open",  ["l"],   0.6),
        ("layout_close", ["\x1b"], 0.4),
        ("quit",      ["q"],      0.6),
    ]
    for name, keys, settle in steps:
        if keys:
            for k in keys:
                child.send(k)
                time.sleep(0.05)
        _drain(child, screen, stream, settle=settle)
        _snapshot_svg(screen, OUT / f"playtest_{name}.svg")
        print(f"  snapshot playtest_{name}.svg")

    child.close(force=True)
    print(f"\nplaytest OK — {len(steps)} snapshots in {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
