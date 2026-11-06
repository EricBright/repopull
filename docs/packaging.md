# Packaging as an AppImage

`make appimage` builds `dist/repopull-0.4.0-x86_64.AppImage`: a single file with
a bundled Python 3.13, PySide6 and `repopull`. It follows the same approach as
AppGlider — `python-appimage` stages the AppDir, then a pinned `appimagetool`
packs it.

## Requirements

- Linux x86_64.
- Python 3.11+ to run the build.
- Network access (downloads the pinned base image, appimagetool, runtime and
  PySide6).
- `python3 -m venv` and `pip`; the Makefile creates `build/packaging-env`.
- Host `git` at runtime. The AppImage bundles Python and Qt, not git.

## Build

```bash
make appimage
```

The script downloads pinned inputs into `build/downloads/`, builds the wheel,
stages the AppDir, replaces `AppRun`, packs the image, and runs two smoke tests
(GUI offscreen and `--cli version`). Output:

```
dist/repopull-0.4.0-x86_64.AppImage
dist/SHA256SUMS.txt
```

## Run

```bash
./dist/repopull-0.4.0-x86_64.AppImage                  # GUI
./dist/repopull-0.4.0-x86_64.AppImage --cli status
./dist/repopull-0.4.0-x86_64.AppImage --cli sync --only 'craft-*'
```

If FUSE is unavailable, add `--appimage-extract-and-run`.

Qt chooses Wayland or X11 automatically. Both platform plugins are bundled, so
the image runs natively on either; force one with `QT_QPA_PLATFORM=wayland` or
`QT_QPA_PLATFORM=xcb`.

## Where config and logs live

The image is read-only, so `AppRun` uses a writable folder:

```
${XDG_CONFIG_HOME:-$HOME/.config}/repopull/
  config.toml
  logs/
```

On first run it copies a **template with no watched folder**. Open **Settings**
in the GUI and choose one, or edit `config.toml` / pass `--root`. The image never
ships the developer's path. Set `REPOPULL_HOME` to use another config location.

The Settings page shows the resolved logs path; it comes from
`${XDG_CONFIG_HOME:-$HOME/.config}` at runtime, so it is correct on any machine.

## Versioning

The image name comes from `pyproject.toml`. `make bump` increments the version
(patch by default; `PART=minor` or `PART=major` for a larger step), and
`make release` runs the checks, bumps the patch, and rebuilds. There is no
separate build counter; the semantic version is the build identity. Record
user-visible changes in [CHANGELOG.md](../CHANGELOG.md).

## What is pinned

`packaging/downloads.json` pins the `python-appimage` base, `appimagetool` 1.9.1
and the type-2 runtime by URL and SHA-256. `packaging/runtime-requirements.txt`
pins PySide6 and certifi. Change them deliberately.

## Layout

| Path | Purpose |
|---|---|
| `packaging/AppRun` | Writable home, Qt paths, GUI/CLI dispatch |
| `packaging/repopull.desktop` | Menu entry |
| `packaging/repopull.png` | 256×256 AppImage/desktop icon |
| `packaging/make_icon.py` | Regenerates the icon family; see branding.md |
| `packaging/build_appimage.py` | Build orchestration |
| `packaging/downloads.json` | Pinned build inputs |
| `packaging/runtime-requirements.txt` | Bundled Python packages |
| `packaging/build-requirements.txt` | Build-time Python package |

The icon family and its optical cuts are documented in
[branding.md](branding.md); the build stages every hicolor size from the same
assets.

## Licensing

AppGlider is GPL-3.0-or-later. This packaging is a separate implementation that
uses the same public tools (`python-appimage`, `appimagetool`); it does not copy
AppGlider's code.
For the full documentation index, see [README.md](../README.md#documentation-index).
