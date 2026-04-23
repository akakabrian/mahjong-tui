"""Eyeball test: dump every tile face as Unicode + ASCII side-by-side.

If your terminal renders the Unicode mahjong block (U+1F000..U+1F029)
as tofu or with wrong width, you want to play with --ascii. This
script lets you see both representations at once.

    .venv/bin/python -m tests.tile_test
"""

from __future__ import annotations

from mahjong_tui import tiles as tileset


def main() -> None:
    print(f"{'id':>3}  {'name':<8}  uni  ascii  color")
    print("-" * 50)
    for face in tileset.FACES:
        print(
            f"{face.id:>3}  {face.name:<8}  "
            f"{face.glyph_unicode}   "
            f"{face.glyph_ascii:<5}  {face.color}"
        )
    print()
    print("If the 'uni' column shows boxes/tofu or wrong width, run with --ascii.")
    print("Otherwise Unicode is preferred — 2-cell wide, matches tile footprint.")


if __name__ == "__main__":
    main()
