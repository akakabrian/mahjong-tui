# DOGFOOD — mahjong-tui

_Session: 2026-04-23T10:29:01, driver: pilot, duration: 8.0 min_

**PASS** — ran for 1.5m, captured 0 snap(s), 0 milestone(s), 0 blocker(s), 1 major(s).

## Summary

Ran a rule-based exploratory session via `pilot` driver. Found **1 major(s)**, 2 UX note(s). Game state never changed during the session. 2 coverage note(s) — see Coverage section. 1 driver warning(s) captured — see below.

## Findings

### Blockers

_None._

### Majors
- **[M1] state appears frozen during golden-path play**
  - Collected 10 state samples; only 1 unique. Game may not be receiving keys.
  - Repro: start game → press right/up/left/down repeatedly

### Minors

_None._

### Nits

_None._

### UX (feel-better-ifs)
- **[U1] state() feedback is coarse**
  - Only 1 unique states over 14 samples (ratio 0.07). The driver interface works but reveals little per tick.
- **[U2] reached win state 14 time(s)**
  - Level advancement appears to work end-to-end.

## Coverage

- Driver backend: `pilot`
- Keys pressed: 160 (unique: 12)
- State samples: 14 (unique: 1)
- Score samples: 0
- Milestones captured: 0
- Phase durations (s): A=17.8, B=22.5, C=48.0
- Snapshots: `/tmp/AI/projects-20260423-102623/tui-dogfood/reports/snaps/mahjong-tui-20260423-102732`

Unique keys exercised: ?, R, down, enter, escape, left, n, p, r, right, space, up

### Coverage notes

- **[CN1] Phase A exited early due to saturation**
  - State hash unchanged for 10 consecutive samples after 9 golden-path loop(s); no further learning expected.
- **[CN2] Phase B exited early due to saturation**
  - State hash unchanged for 10 consecutive samples during the stress probe; remaining keys skipped.

## Driver warnings

Captured 1 non-fatal driver warning(s) during the run:

```
PilotDriver teardown: AttributeError: 'NoneType' object has no attribute 'color'
_update(simplify=simplify)
           ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/_compositor.py", line 1149, in render_full_update
    chops = self._render_chops(crop, lambda y: True)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/_compositor.py", line 1222, in _render_chops
    for region, clip, strips in renders:
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/_compositor.py", line 1068, in _get_renders
    widget.render_lines(
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/widget.py", line 4285, in render_lines
    strips = self._styles_cache.render_widget(self, crop)
             ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/_styles_cache.py", line 115, in render_widget
    strips = self.render(
             ^^^^^^^^^^^^
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/_styles_cache.py", line 236, in render
    strip = strip.apply_filter(filter, background)
            ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/strip.py", line 466, in apply_filter
    filter.apply(self._segments, background), self._cell_length
    ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/filter.py", line 93, in apply
    _Segment(text, _monochrome_style(style), None)
                   ^^^^^^^^^^^^^^^^^^^^^^^^
  File "/home/brian/AI/projects/tui-dogfood/.venv/lib/python3.12/site-packages/textual/filter.py", line 62, in monochrome_style
    style_color = style.color
                  ^^^^^^^^^^^
AttributeError: 'NoneType' object has no attribute 'color'
```
