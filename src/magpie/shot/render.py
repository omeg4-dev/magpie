"""Painting an edited screenshot — for the window and for the file, by one code path.

The editor shows what `Renderer.paint` draws, and saving calls the very same
method at scale 1 onto a surface the size of the picture. There is no second
renderer to drift out of step with the first, which is how "it looked right in
the editor" turns into a saved file that does not.

Blur, pixelate and redact are applied to *pixels*, once, from the untouched
original: whatever is under a redaction bar is not hidden in the PNG, it is
gone. They never read the other annotations, so a blur does not smear an arrow
drawn across it.
"""

from __future__ import annotations

import io
import math

import cairo
import gi
from PIL import Image, ImageFilter

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo  # noqa: E402

from .model import (Arrow, Badge, Blur, Ellipse, Highlighter, Item, Line, Pen,  # noqa: E402
                    Pixelate, Rect, Redact, Sticker, Text, contrast)

__all__ = ["Renderer", "measure_text", "to_pil", "from_pil", "FONT"]

FONT = "IBM Plex Sans SemiBold"

#: The marker is see-through; a solid one would just be a bar.
HIGHLIGHT_ALPHA = 0.42


def to_pil(surface: cairo.ImageSurface) -> Image.Image:
    """A cairo ARGB32 surface as an RGBA picture (cairo is premultiplied; the
    surfaces here are opaque, so no un-premultiplying is needed)."""
    surface.flush()
    return Image.frombuffer("RGBA", (surface.get_width(), surface.get_height()),
                            bytes(surface.get_data()), "raw", "BGRA",
                            surface.get_stride(), 1)


def from_pil(image: Image.Image) -> cairo.ImageSurface:
    image = image.convert("RGBA")
    w, h = image.size
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    stride = surface.get_stride()
    rows = image.tobytes("raw", "BGRA")
    surface.flush()
    buf = surface.get_data()
    if stride == w * 4:
        buf[:] = rows
    else:  # pragma: no cover - ARGB32 rows are 4-byte aligned already
        for y in range(h):
            buf[y * stride:y * stride + w * 4] = rows[y * w * 4:(y + 1) * w * 4]
    surface.mark_dirty()
    return surface


# -- text --------------------------------------------------------------------

_scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))


def _layout(ctx: cairo.Context, text: str, size: float) -> Pango.Layout:
    layout = PangoCairo.create_layout(ctx)
    layout.set_font_description(Pango.FontDescription(f"{FONT} {size}px"))
    layout.set_text(text or " ", -1)
    return layout


def measure_text(item: Text) -> tuple[float, float]:
    """Set and return the size of a text object. Call after its text or size
    changes; hits and handles read the stored numbers."""
    layout = _layout(_scratch, item.text, item.size)
    _, logical = layout.get_pixel_extents()
    item.w = float(max(logical.width, item.size * 0.6))
    item.h = float(max(logical.height, item.size))
    return item.w, item.h


# -- region effects -----------------------------------------------------------

def _effect(source: Image.Image, kind: str, strength: float,
            box: tuple[int, int, int, int]) -> Image.Image:
    left, top, right, bottom = box
    if kind == "blur":
        # Blur with some of the surroundings included, so the edge of the
        # region is not a smear towards nothing; then cut back to the region.
        pad = int(strength * 3)
        wide = (max(0, left - pad), max(0, top - pad),
                min(source.width, right + pad), min(source.height, bottom + pad))
        blurred = source.crop(wide).filter(ImageFilter.GaussianBlur(strength))
        return blurred.crop((left - wide[0], top - wide[1],
                             right - wide[0], bottom - wide[1]))
    crop = source.crop(box)
    block = max(2, int(strength))
    small = crop.resize((max(1, math.ceil(crop.width / block)),
                         max(1, math.ceil(crop.height / block))), Image.BOX)
    return small.resize(crop.size, Image.NEAREST)


class Renderer:
    """Draws one picture's annotations. Holds the original and the cache of
    effects computed from it; make a new one for a new picture."""

    def __init__(self, base: cairo.ImageSurface) -> None:
        self.base = base
        self.width = base.get_width()
        self.height = base.get_height()
        self._pil: Image.Image | None = None
        self._effects: dict[tuple, cairo.ImageSurface] = {}

    # -- public -------------------------------------------------------------

    def paint(self, ctx: cairo.Context, items, scale: float = 1.0, *,
              hide: int | None = None) -> None:
        """The picture and everything on it. `scale` is screen pixels per image
        pixel; `hide` leaves one object out (the one being typed into)."""
        ctx.save()
        ctx.scale(scale, scale)
        ctx.set_source_surface(self.base, 0, 0)
        if scale != 1.0:
            # Down-scaling a screenshot with the default filter shimmers.
            ctx.get_source().set_filter(cairo.FILTER_BEST if scale < 1 else cairo.FILTER_NEAREST)
        ctx.paint()
        for item in items:
            if item.id != hide:
                self._paint_item(ctx, item)
        ctx.restore()

    def export_png(self, items) -> bytes:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width, self.height)
        self.paint(cairo.Context(surface), items, 1.0)
        out = io.BytesIO()
        surface.write_to_png(out)
        return out.getvalue()

    def export_surface(self, items) -> cairo.ImageSurface:
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width, self.height)
        self.paint(cairo.Context(surface), items, 1.0)
        return surface

    # -- items --------------------------------------------------------------

    def _paint_item(self, ctx: cairo.Context, item: Item) -> None:
        ctx.save()
        try:
            if isinstance(item, (Arrow, Line)):
                self._linear(ctx, item)
            elif isinstance(item, (Rect, Ellipse)):
                self._box(ctx, item)
            elif isinstance(item, Highlighter):
                self._stroke(ctx, item, item.width * item.SCALE, HIGHLIGHT_ALPHA,
                             cap=cairo.LINE_CAP_BUTT)
            elif isinstance(item, Pen):
                self._stroke(ctx, item, item.width, None, cap=cairo.LINE_CAP_ROUND)
            elif isinstance(item, Text):
                self._text(ctx, item)
            elif isinstance(item, Badge):
                self._badge(ctx, item)
            elif isinstance(item, (Blur, Pixelate)):
                self._effect_region(ctx, item)
            elif isinstance(item, Redact):
                x, y, w, h = item.bounds()
                ctx.set_source_rgba(*item.color)
                ctx.rectangle(round(x), round(y), round(w), round(h))
                ctx.fill()
            elif isinstance(item, Sticker):
                self._sticker(ctx, item)
        finally:
            ctx.restore()

    def _linear(self, ctx: cairo.Context, item: Arrow | Line) -> None:
        (x0, y0), (x1, y1) = item.p0, item.p1
        ctx.set_source_rgba(*item.color)
        ctx.set_line_width(item.width)
        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        if isinstance(item, Line) or item.length() < 1:
            ctx.move_to(x0, y0)
            ctx.line_to(x1, y1)
            ctx.stroke()
            return

        length = item.length()
        angle = math.atan2(y1 - y0, x1 - x0)
        head = min(max(item.width * 4.2, 16.0), length * 0.6)
        spread = math.radians(26)
        # The shaft stops inside the head, so its round cap never pokes out of
        # the point.
        inset = head * 0.7
        ctx.move_to(x0, y0)
        ctx.line_to(x1 - inset * math.cos(angle), y1 - inset * math.sin(angle))
        ctx.stroke()
        ctx.move_to(x1, y1)
        for side in (-1, 1):
            ctx.line_to(x1 - head * math.cos(angle + side * spread),
                        y1 - head * math.sin(angle + side * spread))
        ctx.close_path()
        ctx.fill_preserve()
        ctx.set_line_width(item.width * 0.5)
        ctx.stroke()

    def _box(self, ctx: cairo.Context, item: Rect | Ellipse) -> None:
        x, y, w, h = item.bounds()
        if w < 1 and h < 1:
            return
        ctx.set_source_rgba(*item.color)
        ctx.set_line_width(item.width)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        if isinstance(item, Ellipse):
            ctx.save()
            ctx.translate(x + w / 2, y + h / 2)
            ctx.scale(max(w / 2, 0.5), max(h / 2, 0.5))
            ctx.arc(0, 0, 1, 0, 2 * math.pi)
            ctx.restore()
        else:
            radius = min(item.width * 1.2, w / 2, h / 2)
            _rounded(ctx, x, y, w, h, radius)
        if item.fill:
            ctx.fill()
        else:
            ctx.stroke()

    def _stroke(self, ctx: cairo.Context, item, width: float, alpha: float | None,
                cap: int) -> None:
        points = item.points
        if not points:
            return
        r, g, b, a = item.color
        ctx.set_source_rgba(r, g, b, a if alpha is None else alpha)
        ctx.set_line_width(width)
        ctx.set_line_cap(cap)
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        if len(points) == 1:
            ctx.arc(points[0][0], points[0][1], width / 2, 0, 2 * math.pi)
            ctx.fill()
            return
        # Midpoint smoothing: each recorded point is a control point, so a
        # shaky hand comes out as a curve instead of a polyline.
        ctx.move_to(*points[0])
        for (px, py), (nx, ny) in zip(points[1:], points[2:]):
            mx, my = (px + nx) / 2, (py + ny) / 2
            _quad(ctx, px, py, mx, my)
        ctx.line_to(*points[-1])
        ctx.stroke()

    def _text(self, ctx: cairo.Context, item: Text) -> None:
        if not item.text:
            return
        layout = _layout(ctx, item.text, item.size)
        ctx.translate(item.x, item.y)
        # An outline in the opposite tone keeps text legible on any picture.
        ctx.set_line_join(cairo.LINE_JOIN_ROUND)
        ctx.set_line_width(max(2.0, item.size / 7))
        halo = contrast(item.color)
        ctx.set_source_rgba(halo[0], halo[1], halo[2], 0.9)
        PangoCairo.layout_path(ctx, layout)
        ctx.stroke()
        ctx.set_source_rgba(*item.color)
        PangoCairo.show_layout(ctx, layout)

    def _badge(self, ctx: cairo.Context, item: Badge) -> None:
        ink = contrast(item.color)
        ctx.arc(item.x, item.y, item.radius, 0, 2 * math.pi)
        ctx.set_source_rgba(*item.color)
        ctx.fill_preserve()
        ctx.set_source_rgba(ink[0], ink[1], ink[2], 0.95)
        ctx.set_line_width(max(1.5, item.radius * 0.12))
        ctx.stroke()

        label = str(item.n)
        size = item.radius * (1.15 if len(label) < 2 else 0.95 if len(label) < 3 else 0.75)
        layout = _layout(ctx, label, size)
        _, logical = layout.get_pixel_extents()
        ctx.move_to(item.x - logical.width / 2 - logical.x,
                    item.y - logical.height / 2 - logical.y)
        ctx.set_source_rgba(*ink)
        PangoCairo.show_layout(ctx, layout)

    def _effect_region(self, ctx: cairo.Context, item: Blur | Pixelate) -> None:
        x, y, w, h = item.bounds()
        left, top = max(0, int(x)), max(0, int(y))
        right, bottom = min(self.width, math.ceil(x + w)), min(self.height, math.ceil(y + h))
        if right - left < 1 or bottom - top < 1:
            return
        key = (item.kind, left, top, right, bottom, round(item.strength, 1))
        surface = self._effects.get(key)
        if surface is None:
            if self._pil is None:
                self._pil = to_pil(self.base).convert("RGB")
            surface = from_pil(_effect(self._pil, item.kind, item.strength,
                                       (left, top, right, bottom)))
            if len(self._effects) > 64:
                self._effects.pop(next(iter(self._effects)))
            self._effects[key] = surface
        ctx.set_source_surface(surface, left, top)
        ctx.rectangle(left, top, right - left, bottom - top)
        ctx.fill()

    def _sticker(self, ctx: cairo.Context, item: Sticker) -> None:
        surface = item.surface
        if surface is None:
            return
        sw, sh = surface.get_width(), surface.get_height()
        ctx.translate(item.x - item.size / 2, item.y - item.size / 2)
        ctx.scale(item.size / sw, item.size / sh)
        ctx.set_source_surface(surface, 0, 0)
        ctx.get_source().set_filter(cairo.FILTER_BEST)
        ctx.paint()


def _rounded(ctx: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    if r <= 0.5:
        ctx.rectangle(x, y, w, h)
        return
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def _quad(ctx: cairo.Context, cx: float, cy: float, x: float, y: float) -> None:
    """A quadratic Bézier from the current point, as cairo only draws cubics."""
    x0, y0 = ctx.get_current_point()
    ctx.curve_to(x0 + 2 / 3 * (cx - x0), y0 + 2 / 3 * (cy - y0),
                 x + 2 / 3 * (cx - x), y + 2 / 3 * (cy - y), x, y)
