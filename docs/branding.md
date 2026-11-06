# Branding and icons

The mark is **Convergence**: three tapered violet branches converge into a blue
down arrow that lands in a violet U-tray, on a dark squircle. It is the only
logo; there is no branchless caption.

## Cuts

| Sizes | Cut | Notes |
|---|---|---|
| 16 / 22 / 24 px | small B1t | 1.18× larger, thicker branches and tray, lighter tints. Branches are kept; 16 px is soft. |
| 32–512 px | standard B1t | The full mark at normal weight. |
| 28 px sidebar | full B1t, no tile | Mark only, beside the wordmark. |

Do not replace the small sizes with a branchless glyph. The small cut is an
optical size, not a second brand; the reason and trade-off are recorded in
[design decision 21](design-decisions.md#21-branches-at-every-icon-size).

## Where it is used

- **AppImage / `.desktop`:** `packaging/repopull.png` (256 px).
- **Window and taskbar:** `build_app_icon()` in `src/repopull/gui/app.py`, a
  multi-size `QIcon` loaded from `src/repopull/gui/assets/repopull-*.png`; the
  desktop file name is `repopull`.
- **Sidebar:** `repopull-mark.png` at 28 px, next to the wordmark.
- **Tray:** `repopull-symbolic-{16,22,24,32}.png`, a white/alpha mask used with
  `QIcon.setIsMask(True)` so KDE/Bazzite can recolour it for the panel theme.
- **AppImage icon theme:** `packaging/build_appimage.py` stages 16/22/24/32/48/64/128/256/512
  into `usr/share/icons/hicolor/...` so the launcher can choose the right cut.

## Regenerate

```bash
python3 packaging/make_icon.py
make test
```

`make_icon.py` writes `packaging/repopull.png`, the size-specific assets,
`repopull-mark.png`, and the symbolic tray assets. Do not hand-edit the PNGs; the geometry and colours live in
that script. Run `make appimage` only when the change should ship.

## Files

| Path | Purpose |
|---|---|
| `packaging/make_icon.py` | Generates the whole family from the B1t geometry |
| `packaging/repopull.png` | 256 px AppImage/desktop icon |
| `src/repopull/gui/assets/repopull-{16..512}.png` | Window/taskbar `QIcon` sizes |
| `src/repopull/gui/assets/repopull-mark.png` | Tile-less 64 px sidebar source |
| `src/repopull/gui/assets/repopull-symbolic-{16,22,24,32}.png` | Symbolic tray mask |
| `src/repopull/gui/app.py` | Builds the `QIcon` and sets the desktop file name |
| `src/repopull/gui/window.py` | Places the 28 px sidebar mark |

## Constraints

- One family: the small cut and the display cut share the same geometry and hue.
- No text in the icon, no Git/GitHub marks, and no branchless caption.
- Keep the icon theme sizes sourced from the same assets; do not add a separate
  small-size logo.

For packaging details see [packaging.md](packaging.md); for placement see
[gui.md](gui.md).

For the full documentation index, see
[README.md](../README.md#documentation-index).
