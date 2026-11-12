# Packaging as an AppImage

`make appimage` builds `dist/repopull-0.6.0-x86_64.AppImage`: a single file with
a bundled Python 3.13, PySide6 and `repopull`. It follows the same approach as
AppGlider — `python-appimage` stages the AppDir, then a pinned `appimagetool`
packs it. The staged AppDir is trimmed to the Qt modules repopull imports, so
the download is about 46 MB instead of 95 MB.

## Requirements

- Linux x86_64.
- Python 3.11+ to run the build.
- Network access (downloads the pinned base image, appimagetool, runtime and
  PySide6).
- `python3 -m venv` and `pip`; the Makefile creates `build/packaging-env`.
- `readelf` from binutils; the trim follows ELF dependencies.
- Host `git` at runtime. The AppImage bundles Python and Qt, not git.

## Build

```bash
make appimage
```

The script downloads pinned inputs into `build/downloads/`, builds the wheel,
stages the AppDir, replaces `AppRun`, trims the AppDir, adds the licence
notices, packs the image, and runs two smoke tests (GUI offscreen and
`--cli version`). Output:

```
dist/repopull-0.6.0-x86_64.AppImage
dist/SHA256SUMS.txt
```

## Trimming the AppDir

`python-appimage` installs the complete PySide6-Essentials wheel, which is built
for every Qt application. `packaging/trim_appdir.py` removes the parts repopull
cannot reach:

- QML, Quick, Designer and their plugins, tools and QML assets;
- the bundled `pip`, type stubs, headers, build glue and documentation;
- Python's Tk, IDLE, turtle demos, SQLite and the matching shared libraries;
- Qt translations other than the `qtbase_*` and `qt_*` catalogues.

It then keeps only the `QtCore`, `QtGui` and `QtWidgets` Python bindings and
follows their ELF `NEEDED` entries (plus those of the retained plugins) to keep
exactly the Qt shared libraries they load. If a retained file needs a Qt library
that is missing, the build stops rather than producing an image that only starts
on the build machine. Platform plugins for X11, Wayland, offscreen and minimal
are kept; the build also refuses any image above 60 MB.

`tests/test_packaging.py` ties the keep-list to the Qt modules imported under
`src/`, so adding a new Qt module to the app fails the suite until the trim is
updated. The trim is written for repopull; it does not copy AppGlider's GPL
code.

## Run

```bash
./dist/repopull-0.6.0-x86_64.AppImage                  # GUI
./dist/repopull-0.6.0-x86_64.AppImage --cli status
./dist/repopull-0.6.0-x86_64.AppImage --cli sync --only 'craft-*'
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

## Updates and dependency checks

- **Before each release:** run `make audit`. It runs `pip-audit` over both
  `packaging/runtime-requirements.txt` and `packaging/build-requirements.txt`.
  CI runs the same two audits on every push and pull request.
- **Runtime packages:** PySide6 and certifi are pinned exactly. Update the pin,
  rebuild the image, and smoke-test it with `--smoke-test`, the GUI, and
  `make soak-qt`; the application must still import, render, and close cleanly.
- **Build inputs:** update the URL and SHA-256 together in
  `packaging/downloads.json`, remove the cached file under `build/downloads/`,
  and rebuild. A checksum mismatch stops the build by design.
- **Python:** the package supports 3.11+, CI tests 3.11 and 3.13, and the image
  bundles the pinned 3.13 runtime. Change the CI matrix, the base-image pin, and
  the `requires-python` floor together; do not raise the floor without a release
  note.
- **PySide6 range:** `pyproject.toml` allows `>=6.8,<7` for a source checkout;
  the AppImage uses the exact pin. Test the oldest supported minor before
  widening the range.
- **CI inputs:** the workflow pins `actions/checkout` and `actions/setup-python`
  to a commit SHA with the release tag in a comment, and installs `mypy` and
  `pip-audit` from `packaging/ci-requirements.txt` at exact versions. Dependabot
  proposes updates for the actions. CI is not the build: the image is made
  locally from `downloads.json` and the pinned requirements, so a compromise in
  a CI runner cannot change what a user downloads.
- **Rust:** there is no Rust wrapper and no build-time Rust dependency. The
  language decision stays gated on a measured need for a small native helper;
  see [hardening-backlog.md](hardening-backlog.md).

## Layout

| Path | Purpose |
|---|---|
| `packaging/AppRun` | Writable home, Qt paths, GUI/CLI dispatch |
| `packaging/repopull.desktop` | Menu entry |
| `packaging/repopull.png` | 256×256 AppImage/desktop icon |
| `packaging/make_icon.py` | Regenerates the icon family; see branding.md |
| `packaging/build_appimage.py` | Build orchestration |
| `packaging/trim_appdir.py` | AppDir trim policy and ELF dependency walk |
| `packaging/THIRD_PARTY_NOTICES.md` | Bundled-component notices copied into the image |
| `packaging/licenses/LGPL-3.0.txt` | LGPL text for PySide6/Qt |
| `packaging/downloads.json` | Pinned build inputs |
| `packaging/runtime-requirements.txt` | Bundled Python packages |
| `packaging/build-requirements.txt` | Build-time Python package |
| `packaging/ci-requirements.txt` | Test and audit tools CI installs |

The icon family and its optical cuts are documented in
[branding.md](branding.md); the build stages every hicolor size from the same
assets.

## Licensing

AppGlider is GPL-3.0-or-later. This packaging is a separate implementation that
uses the same public tools (`python-appimage`, `appimagetool`) and an
independently written trim step; it does not copy AppGlider's code.

The image carries `usr/share/doc/repopull/THIRD_PARTY_NOTICES.md`, the
LGPL-3.0 text and repopull's own licence. Qt is bundled unmodified as shared
libraries, and the build inputs and scripts are public, so the image can be
inspected or relinked.
For the full documentation index, see [README.md](../README.md#documentation-index).
