"""Tile face definitions and the match rule.

Mahjong solitaire uses the standard 144-tile set. Every face has four
copies EXCEPT seasons and flowers, which have one copy each and match
any other tile in the SAME GROUP rather than by face.

We keep two parallel representations: Unicode mahjong block (U+1F000..)
and 2-character ASCII. The terminal's font determines which is usable
at runtime — `tests/tile_test.py` lets the user eyeball both. Most
modern terminals render the Unicode glyphs at double-width, which
matches the 2-cell-wide geometry we want for the board.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


# ---- face IDs ------------------------------------------------------------
# We keep face IDs as small ints so the game state is cheap to copy / snapshot
# for undo. 0..33 cover the 34 distinct face values.

# Dots / circles 1–9         IDs 0..8
# Bamboo 1–9                 IDs 9..17
# Characters 1–9             IDs 18..26
# Winds E/S/W/N              IDs 27..30
# Dragons Red/Green/White    IDs 31..33
# Seasons spring..winter     IDs 34..37   (match ANY in this group)
# Flowers plum..bamboo       IDs 38..41   (match ANY in this group)

FACE_COUNT = 42

_NAMES = [
    "Dot1", "Dot2", "Dot3", "Dot4", "Dot5", "Dot6", "Dot7", "Dot8", "Dot9",
    "Bam1", "Bam2", "Bam3", "Bam4", "Bam5", "Bam6", "Bam7", "Bam8", "Bam9",
    "Chr1", "Chr2", "Chr3", "Chr4", "Chr5", "Chr6", "Chr7", "Chr8", "Chr9",
    "East", "South", "West", "North",
    "RedDr", "GrnDr", "WhtDr",
    "Sp", "Su", "Au", "Wi",
    "Plum", "Orchid", "Chrys", "Bamboo",
]

# Unicode mahjong tiles — U+1F000..U+1F021 covers all 42 faces in a
# canonical KDE/Unicode order.
_UNICODE = [
    # winds
    "\U0001F000", "\U0001F001", "\U0001F002", "\U0001F003",  # E S W N
    # dragons
    "\U0001F004", "\U0001F005", "\U0001F006",  # Red Green White
    # characters (man) 1..9
    "\U0001F007", "\U0001F008", "\U0001F009", "\U0001F00A", "\U0001F00B",
    "\U0001F00C", "\U0001F00D", "\U0001F00E", "\U0001F00F",
    # bamboo 1..9
    "\U0001F010", "\U0001F011", "\U0001F012", "\U0001F013", "\U0001F014",
    "\U0001F015", "\U0001F016", "\U0001F017", "\U0001F018",
    # dots (circles) 1..9
    "\U0001F019", "\U0001F01A", "\U0001F01B", "\U0001F01C", "\U0001F01D",
    "\U0001F01E", "\U0001F01F", "\U0001F020", "\U0001F021",
]

# Our internal face ID order is dots/bamboo/chars/winds/drags/seasons/flowers.
# Unicode order above is winds/drags/chars/bamboo/dots. Plus seasons/flowers
# (U+1F022..U+1F029 — 4 seasons then 4 flowers).
_UNICODE_BY_ID: list[str] = [
    # Dots 1..9
    *["\U0001F019", "\U0001F01A", "\U0001F01B", "\U0001F01C", "\U0001F01D",
      "\U0001F01E", "\U0001F01F", "\U0001F020", "\U0001F021"],
    # Bamboo 1..9
    *["\U0001F010", "\U0001F011", "\U0001F012", "\U0001F013", "\U0001F014",
      "\U0001F015", "\U0001F016", "\U0001F017", "\U0001F018"],
    # Characters 1..9
    *["\U0001F007", "\U0001F008", "\U0001F009", "\U0001F00A", "\U0001F00B",
      "\U0001F00C", "\U0001F00D", "\U0001F00E", "\U0001F00F"],
    # Winds E S W N
    "\U0001F000", "\U0001F001", "\U0001F002", "\U0001F003",
    # Dragons Red Green White
    "\U0001F004", "\U0001F005", "\U0001F006",
    # Seasons spring..winter
    "\U0001F026", "\U0001F027", "\U0001F028", "\U0001F029",
    # Flowers plum/orchid/chrysanthemum/bamboo
    "\U0001F022", "\U0001F023", "\U0001F024", "\U0001F025",
]

# 2-char ASCII abbreviations. Column-aligned to 2 cells to match tile width.
_ASCII_BY_ID: list[str] = (
    [f"D{i}" for i in range(1, 10)]      # Dots
    + [f"B{i}" for i in range(1, 10)]    # Bamboo
    + [f"C{i}" for i in range(1, 10)]    # Characters
    + ["WE", "WS", "WW", "WN"]           # Winds
    + ["DR", "DG", "DW"]                 # Dragons
    + ["Sp", "Su", "Au", "Wi"]           # Seasons
    + ["Pl", "Or", "Ch", "Bm"]           # Flowers
)

# Face IDs grouped by colour for legibility on the board.
_COLOR_BY_ID: list[str] = (
    ["rgb(200,60,60)"] * 9           # Dots — red dots
    + ["rgb(70,170,80)"] * 9         # Bamboo — green
    + ["rgb(40,40,40)"] * 9          # Characters — black on light
    + ["rgb(80,140,220)"] * 4        # Winds — blue
    + ["rgb(200,60,60)",             # Red dragon
       "rgb(70,170,80)",             # Green dragon
       "rgb(230,230,230)"]           # White dragon
    + ["rgb(230,180,70)"] * 4        # Seasons — gold
    + ["rgb(220,130,200)"] * 4       # Flowers — pink
)


SEASON_GROUP = range(34, 38)
FLOWER_GROUP = range(38, 42)


@dataclass(frozen=True)
class Face:
    id: int
    name: str
    glyph_unicode: str
    glyph_ascii: str
    color: str

    @property
    def is_season(self) -> bool:
        return self.id in SEASON_GROUP

    @property
    def is_flower(self) -> bool:
        return self.id in FLOWER_GROUP


FACES: list[Face] = [
    Face(i, _NAMES[i], _UNICODE_BY_ID[i], _ASCII_BY_ID[i], _COLOR_BY_ID[i])
    for i in range(FACE_COUNT)
]


def match(a: int, b: int) -> bool:
    """True iff two face IDs can be matched and removed as a pair.

    Identical faces always match. Seasons match any other season;
    flowers match any other flower (even though the faces differ).
    A tile does not match itself (same physical tile).
    """
    if a == b:
        return True
    if a in SEASON_GROUP and b in SEASON_GROUP:
        return True
    if a in FLOWER_GROUP and b in FLOWER_GROUP:
        return True
    return False


def standard_deck() -> list[int]:
    """Returns a list of 144 face IDs — the standard solitaire deck.

    Dots/Bamboo/Chars/Winds/Dragons: 4 copies of each face.
    Seasons (4 faces, 1 copy each) + Flowers (4 faces, 1 copy each).
    Total: 27*4 + 4*4 + 3*4 + 4 + 4 = 108 + 16 + 12 + 8 = 144.
    """
    deck: list[int] = []
    # The 34 four-of-a-kind faces (suits + honors).
    for fid in range(34):
        deck.extend([fid] * 4)
    # Seasons and flowers — one of each.
    for fid in range(34, 42):
        deck.append(fid)
    assert len(deck) == 144, f"expected 144 tiles, got {len(deck)}"
    return deck


def assign_faces_to_positions(n_positions: int, rng) -> list[int]:
    """Return a shuffled deck sized to the number of board positions.

    Most KMahjongg layouts use exactly 144 slots; some non-standard ones
    use fewer (e.g. small test layouts). We truncate or extend a standard
    deck — extension repeats the suit faces (seasons/flowers are unique
    singletons and never duplicate). For >144 layouts we issue repeats of
    the 34 regular faces only, keeping them in sets of 4 so pairing still
    works.
    """
    deck = standard_deck()
    if n_positions == 144:
        rng.shuffle(deck)
        return deck
    if n_positions < 144:
        # Shave seasons/flowers first (they're singletons — odd to force
        # match with no partner). Then drop whole quads of ordinary faces.
        # n_positions must be even for pairing to be possible.
        if n_positions % 2 == 1:
            raise ValueError(f"layout has odd slot count {n_positions}")
        # Drop seasons/flowers from tail until either empty or even count.
        while len(deck) > n_positions and len(deck) > 108:
            deck.pop()
        # Drop full quads of the highest-numbered regular faces next.
        while len(deck) > n_positions:
            # Remove one full quad (4 tiles of the same face) from the tail.
            if len(deck) >= 4 and deck[-1] == deck[-4]:
                del deck[-4:]
            else:
                deck.pop()
        rng.shuffle(deck)
        return deck
    # n_positions > 144 — extend with extra regular-face quads.
    extra_needed = n_positions - 144
    if extra_needed % 4 != 0:
        # Round down to a multiple of 4 — pad with fewer tiles than slots
        # if we cant divide cleanly. Caller should warn.
        extra_needed -= extra_needed % 4
    fid = 0
    while extra_needed > 0:
        deck.extend([fid] * 4)
        fid = (fid + 1) % 34
        extra_needed -= 4
    rng.shuffle(deck)
    # If we padded down, there may still be positions without tiles —
    # but assign_faces_to_positions's contract is to return len==n_positions,
    # so we fallback to trimming.
    return deck[:n_positions]


__all__ = [
    "Face", "FACES", "FACE_COUNT",
    "SEASON_GROUP", "FLOWER_GROUP",
    "match", "standard_deck", "assign_faces_to_positions",
]
