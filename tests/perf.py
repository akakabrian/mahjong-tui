"""Micro-benchmark for the hot paths that affect perceived latency.

    .venv/bin/python -m tests.perf
"""

from __future__ import annotations

import asyncio
import statistics
import time

from mahjong_tui.app import MahjongApp
from mahjong_tui import render as R


def timed(label: str, fn, iterations: int = 30) -> float:
    samples = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append((time.perf_counter() - t0) * 1000)  # ms
    samples.sort()
    trimmed = samples[: max(1, len(samples) - 2)]
    mean = statistics.mean(trimmed)
    p95 = samples[min(int(len(samples) * 0.95), len(samples) - 1)]
    print(f"  {label:50s} mean={mean:7.2f}ms  p95={p95:7.2f}ms  (n={iterations})")
    return mean


async def main() -> None:
    app = MahjongApp(seed=0xBEEF)
    async with app.run_test(size=(200, 60)) as pilot:
        await pilot.pause()
        game = app.game
        board = app.board
        out = board._render_out
        assert out is not None
        print(f"\nbaseline — layout={game.layout.name}  tiles={game.remaining}")
        print(f"grid     — {out.width}x{out.height}  viewport=(200,60)")
        print()

        # Render all rows (full virtual board).
        def render_all_rows():
            for y in range(out.height):
                board.render_line(y)
        timed("render_line x full grid", render_all_rows)

        # Viewport-sized render (60 rows).
        def render_viewport():
            for y in range(60):
                board.render_line(y)
        timed("render_line x 60 rows (viewport)", render_viewport)

        # Full game-state rebuild — what _rebuild() does on every move.
        timed("render_board() (full rebuild)", lambda: R.render_board(game))

        # Free-tile query (used by every render + every mouse click).
        timed("game.free_tiles() (144 tiles)", game.free_tiles)

        # Free-pair enumeration — used for hint + deadlock detection.
        timed("game.free_pairs()", game.free_pairs, iterations=20)

        # Is-free for a single tile — inner loop of free_tiles.
        sample_tile = next(iter(game.tiles.values()))
        timed("game.is_free(one tile)", lambda: game.is_free(sample_tile),
              iterations=200)

        # New game — includes solvable deal.
        from mahjong_tui.game import Game
        timed("Game.new (solvable deal)", lambda: Game.new(game.layout, seed=1),
              iterations=10)


if __name__ == "__main__":
    asyncio.run(main())
