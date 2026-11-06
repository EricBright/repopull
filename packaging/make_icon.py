"""Generate repopull's icon family from the B1t Convergence mark."""

from __future__ import annotations

import math
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "src" / "repopull" / "gui" / "assets"
PACKAGING = Path(__file__).resolve().parent

BLUE = "#6ea8ff"
VIOLET = "#a78bfa"
SMALL_BLUE = "#9cc8ff"
SMALL_VIOLET = "#c4b5ff"
SMALL_SIZES = (16, 22, 24)
DISPLAY_SIZES = (32, 48, 64, 128, 256, 512)
SYMBOLIC_SIZES = (16, 22, 24, 32)


def _fmt(point: tuple[float, float]) -> str:
    return f"{point[0]:.2f} {point[1]:.2f}"


def _taper(
    base: tuple[float, float],
    tip: tuple[float, float],
    base_half: float,
    tip_half: float,
    color: str,
) -> str:
    bx, by = base
    tx, ty = tip
    dx, dy = tx - bx, ty - by
    length = math.hypot(dx, dy)
    ux, uy = dx / length, dy / length
    px, py = -uy, ux

    bl = (bx + px * base_half, by + py * base_half)
    br = (bx - px * base_half, by - py * base_half)
    tl = (tx + px * tip_half, ty + py * tip_half)
    tr = (tx - px * tip_half, ty - py * tip_half)
    control = (tx + ux * tip_half * 1.8, ty + uy * tip_half * 1.8)

    return (
        f'<path d="M {_fmt(bl)} L {_fmt(tl)} Q {_fmt(control)} {_fmt(tr)} '
        f'L {_fmt(br)} Z" fill="{color}"/>'
    )


def _display_mark() -> str:
    branches = "".join(
        (
            _taper((256, 236), (164, 156), 15, 7, VIOLET),
            _taper((256, 236), (256, 128), 15, 8, VIOLET),
            _taper((256, 236), (348, 156), 15, 7, VIOLET),
        )
    )
    arrow = (
        '<path d="M 241 232 L 271 232 L 271 310 L 314 310 '
        f'L 256 382 L 198 310 L 241 310 Z" fill="{BLUE}"/>'
    )
    tray = (
        '<path d="M 152 352 L 152 382 Q 152 404 174 404 '
        'L 338 404 Q 360 404 360 382 L 360 352" '
        f'fill="none" stroke="{VIOLET}" stroke-width="22" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    return branches + arrow + tray


def _display_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#1a2230"/>
      <stop offset="1" stop-color="#0d1117"/>
    </linearGradient>
  </defs>
  <rect x="28" y="28" width="456" height="456" rx="108" ry="108"
        fill="url(#bg)" stroke="#2a3345" stroke-width="2"/>
  {_display_mark()}
</svg>
"""


def _small_mark() -> str:
    branches = "".join(
        (
            _taper((256, 236), (164, 156), 18, 10, SMALL_VIOLET),
            _taper((256, 236), (256, 128), 18, 11, SMALL_VIOLET),
            _taper((256, 236), (348, 156), 18, 10, SMALL_VIOLET),
        )
    )
    arrow = (
        '<path d="M 238 232 L 274 232 L 274 310 L 314 310 '
        f'L 256 386 L 198 310 L 238 310 Z" fill="{SMALL_BLUE}"/>'
    )
    tray = (
        '<path d="M 152 352 L 152 382 Q 152 404 174 404 '
        'L 338 404 Q 360 404 360 382 L 360 352" '
        f'fill="none" stroke="{SMALL_VIOLET}" stroke-width="28" '
        'stroke-linecap="round" stroke-linejoin="round"/>'
    )
    return branches + arrow + tray


def _small_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="512" height="512" viewBox="0 0 512 512">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#1a2230"/>
      <stop offset="1" stop-color="#0d1117"/>
    </linearGradient>
  </defs>
  <rect x="28" y="28" width="456" height="456" rx="108" ry="108"
        fill="url(#bg)" stroke="#2a3345" stroke-width="2"/>
  <g transform="translate(256 258) scale(1.18) translate(-256 -266)">
    {_small_mark()}
  </g>
</svg>
"""


def _mark_svg() -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"
     viewBox="140 116 232 300">
  {_display_mark()}
</svg>
"""

def _symbolic_svg() -> str:
    mark = _display_mark().replace(VIOLET, "#ffffff").replace(BLUE, "#ffffff")
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"
     viewBox="140 116 232 300">
  {mark}
</svg>
"""


def render(svg: str, size: int) -> QImage:
    image = QImage(size, size, QImage.Format.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(painter)
    painter.end()
    return image


def _save(image: QImage, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not image.save(str(path)):
        raise SystemExit(f"could not write {path}")
    print(f"wrote {path}")


def main() -> None:
    app = QGuiApplication(["repopull-icons"])
    display = _display_svg()
    small = _small_svg()

    _save(render(display, 256), PACKAGING / "repopull.png")
    for size in SMALL_SIZES:
        _save(render(small, size), ASSETS / f"repopull-{size}.png")
    for size in DISPLAY_SIZES:
        _save(render(display, size), ASSETS / f"repopull-{size}.png")
    _save(render(_mark_svg(), 64), ASSETS / "repopull-mark.png")
    symbolic = _symbolic_svg()
    for size in SYMBOLIC_SIZES:
        _save(
            render(symbolic, size),
            ASSETS / f"repopull-symbolic-{size}.png",
        )
    app.quit()


if __name__ == "__main__":
    main()
