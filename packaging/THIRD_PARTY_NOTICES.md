# Third-party notices

repopull itself is licensed under the GNU Affero General Public License,
version 3 only. The full text is in [LICENSE](../LICENSE).

The AppImage is a bundle. It contains the components below, each under its own
licence. repopull does not modify them.

## Python 3.13.17

- Licence: Python Software Foundation License 2.0
- Licence text: <https://docs.python.org/3/license.html>
- Source: <https://www.python.org/downloads/source/>

## PySide6 6.12.0 and Qt 6.12

- Licence: GNU Lesser General Public License, version 3 (LGPL-3.0-only), with
  the alternative GPL-2.0/GPL-3.0 options offered by the Qt project
- LGPL text: [licenses/LGPL-3.0.txt](licenses/LGPL-3.0.txt)
- PySide6 source: <https://code.qt.io/cgit/pyside/pyside-setup.git/>
- Qt source: <https://download.qt.io/official_releases/qt/6.12/>
- Licence information: <https://www.qt.io/licensing/open-source-lgpl-obligations>

Qt is bundled as unmodified shared libraries. The AppImage's build inputs,
versions and scripts are public in this repository, so the image can be
inspected and Qt can be replaced or relinked. The complete corresponding
source for the LGPL-covered components is available from the Qt and PySide6
locations above.

## certifi 2026.10.18

- Licence: Mozilla Public License 2.0
- Licence text: <https://www.mozilla.org/en-US/MPL/2.0/>
- Source: <https://github.com/certifi/python-certifi>

## OpenSSL 3.5.9

- Licence: Apache License 2.0
- Licence text: <https://www.openssl.org/source/license.html>
- Source: <https://www.openssl.org/source/>

## Base image libraries

The Python and Qt runtimes come from the pinned `python-appimage` base image
(<https://github.com/niess/python-appimage>). Libraries such as `libcrypto`,
`libssl`, `readline`, `ncurses`, `liblzma` and `zlib` retain the licences of
their respective projects. Their copyright notices are part of the base image
and are not removed by the trim step.

## AppGlider

No code from AppGlider is included. The packaging uses the same public tools
(`python-appimage`, `appimagetool`) and an independently written trim step.
