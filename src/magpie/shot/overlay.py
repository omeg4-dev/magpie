"""Choosing a region: the screen, frozen, with everything but your choice dimmed.

One layer surface per monitor, each showing that monitor as it was the instant
the key was pressed. Nothing is re-captured when you let go of the mouse: the
region is cut out of the picture that is already in memory, at the monitor's
native resolution, so what you saw is exactly what you get — a hover state or a
tooltip that was open stays open, and a fractional-scale monitor does not cost
a pixel of accuracy.

Release the button and it is done; there is no second confirmation, because the
editor that follows is where you look at it and the one key that matters there
is Escape. Hold Space while dragging to move the rectangle instead of resizing
it, Shift to keep it square.
"""

from __future__ import annotations

import math
from typing import Callable

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango, PangoCairo  # noqa: E402

from ..config import load  # noqa: E402
from ..palette import Palette, _rgb, read  # noqa: E402
from ..ui.style import MONO, SANS  # noqa: E402
from .style import OPENING  # noqa: E402

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell
except (ValueError, ImportError):  # pragma: no cover - depends on the machine
    Gtk4LayerShell = None

__all__ = ["RegionOverlay", "NAMESPACE", "as_layer"]

NAMESPACE = "magpie-shot"
DIM = 0.52
MIN_SIDE = 4  # logical pixels; smaller than this is a click, not a region
LOUPE_R = 56
LOUPE_ZOOM = 9


def as_layer(window: Gtk.Window, monitor: Gdk.Monitor | None, *, exclusive: bool = True) -> None:
    """Make `window` a full-monitor overlay the compositor owns."""
    if Gtk4LayerShell is None:  # pragma: no cover
        return
    Gtk4LayerShell.init_for_window(window)
    Gtk4LayerShell.set_namespace(window, NAMESPACE)
    Gtk4LayerShell.set_layer(window, Gtk4LayerShell.Layer.OVERLAY)
    if monitor is not None:
        Gtk4LayerShell.set_monitor(window, monitor)
    for edge in (Gtk4LayerShell.Edge.TOP, Gtk4LayerShell.Edge.BOTTOM,
                 Gtk4LayerShell.Edge.LEFT, Gtk4LayerShell.Edge.RIGHT):
        Gtk4LayerShell.set_anchor(window, edge, True)
    # Cover the bar and the dock too: -1 means "do not move for anyone".
    Gtk4LayerShell.set_exclusive_zone(window, -1)
    Gtk4LayerShell.set_keyboard_mode(
        window, Gtk4LayerShell.KeyboardMode.EXCLUSIVE if exclusive
        else Gtk4LayerShell.KeyboardMode.NONE)


def _rgb01(colour: str) -> tuple[float, float, float]:
    r, g, b = _rgb(colour)
    return r / 255, g / 255, b / 255


class RegionOverlay(Gtk.Window):
    """The frozen picture of one monitor, and the rectangle being dragged on it."""

    def __init__(self, app: Gtk.Application, monitor: Gdk.Monitor, *,
                 on_region: Callable, on_whole: Callable, on_cancel: Callable) -> None:
        super().__init__(application=app, title="magpie-shot")
        self.add_css_class("shot-overlay")
        self.set_decorated(False)
        self.gdk_monitor = monitor
        self._on_region, self._on_whole, self._on_cancel = on_region, on_whole, on_cancel
        as_layer(self, monitor)

        self.native: cairo.ImageSurface | None = None   # the monitor, in its own pixels
        self.bright: cairo.ImageSurface | None = None   # the same, at logical size
        self.palette: Palette = read()
        self.index = 0
        self._reset()

        self.area = Gtk.DrawingArea()
        self.area.set_hexpand(True)
        self.area.set_vexpand(True)
        self.area.set_draw_func(self._draw)
        self.area.set_cursor_from_name("crosshair")

        self.hint = self._build_hint()
        # Only the hint fades in; the frozen picture has to be there at once, exactly
        # over the screen it was taken from.
        self.hint.connect("map", lambda w: load().shot_animation and w.add_css_class(OPENING))
        overlay = Gtk.Overlay()
        overlay.set_child(self.area)
        overlay.add_overlay(self.hint)
        self.set_child(overlay)

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._begin)
        drag.connect("drag-update", self._update)
        drag.connect("drag-end", self._end)
        self.area.add_controller(drag)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._motion)
        motion.connect("leave", self._leave)
        self.area.add_controller(motion)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._pressed)
        keys.connect("key-released", self._released)
        self.add_controller(keys)

    # -- state --------------------------------------------------------------

    def _reset(self) -> None:
        self.pointer: tuple[float, float] | None = None
        self.anchor: tuple[float, float] | None = None
        self.sel: tuple[float, float, float, float] | None = None   # logical x, y, w, h
        self.dragging = False
        self.space = False
        self.shift = False
        self._last: tuple[float, float] = (0.0, 0.0)

    def arm(self, native: cairo.ImageSurface, index: int, palette: Palette | None = None) -> None:
        """Give this overlay the picture it will show; call before presenting."""
        self.native = native
        self.index = index
        self.palette = palette or read()
        self.bright = None
        self._reset()
        self.hint.set_visible(True)
        self.area.queue_draw()

    def disarm(self) -> None:
        self.hint.remove_css_class(OPENING)
        self.native = self.bright = None
        self._reset()
        self.set_visible(False)

    def logical_size(self) -> tuple[int, int]:
        geometry = self.gdk_monitor.get_geometry()
        return geometry.width, geometry.height

    # -- drawing ------------------------------------------------------------

    def _build_hint(self) -> Gtk.Widget:
        box = Gtk.Box(spacing=0)
        box.add_css_class("shot-hint")
        box.set_halign(Gtk.Align.CENTER)
        box.set_valign(Gtk.Align.START)
        box.set_margin_top(34)
        box.set_can_target(False)
        for key, what in (("drag", "select"), ("Space", "move"), ("Shift", "square"),
                          ("Esc", "cancel"), ("Enter", "this screen")):
            k = Gtk.Label(label=key)
            k.add_css_class("key")
            box.append(k)
            box.append(Gtk.Label(label=what))
        return box

    def _bright(self, width: int, height: int) -> cairo.ImageSurface:
        """The monitor at logical size, made once per presentation."""
        if self.bright is None or self.bright.get_width() != width:
            surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, width, height)
            ctx = cairo.Context(surface)
            ctx.scale(width / self.native.get_width(), height / self.native.get_height())
            ctx.set_source_surface(self.native, 0, 0)
            ctx.get_source().set_filter(cairo.FILTER_BEST)
            ctx.paint()
            self.bright = surface
        return self.bright

    def _draw(self, _area, ctx: cairo.Context, width: int, height: int) -> None:
        if self.native is None:
            return
        ctx.set_source_surface(self._bright(width, height), 0, 0)
        ctx.paint()

        # Dim everything except the selection: one fill with a hole in it.
        ctx.set_fill_rule(cairo.FILL_RULE_EVEN_ODD)
        ctx.rectangle(0, 0, width, height)
        if self.sel:
            ctx.rectangle(*self.sel)
        ctx.set_source_rgba(0, 0, 0, DIM)
        ctx.fill()

        accent = _rgb01(self.palette.accent)
        if self.sel:
            x, y, w, h = self.sel
            # A light line outside and the accent inside: visible on a white
            # page and on a black one.
            ctx.set_line_width(1)
            ctx.set_source_rgba(1, 1, 1, 0.9)
            ctx.rectangle(x - 0.5, y - 0.5, w + 1, h + 1)
            ctx.stroke()
            ctx.set_source_rgba(*accent, 1)
            ctx.set_line_width(1.5)
            ctx.rectangle(x + 0.75, y + 0.75, w - 1.5, h - 1.5)
            ctx.stroke()
            self._size_label(ctx, x, y, w, h, width, height)
        elif self.pointer and not self.dragging:
            px, py = self.pointer
            ctx.set_source_rgba(1, 1, 1, 0.35)
            ctx.set_line_width(1)
            ctx.move_to(0, round(py) + 0.5); ctx.line_to(width, round(py) + 0.5)
            ctx.move_to(round(px) + 0.5, 0); ctx.line_to(round(px) + 0.5, height)
            ctx.stroke()

        if self.pointer:
            self._loupe(ctx, width, height, accent)

    def _pango(self, ctx, text: str, family: str, size: float, weight=Pango.Weight.NORMAL):
        layout = PangoCairo.create_layout(ctx)
        description = Pango.FontDescription(f"{family} {size}px")
        description.set_weight(weight)
        layout.set_font_description(description)
        layout.set_text(text, -1)
        return layout

    def _pill(self, ctx, text: str, cx: float, top: float, width: int, height: int,
              family: str = MONO, size: float = 12) -> None:
        layout = self._pango(ctx, text, family, size)
        _, logical = layout.get_pixel_extents()
        pw, ph = logical.width + 18, logical.height + 10
        x = max(6, min(width - pw - 6, cx - pw / 2))
        y = max(6, min(height - ph - 6, top))
        ink = _rgb01(self.palette.ink)
        ctx.set_source_rgba(*ink, 0.94)
        _round(ctx, x, y, pw, ph, ph / 2)
        ctx.fill()
        ctx.set_source_rgba(*_rgb01(self.palette.edge), 1)
        ctx.set_line_width(1)
        _round(ctx, x + 0.5, y + 0.5, pw - 1, ph - 1, ph / 2)
        ctx.stroke()
        ctx.set_source_rgba(*_rgb01(self.palette.bone), 1)
        ctx.move_to(x + 9, y + 5)
        PangoCairo.show_layout(ctx, layout)

    def _scale(self) -> float:
        width = self.logical_size()[0] or 1
        return self.native.get_width() / width

    def _size_label(self, ctx, x, y, w, h, width, height) -> None:
        k = self._scale()
        label = f"{round(w * k)} × {round(h * k)}"
        below = y + h + 10
        self._pill(ctx, label, x + w / 2, below if below < height - 40 else y - 34, width, height)

    def _loupe(self, ctx, width: int, height: int, accent) -> None:
        px, py = self.pointer  # type: ignore[misc]
        k = self._scale()
        ix, iy = px * k, py * k
        cx = px + 26 + LOUPE_R if px + 26 + 2 * LOUPE_R < width - 8 else px - 26 - LOUPE_R
        cy = py + 26 + LOUPE_R if py + 26 + 2 * LOUPE_R < height - 40 else py - 26 - LOUPE_R
        # Every arc starts from a clean path: an arc draws a line from wherever
        # the path last was, which is how a stray diagonal got into the loupe.
        ctx.new_path()
        ctx.save()
        ctx.arc(cx, cy, LOUPE_R, 0, 2 * math.pi)
        ctx.clip()
        ctx.set_source_rgb(0, 0, 0)
        ctx.paint()
        ctx.save()
        ctx.translate(cx, cy)
        ctx.scale(LOUPE_ZOOM, LOUPE_ZOOM)
        ctx.set_source_surface(self.native, -math.floor(ix) - 0.5, -math.floor(iy) - 0.5)
        ctx.get_source().set_filter(cairo.FILTER_NEAREST)
        ctx.paint()
        ctx.restore()
        # The pixel under the pointer, boxed.
        ctx.set_line_width(1.5)
        ctx.set_source_rgba(1, 1, 1, 0.95)
        ctx.new_path()
        ctx.rectangle(cx - LOUPE_ZOOM / 2, cy - LOUPE_ZOOM / 2, LOUPE_ZOOM, LOUPE_ZOOM)
        ctx.stroke()
        ctx.new_path()
        ctx.restore()
        ctx.set_line_width(2)
        ctx.set_source_rgba(*accent, 1)
        ctx.new_path()
        ctx.arc(cx, cy, LOUPE_R, 0, 2 * math.pi)
        ctx.stroke()
        self._pill(ctx, f"{math.floor(ix)}, {math.floor(iy)}", cx, cy + LOUPE_R + 8, width, height,
                   size=11)

    # -- pointer ------------------------------------------------------------

    def _motion(self, _controller, x: float, y: float) -> None:
        self.pointer = (x, y)
        self.area.queue_draw()

    def _leave(self, _controller) -> None:
        if not self.dragging:
            self.pointer = None
            self.area.queue_draw()

    def _begin(self, _gesture, x: float, y: float) -> None:
        self.dragging = True
        self.anchor = (x, y)
        self.pointer = (x, y)
        self._last = (x, y)
        self.sel = None
        self.hint.set_visible(False)
        self.area.queue_draw()

    def _update(self, gesture, dx: float, dy: float) -> None:
        if self.anchor is None:
            return
        _, sx, sy = gesture.get_start_point()
        pointer = (sx + dx, sy + dy)
        if self.space:
            # Move the whole rectangle with the pointer instead of resizing it.
            mx, my = pointer[0] - self._last[0], pointer[1] - self._last[1]
            self.anchor = (self.anchor[0] + mx, self.anchor[1] + my)
        self._last = pointer
        self.pointer = pointer
        self.sel = self._rect(self.anchor, pointer)
        self.area.queue_draw()

    def _rect(self, a, b) -> tuple[float, float, float, float]:
        width, height = self.logical_size()
        bx, by = (max(0, min(width, b[0])), max(0, min(height, b[1])))
        if self.shift:
            side = max(abs(bx - a[0]), abs(by - a[1]))
            bx = a[0] + math.copysign(side, bx - a[0] or 1)
            by = a[1] + math.copysign(side, by - a[1] or 1)
            bx, by = max(0, min(width, bx)), max(0, min(height, by))
        x0, x1 = sorted((max(0, min(width, a[0])), bx))
        y0, y1 = sorted((max(0, min(height, a[1])), by))
        return (round(x0), round(y0), round(x1) - round(x0), round(y1) - round(y0))

    def _end(self, _gesture, _dx, _dy) -> None:
        self.dragging = False
        sel, self.sel, self.anchor = self.sel, None, None
        self.area.queue_draw()
        if sel and sel[2] >= MIN_SIDE and sel[3] >= MIN_SIDE:
            k = self._scale()
            x, y, w, h = sel
            box = (round(x * k), round(y * k), round((x + w) * k), round((y + h) * k))
            self._on_region(self.index, box)
        else:
            self.hint.set_visible(True)

    # -- keys ---------------------------------------------------------------

    def _pressed(self, _c, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_space:
            self.space = True
            return True
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R):
            self.shift = True
            return False
        # Swallowed here, acted on at the release: closing on the press hands
        # the keyboard to the window below before the key is up, and that
        # window then receives the release.
        return keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter)

    def _released(self, _c, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_space:
            self.space = False
            return True
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R):
            self.shift = False
            return False
        if keyval == Gdk.KEY_Escape:
            GLib.idle_add(self._on_cancel)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            # Enter with nothing selected: the monitor the pointer is on.
            GLib.idle_add(self._on_whole, self.index)
            return True
        return False


def _round(ctx: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()
