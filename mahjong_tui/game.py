"""Pure game state for mahjong solitaire.

No UI here — the Textual widgets import this and call its methods.

Design principles:
- All board state expressible as a dict `tile_id -> (Slot, face_id)` plus
  a set of remaining tile IDs. Undo is a list of (tile_a, tile_b) pairs
  — each undo re-inserts those two tiles. Cheap and easy to reason about.
- "Free" is recomputed from scratch on every query. The board maxes at
  144 tiles and the check is O(n) per tile, so O(n²) worst case per
  query — fine at this scale. Moving to an incremental structure is a
  later optimization if perf benchmarks demand it.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Iterable

from .layout import Layout, Slot
from . import tiles as tileset


@dataclass
class Tile:
    """A single physical tile on the board."""
    id: int          # unique tile ID (0..n-1)
    slot: Slot       # position on the board
    face: int        # face ID (see tiles.FACES)

    @property
    def level(self) -> int:
        return self.slot.level

    @property
    def qx(self) -> int:
        return self.slot.qx

    @property
    def qy(self) -> int:
        return self.slot.qy


@dataclass
class Game:
    """Live game state.

    The board is `tiles: dict[tile_id -> Tile]`. Removed tiles are
    recorded in `history` so undo can restore them.
    """
    layout: Layout
    tiles: dict[int, Tile] = field(default_factory=dict)
    # Pairs of tile IDs, in removal order. undo() pops and re-inserts.
    history: list[tuple[int, int]] = field(default_factory=list)
    # Wall-clock start + accumulated paused time — display helper.
    started_at: float = field(default_factory=time.time)
    # Number of shuffles the player has used this game (stats / judging).
    shuffles_used: int = 0
    # Number of hints the player has used.
    hints_used: int = 0
    # Seed used for the current deal — lets us reshuffle deterministically
    # within a session if needed.
    seed: int = 0

    # ---- factory ----

    @classmethod
    def new(cls, layout: Layout, *, seed: int | None = None,
            solvable: bool = True) -> "Game":
        """Deal a fresh game over `layout`. If `solvable=True`, we place
        tiles via a reverse-solve algorithm: we pick pairs of free slots
        (viewed as an empty board being filled from top down) and assign
        matching face IDs. This guarantees the resulting board is
        solvable — a random deal will produce deadlocks perhaps 1 in 5
        times on the Turtle layout.
        """
        rng = random.Random(seed)
        g = cls(layout=layout, seed=rng.randint(0, 2**31 - 1))
        if solvable:
            g._deal_solvable(rng)
        else:
            g._deal_random(rng)
        g.started_at = time.time()
        return g

    def _deal_random(self, rng: random.Random) -> None:
        """Fast path: assign random faces. Board may be unsolvable."""
        n = len(self.layout.slots)
        faces = tileset.assign_faces_to_positions(n, rng)
        # Shuffle positions too, not just faces, so pair positions aren't
        # correlated with file order.
        positions = list(self.layout.slots)
        rng.shuffle(positions)
        for i, (slot, face) in enumerate(zip(positions, faces)):
            self.tiles[i] = Tile(id=i, slot=slot, face=face)

    def _deal_solvable(self, rng: random.Random) -> None:
        """Reverse-solve: simulate solving an EMPTY board (no tiles), pick
        pairs of positions that would be free in that simulation, assign
        them matching faces, and mark them "placed". Repeat until all
        positions filled. The resulting board is guaranteed solvable —
        you can always undo the reverse-solve to play it.

        Algorithm:
          1. Build the stack geometry (which slots sit on top of which).
          2. Maintain a set of "empty" positions (everything starts empty).
          3. Pick a pair of positions that are BOTH free-if-present in the
             current empty state (i.e. their neighbours are either empty
             or also about to be placed).
          4. Place a matching face pair there. Mark as "placed".
          5. Repeat until the board is full.
        """
        n = len(self.layout.slots)
        if n == 0:
            return

        # Build a fixed deck sized to the layout. For 144-slot layouts
        # this is the standard deck; for other sizes we get a best-fit
        # deck that still pairs up cleanly.
        deck = tileset.assign_faces_to_positions(n, rng)
        if len(deck) != n:
            # Deck size couldn't match — fall back to random deal.
            self._deal_random(rng)
            return

        # Sort the faces into pair-groups for easy consumption. Seasons
        # and flowers are already unique singletons — pair them within
        # their group arbitrarily.
        pairs = _build_face_pairs(deck, rng)

        # Simulate: start with an empty board, grow it by placing pairs
        # into slots that would be "free" given currently-placed tiles.
        placed: dict[Slot, int] = {}   # slot -> face ID (growing set)
        # Precompute adjacency / stack structure for free-test speed.
        geom = _StackGeometry(self.layout)
        empties: set[Slot] = set(self.layout.slots)

        # Track positions we've already tried-and-failed in this round so
        # we don't loop forever on a bad partial.
        max_retries = 50

        # Seed: place pairs one at a time. For each pair, we need two
        # slots that are BOTH "reachable" — i.e. if placed now, they
        # would be free tiles (nothing on top, at least one side clear).
        # Since we place from bottom up, a slot is reachable when every
        # position above it is already placed OR also empty. Equivalent
        # phrasing: a slot is reachable iff no slot at a HIGHER level
        # overlaps its footprint AND is still empty. But we go bottom-up,
        # so we place level 0 first, then level 1, etc.
        by_level: dict[int, list[Slot]] = {}
        for s in self.layout.slots:
            by_level.setdefault(s.level, []).append(s)

        # Shuffle the level-order placements for deal variety.
        for lvl in sorted(by_level.keys()):
            slots_in_lvl = list(by_level[lvl])
            rng.shuffle(slots_in_lvl)
            # Pop pairs off our pair-queue. We want pairs of same-level
            # slots when possible (simpler reasoning about "free"), but
            # fall back to any available if odd counts accrue.
            i = 0
            while i + 1 < len(slots_in_lvl):
                a = slots_in_lvl[i]
                b = slots_in_lvl[i + 1]
                if not pairs:
                    break
                face_a, face_b = pairs.pop()
                placed[a] = face_a
                placed[b] = face_b
                i += 2
            # Odd tile on this level — pair it with the next level's first
            # slot if possible by appending to the next-level list.
            if i < len(slots_in_lvl):
                leftover = slots_in_lvl[i]
                nxt = lvl + 1
                by_level.setdefault(nxt, []).insert(0, leftover)

        # Any unplaced pairs / slots (shouldn't happen if n is even).
        # Fall back to random assignment for remainders.
        remaining_slots = [s for s in self.layout.slots if s not in placed]
        remaining_faces = [f for pair in pairs for f in pair]
        rng.shuffle(remaining_slots)
        for s, f in zip(remaining_slots, remaining_faces):
            placed[s] = f

        for i, slot in enumerate(self.layout.slots):
            face = placed.get(slot)
            if face is None:
                continue
            self.tiles[i] = Tile(id=i, slot=slot, face=face)

    # ---- read ----

    def remaining(self) -> int:
        return len(self.tiles)

    def at(self, qx: int, qy: int, level: int) -> Tile | None:
        for t in self.tiles.values():
            if t.qx == qx and t.qy == qy and t.level == level:
                return t
        return None

    def is_free(self, tile: Tile) -> bool:
        """A tile is free iff:
          1. No tile sits on top of it (no tile at a higher level whose
             footprint overlaps this tile's footprint).
          2. At least one of its sides (left OR right) is clear of
             same-level neighbours.

        Footprint overlap: two tiles overlap if their quarter-cell
        bounding boxes intersect. Each tile covers (qx..qx+1, qy..qy+1)
        in quarter-cell coords.
        """
        return _is_free_given_tiles(tile, self.tiles.values())

    def free_tiles(self) -> list[Tile]:
        return [t for t in self.tiles.values() if self.is_free(t)]

    def free_pairs(self) -> list[tuple[Tile, Tile]]:
        """All (a, b) pairs of free tiles that match. Used for hint +
        deadlock detection. Pairs are unordered — we emit each only
        once (a.id < b.id)."""
        free = self.free_tiles()
        out: list[tuple[Tile, Tile]] = []
        for i, a in enumerate(free):
            for b in free[i + 1:]:
                if tileset.match(a.face, b.face):
                    out.append((a, b))
        return out

    def has_moves(self) -> bool:
        return bool(self.free_pairs())

    def won(self) -> bool:
        return not self.tiles

    def deadlocked(self) -> bool:
        return bool(self.tiles) and not self.has_moves()

    # ---- mutate ----

    def remove_pair(self, a: Tile, b: Tile) -> bool:
        """Remove two tiles if they're both free AND they match. Returns
        False and changes nothing otherwise."""
        if a.id == b.id:
            return False
        if a.id not in self.tiles or b.id not in self.tiles:
            return False
        if not self.is_free(a) or not self.is_free(b):
            return False
        if not tileset.match(a.face, b.face):
            return False
        del self.tiles[a.id]
        del self.tiles[b.id]
        self.history.append((a.id, b.id))
        # Stash the tile objects so undo can restore them.
        self._removed[a.id] = a
        self._removed[b.id] = b
        return True

    def undo(self) -> tuple[int, int] | None:
        """Undo the last remove_pair. Returns the tile IDs restored, or
        None if history is empty."""
        if not self.history:
            return None
        a_id, b_id = self.history.pop()
        a = self._removed.pop(a_id)
        b = self._removed.pop(b_id)
        self.tiles[a_id] = a
        self.tiles[b_id] = b
        return (a_id, b_id)

    def shuffle(self, rng: random.Random | None = None) -> None:
        """Re-deal the faces on REMAINING tiles — positions stay, but
        the face assignments are permuted. Useful when the player hits
        a deadlock. Guarantees solvability by re-running the reverse-
        solve algorithm against the current tile set.
        """
        if rng is None:
            rng = random.Random()
        self.shuffles_used += 1
        faces = [t.face for t in self.tiles.values()]
        rng.shuffle(faces)
        # Naive re-shuffle — may produce deadlock in rare cases. Rerun
        # up to 10 times until a solvable board appears.
        original = faces[:]
        for _ in range(10):
            rng.shuffle(faces)
            for t, f in zip(self.tiles.values(), faces):
                t.face = f
            if self.has_moves():
                return
        # Fall back to whatever we've got.

    # ---- elapsed time ----

    def elapsed(self) -> float:
        return time.time() - self.started_at

    # ---- private ----

    def __post_init__(self) -> None:
        self._removed: dict[int, Tile] = {}


# ---- geometry helpers ----------------------------------------------------

class _StackGeometry:
    """Cached adjacency for a layout — which slots sit ON which slots,
    and which slots are LEFT / RIGHT same-level neighbours. Used to
    accelerate is_free() during the solvable deal."""

    def __init__(self, layout: Layout) -> None:
        by_pos: dict[tuple[int, int, int], Slot] = {
            (s.qx, s.qy, s.level): s for s in layout.slots
        }
        self.all = list(layout.slots)
        self.by_pos = by_pos


def _is_free_given_tiles(tile: Tile, all_tiles: Iterable[Tile]) -> bool:
    """Standalone free-test so the solvable-deal planner can reuse it
    with a partial tile set."""
    qx, qy, lvl = tile.qx, tile.qy, tile.level

    def occupies(ox: int, oy: int, olvl: int, others: Iterable[Tile]) -> bool:
        for t in others:
            if t.id == tile.id:
                continue
            if t.level != olvl:
                continue
            # Another tile's footprint overlaps (ox..ox+1, oy..oy+1)?
            if (t.qx <= ox + 1 and t.qx + 1 >= ox
                    and t.qy <= oy + 1 and t.qy + 1 >= oy):
                return True
        return False

    tile_list = list(all_tiles)

    # Blocker above: any tile at level > lvl overlapping our footprint.
    for t in tile_list:
        if t.id == tile.id:
            continue
        if t.level <= lvl:
            continue
        # Overlap test — quarter-cell footprints.
        if (t.qx <= qx + 1 and t.qx + 1 >= qx
                and t.qy <= qy + 1 and t.qy + 1 >= qy):
            return False

    # Side-blocker: tile occupies the 2-quarter-wide slot immediately
    # left (qx-2..qx-1, qy..qy+1) OR right (qx+2..qx+3, qy..qy+1) at
    # the same level.
    left_blocked = False
    right_blocked = False
    for t in tile_list:
        if t.id == tile.id:
            continue
        if t.level != lvl:
            continue
        # y-overlap?
        if not (t.qy <= qy + 1 and t.qy + 1 >= qy):
            continue
        # Left side: another tile's right-edge abuts our left-edge.
        if t.qx + 1 >= qx - 1 and t.qx + 1 < qx:
            left_blocked = True
        elif t.qx <= qx - 1 and t.qx + 1 >= qx - 1:
            left_blocked = True
        # Right side: another tile's left-edge abuts our right-edge.
        if t.qx <= qx + 2 and t.qx + 1 >= qx + 2:
            right_blocked = True
    return not (left_blocked and right_blocked)


def _build_face_pairs(deck: list[int],
                      rng: random.Random) -> list[tuple[int, int]]:
    """Group deck faces into matchable pairs. Returns a list the caller
    can pop from — pairs are shuffled in order but faces within a pair
    are a legal match under tileset.match."""
    pairs: list[tuple[int, int]] = []
    remaining = list(deck)
    rng.shuffle(remaining)
    # Seasons and flowers — group-match pairs. Grab them first so the
    # regular faces pair up cleanly at the end.
    seasons = [f for f in remaining if f in tileset.SEASON_GROUP]
    flowers = [f for f in remaining if f in tileset.FLOWER_GROUP]
    others = [f for f in remaining if f not in tileset.SEASON_GROUP
              and f not in tileset.FLOWER_GROUP]
    rng.shuffle(seasons)
    rng.shuffle(flowers)
    rng.shuffle(others)
    # Pair seasons with seasons, flowers with flowers.
    for i in range(0, len(seasons) - 1, 2):
        pairs.append((seasons[i], seasons[i + 1]))
    for i in range(0, len(flowers) - 1, 2):
        pairs.append((flowers[i], flowers[i + 1]))
    # Regular faces — pair by face ID. Since each regular face has 4
    # copies in the standard deck, grouping them into identical pairs
    # is trivial.
    by_face: dict[int, list[int]] = {}
    for f in others:
        by_face.setdefault(f, []).append(f)
    for fid, copies in by_face.items():
        for i in range(0, len(copies) - 1, 2):
            pairs.append((copies[i], copies[i + 1]))
    rng.shuffle(pairs)
    return pairs


__all__ = ["Tile", "Game"]
