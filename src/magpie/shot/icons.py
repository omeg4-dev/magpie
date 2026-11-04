"""The toolbar's pictures, drawn rather than loaded.

Each icon is a few strokes in a 24 x 24 box, painted with the widget's own CSS
colour — so a hovered, selected or disabled button recolours its icon for free,
and when the wallpaper changes the icons follow it along with everything else.
There are no icon files to be missing, no icon theme to disagree with, and no
raster to go soft on a fractional-scale monitor.
"""

from __future__ import annotations

import math

import cairo
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk  # noqa: E402

__all__ = ["Icon", "draw", "NAMES"]


def _arrow(c: cairo.Context) -> None:
    c.move_to(5, 19); c.line_to(18.5, 5.5)
    c.move_to(10.5, 5); c.line_to(19, 5); c.line_to(19, 13.5)
    c.stroke()


def _line(c: cairo.Context) -> None:
    c.move_to(5, 19); c.line_to(19, 5); c.stroke()


def _rect(c: cairo.Context) -> None:
    _round_rect(c, 4, 6.5, 16, 11, 3); c.stroke()


def _ellipse(c: cairo.Context) -> None:
    c.save(); c.translate(12, 12); c.scale(8.5, 6.5)
    c.arc(0, 0, 1, 0, 2 * math.pi); c.restore(); c.stroke()


def _pen(c: cairo.Context) -> None:
    c.move_to(4, 17)
    c.curve_to(6, 6, 9, 6, 10.5, 12)
    c.curve_to(12, 18, 14.5, 18, 16, 11)
    c.curve_to(17, 7, 18.5, 7, 20, 9)
    c.stroke()


def _highlighter(c: cairo.Context) -> None:
    c.move_to(8, 15); c.line_to(15.5, 7.5); c.line_to(19, 11); c.line_to(11.5, 18.5); c.close_path()
    c.stroke()
    c.move_to(8, 15); c.line_to(5.5, 19.5); c.line_to(11.5, 18.5); c.stroke()
    c.set_line_width(2.6); c.move_to(13, 20.5); c.line_to(20, 20.5); c.stroke()


def _text(c: cairo.Context) -> None:
    c.move_to(5.5, 6.5); c.line_to(18.5, 6.5)
    c.move_to(12, 6.5); c.line_to(12, 18.5)
    c.move_to(9.5, 18.5); c.line_to(14.5, 18.5)
    c.stroke()


def _badge(c: cairo.Context) -> None:
    c.arc(12, 12, 8.5, 0, 2 * math.pi); c.stroke()
    c.move_to(10, 9.5); c.line_to(12.3, 8); c.line_to(12.3, 16)
    c.move_to(10.2, 16); c.line_to(14.4, 16)
    c.stroke()


def _blur(c: cairo.Context) -> None:
    for radius, alpha in ((3.2, 1.0), (6.6, 0.62), (9.6, 0.32)):
        r, g, b, _ = _ink(c)
        c.set_source_rgba(r, g, b, alpha)
        c.arc(12, 12, radius, 0, 2 * math.pi)
        c.stroke()


def _pixelate(c: cairo.Context) -> None:
    for x, y, filled in ((4.5, 4.5, True), (12.5, 4.5, False), (4.5, 12.5, False), (12.5, 12.5, True)):
        _round_rect(c, x, y, 7, 7, 1.4)
        c.fill() if filled else c.stroke()


def _redact(c: cairo.Context) -> None:
    _round_rect(c, 3.5, 8, 17, 8, 2.2); c.fill()


def _emoji(c: cairo.Context) -> None:
    c.arc(12, 12, 8.5, 0, 2 * math.pi); c.stroke()
    c.arc(9, 10.2, 1.1, 0, 2 * math.pi); c.fill()
    c.arc(15, 10.2, 1.1, 0, 2 * math.pi); c.fill()
    c.arc(12, 12.4, 4.4, math.radians(25), math.radians(155)); c.stroke()


def _select(c: cairo.Context) -> None:
    c.move_to(6, 3.5); c.line_to(6, 18.5); c.line_to(9.8, 15); c.line_to(13, 21)
    c.line_to(15.4, 19.8); c.line_to(12.3, 14); c.line_to(17.5, 14); c.close_path()
    c.stroke()


def _undo(c: cairo.Context) -> None:
    c.move_to(9, 5.5); c.line_to(4.5, 10); c.line_to(9, 14.5)
    c.move_to(5, 10)
    c.curve_to(15, 8.5, 19.5, 11, 19.5, 15.5)
    c.curve_to(19.5, 18, 18, 19.5, 15.5, 19.5)
    c.stroke()


def _redo(c: cairo.Context) -> None:
    c.save(); c.translate(24, 0); c.scale(-1, 1); _undo(c); c.restore()


def _trash(c: cairo.Context) -> None:
    c.move_to(4.5, 7); c.line_to(19.5, 7)
    c.move_to(9.5, 7); c.line_to(9.5, 4.5); c.line_to(14.5, 4.5); c.line_to(14.5, 7)
    c.move_to(6.5, 7); c.line_to(7.5, 19.5); c.line_to(16.5, 19.5); c.line_to(17.5, 7)
    c.stroke()


def _check(c: cairo.Context) -> None:
    c.move_to(5, 12.5); c.line_to(10, 17.5); c.line_to(19.5, 7); c.stroke()


def _close(c: cairo.Context) -> None:
    c.move_to(6, 6); c.line_to(18, 18); c.move_to(18, 6); c.line_to(6, 18); c.stroke()


def _fill(c: cairo.Context) -> None:
    _round_rect(c, 4.5, 6.5, 15, 11, 3); c.fill()


def _round_rect(c: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    c.new_sub_path()
    c.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    c.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    c.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    c.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    c.close_path()


_INK: dict[int, tuple[float, float, float, float]] = {}


def _ink(c: cairo.Context) -> tuple[float, float, float, float]:
    return _INK[id(c)]


ICONS = {
    "select": _select, "arrow": _arrow, "line": _line, "rect": _rect,
    "ellipse": _ellipse, "pen": _pen, "highlighter": _highlighter, "text": _text,
    "badge": _badge, "blur": _blur, "pixelate": _pixelate, "redact": _redact,
    "sticker": _emoji, "undo": _undo, "redo": _redo, "trash": _trash,
    "check": _check, "close": _close, "fill": _fill,
}
NAMES = tuple(ICONS)


def draw(name: str, ctx: cairo.Context, size: float, rgba: tuple[float, float, float, float]) -> None:
    """Paint icon `name` into a `size` x `size` square at the origin."""
    ctx.save()
    ctx.scale(size / 24, size / 24)
    ctx.set_source_rgba(*rgba)
    ctx.set_line_width(1.9)
    ctx.set_line_cap(cairo.LINE_CAP_ROUND)
    ctx.set_line_join(cairo.LINE_JOIN_ROUND)
    _INK[id(ctx)] = rgba
    try:
        ICONS[name](ctx)
    finally:
        _INK.pop(id(ctx), None)
        ctx.restore()


class Icon(Gtk.DrawingArea):
    """An icon that takes the colour its CSS says, and redraws when that changes."""

    def __init__(self, icon: str, size: int = 20) -> None:
        super().__init__()
        self.icon = icon
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)
        self.connect("state-flags-changed", lambda *_: self.queue_draw())

    def set_icon(self, icon: str) -> None:
        self.icon = icon
        self.queue_draw()

    def _draw(self, _area, ctx, width, height) -> None:
        color = self.get_color()
        draw(self.icon, ctx, min(width, height), (color.red, color.green, color.blue, color.alpha))
