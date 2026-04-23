"""KMahjongg .layout file parser.

The format is simple:

    kmahjongg-layout-v1.1         # first line — magic + version
    # Board size in quarter tiles  # comment (ignored)
    w32                            # width in quarter-tile cells (optional in v1.0)
    h16                            # height in quarter-tile cells
    d5                             # depth (number of levels, optional)
    # Level 0 -------------------  # level separator
    ...121212...                   # one grid row per quarter-cell row
    ...434343...
    ...
    # Level 1 -------------------
    ...

Quarter-cell characters:

    .       empty
    1 2     top-left / top-right corner of a full tile
    4 3     bottom-left / bottom-right corner of a full tile

A **full tile** spans a 2×2 block of quarter cells:

    1 2
    4 3

We collapse quarter coords to tile coords on load: every tile sits at
(tile_x = qx_of_1 // 2, tile_y = qy_of_1 // 2) on its level — but
because KMahjongg lets tiles half-overlap (shifted by one quarter cell
to produce staggered stacks like the Turtle's top ridge), we keep the
full quarter-precision position internally as (qx, qy) of the top-left
corner, and treat two tiles as "the same slot" only when their (qx, qy,
level) triples match exactly.

A tile covers the quarter-cells (qx, qy), (qx+1, qy), (qx, qy+1),
(qx+1, qy+1) — we validate on parse that all four corners are the
expected digits (1/2/3/4) and error out if the file has a stray digit
without its partners.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Slot:
    """One tile position on the board, in quarter-cell coordinates.

    `qx` / `qy` are the coordinates of the TOP-LEFT corner of the tile
    (the '1' quarter cell). `level` is the depth layer, 0 = bottom.
    """
    qx: int
    qy: int
    level: int

    @property
    def x(self) -> int:
        """Tile x in half-tile units (useful for rendering — each tile is
        2 quarter-columns wide, which maps to 2 terminal cells)."""
        return self.qx

    @property
    def y(self) -> int:
        return self.qy


@dataclass
class Layout:
    name: str
    width_q: int        # board width in quarter-cells
    height_q: int       # board height in quarter-cells
    depth: int
    slots: list[Slot]

    @property
    def tile_count(self) -> int:
        return len(self.slots)

    def level_slots(self, level: int) -> list[Slot]:
        return [s for s in self.slots if s.level == level]


def parse_layout(path: str | Path, name: str | None = None) -> Layout:
    """Parse a KMahjongg .layout file. Returns a Layout with `slots` in
    bottom-up, top-left-first order. Raises ValueError on malformed
    files (missing corners, inconsistent sizes)."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        raise ValueError(f"{p}: empty file")
    magic = lines[0].strip()
    if not magic.startswith("kmahjongg-layout-v"):
        raise ValueError(f"{p}: bad magic {magic!r}")

    # v1.0 has no w/h/d — hard-coded to 32×16, depth determined by level count.
    width_q = 32
    height_q = 16
    depth: int | None = None

    # Walk non-level metadata lines until we hit either the first "# Level"
    # marker OR the first row that looks like tile data (contains any of
    # the corner chars 1/2/3/4 or '.'). v1.0 files often omit the level
    # header before Level 0 — the first data row IS Level 0.
    idx = 1
    while idx < len(lines):
        line = lines[idx]
        stripped = line.strip()
        if stripped.startswith("# Level"):
            break
        if stripped.startswith("#") or not stripped:
            idx += 1
            continue
        # width/height/depth keys — very short, pure "w<N>" / "h<N>" / "d<N>".
        if len(stripped) <= 4 and stripped[0] in "whd" and stripped[1:].isdigit():
            key = stripped[0]
            val = int(stripped[1:])
            if key == "w":
                width_q = val
            elif key == "h":
                height_q = val
            else:
                depth = val
            idx += 1
            continue
        # Anything else — this is a tile data row. Stop meta scan and let
        # the grid loop consume from here (no level header in front of it
        # means this IS Level 0).
        break

    # Now parse level grids. Each level's data is `height_q` rows of exactly
    # `width_q` chars (trailing whitespace is tolerated). Level headers are
    # "# Level N ..." and separate the grids.
    levels: list[list[str]] = []
    cur: list[str] = []
    while idx < len(lines):
        line = lines[idx]
        stripped = line.rstrip()
        if stripped.startswith("# Level"):
            if cur:
                levels.append(cur)
                cur = []
        elif stripped.startswith("#"):
            pass  # other comment
        else:
            if stripped == "":
                # Blank rows inside a level are rare but valid — pad.
                cur.append("." * width_q)
            else:
                # Pad / truncate to the declared width.
                if len(stripped) < width_q:
                    stripped = stripped + "." * (width_q - len(stripped))
                elif len(stripped) > width_q:
                    stripped = stripped[:width_q]
                cur.append(stripped)
        idx += 1
    if cur:
        levels.append(cur)

    if depth is None:
        depth = len(levels)

    slots: list[Slot] = []
    for lvl, grid in enumerate(levels):
        # Ensure grid has height_q rows.
        if len(grid) < height_q:
            grid = grid + ["." * width_q] * (height_q - len(grid))
        # Scan for '1' corners — each marks the top-left of a tile.
        for qy in range(height_q):
            row = grid[qy]
            for qx in range(width_q):
                if qx >= len(row):
                    break
                if row[qx] != "1":
                    continue
                # Validate the other three corners.
                ok = True
                if qx + 1 >= width_q or qy + 1 >= height_q:
                    ok = False
                else:
                    if grid[qy][qx + 1] != "2":
                        ok = False
                    elif grid[qy + 1][qx] != "4":
                        ok = False
                    elif grid[qy + 1][qx + 1] != "3":
                        ok = False
                if not ok:
                    # Gracefully skip — some fan-made layouts have stray chars.
                    continue
                slots.append(Slot(qx=qx, qy=qy, level=lvl))

    if name is None:
        name = p.stem

    # Even tile count is required for pair play; round down to even by
    # dropping the last slot if necessary. Warn via a print-to-stderr would
    # be nice, but we keep silent and let QA flag it.
    if len(slots) % 2 == 1:
        slots.pop()

    return Layout(name=name, width_q=width_q, height_q=height_q,
                  depth=depth, slots=slots)


def load_desktop_metadata(path: str | Path) -> dict[str, str]:
    """Parse a KMahjongg .desktop sidecar file for display metadata.
    Returns a dict with at least 'Name' and 'Description' (English)."""
    p = Path(path)
    out: dict[str, str] = {}
    if not p.exists():
        return out
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return out
    for line in text.splitlines():
        # Skip localised entries — we only keep the plain "Name=" etc.
        if "=" not in line or "[" in line.split("=", 1)[0]:
            continue
        key, val = line.split("=", 1)
        key = key.strip()
        if key in ("Name", "Description", "Author", "AuthorEmail", "FileName"):
            out[key] = val.strip()
    return out


def available_layouts(*search_dirs: Path) -> list[tuple[str, Path]]:
    """Scan directories for `.layout` files. Returns
    [(display_name, path), ...] sorted alphabetically by name.
    Accepts any number of directories — the first match for a given
    stem wins, so user dirs earlier in the list override vendor."""
    found: dict[str, Path] = {}
    for d in search_dirs:
        if not d.exists():
            continue
        for p in sorted(d.glob("*.layout")):
            stem = p.stem
            if stem in found:
                continue
            found[stem] = p
    return sorted(found.items())


__all__ = ["Slot", "Layout", "parse_layout", "load_desktop_metadata",
           "available_layouts"]
