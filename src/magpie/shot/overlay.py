"""Choosing a region: the screen, frozen, with everything but your choice dimmed.

One layer surface per monitor, each showing that monitor as it was the instant
the key was pressed. Nothing is re-captured when you let go of the mouse: the
region is cut out of the picture that is already in memory, at the monitor's
native resolution, so what you saw is exactly what you get — a hover state or a
tooltip that was open stays open, and a fractional-scale monitor does not cost
a pixel of accuracy.

The frozen picture is a GPU texture at the monitor's *native* size, stretched
over a surface that is as big as the monitor is in logical pixels. At 1.25x
that is exactly one texture pixel per device pixel, so it is as sharp as the
screen was. (It used to be shrunk to logical size first and then enlarged again
by GTK, which is what made it soft.) The selection is kept in native pixels for
the same reason: the edges land on real pixels, not on 1.25-pixel steps.

Click a window to take it exactly; hold C to read the colour under the pointer
(press it to copy the hex); the arrow keys move the corner you are dragging by
one native pixel, ten with Shift.

Release the button and it is done; there is no second confirmation, because the
editor that follows is where you look at it and the one key that matters there
is Escape. Hold Space while dragging to move the rectangle instead of resizing
it, Shift to keep it square.
"""

from __future__ import annotations

import math
import subprocess
from typing import Callable

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Graphene", "1.0")
gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Gdk, GLib, Graphene, Gtk, Pango, PangoCairo  # noqa: E402

from ..config import load  # noqa: E402
from ..palette import Palette, _rgb, read  # noqa: E402
from ..ui.style import MONO, SANS  # noqa: E402
from .grab import Window, native_rect, nudge_step, pixel_hex, window_at  # noqa: E402
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
_SCRATCH = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))  # for measuring text


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


class _Canvas(Gtk.Widget):
    """A widget that is drawn by its owner, with the GPU doing the heavy part."""

    def __init__(self, owner: "RegionOverlay") -> None:
        super().__init__()
        self.owner = owner
        self.set_hexpand(True)
        self.set_vexpand(True)
        self.set_overflow(Gtk.Overflow.HIDDEN)

    def do_snapshot(self, snapshot: Gtk.Snapshot) -> None:
        self.owner._snapshot(snapshot, self.get_width(), self.get_height())


def _rect(x: float, y: float, w: float, h: float) -> Graphene.Rect:
    return Graphene.Rect().init(x, y, w, h)


def _colour(r: float, g: float, b: float, a: float) -> Gdk.RGBA:
    c = Gdk.RGBA()
    c.red, c.green, c.blue, c.alpha = r, g, b, a
    return c


def texture_of(surface: cairo.ImageSurface) -> Gdk.MemoryTexture:
    """The monitor as a texture, in its own pixels. The screen is opaque, so X not A."""
    surface.flush()
    return Gdk.MemoryTexture.new(
        surface.get_width(), surface.get_height(), Gdk.MemoryFormat.B8G8R8X8,
        GLib.Bytes.new(bytes(surface.get_data())), surface.get_stride())


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
        self.texture: Gdk.MemoryTexture | None = None   # the same, on the GPU
        self.windows: list[Window] = []                 # logical, relative to this monitor
        self.palette: Palette = read()
        self.index = 0
        self._flash: tuple[str, int] | None = None
        self._reset()

        self.area = _Canvas(self)
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
        #: The rectangle being dragged, in NATIVE pixels: x, y, w, h.
        self.sel: tuple[int, int, int, int] | None = None
        self.hover: Window | None = None
        self.dragging = False
        self.space = False
        self.shift = False
        self.nudge: tuple[int, int] = (0, 0)     # arrow keys, native pixels
        self._press: tuple[float, float] | None = None
        self._last: tuple[float, float] = (0.0, 0.0)

    def arm(self, native: cairo.ImageSurface, index: int, palette: Palette | None = None,
            windows: list[Window] | None = None) -> None:
        """Give this overlay the picture it will show; call before presenting."""
        self.native = native
        self.texture = texture_of(native)
        self.index = index
        self.palette = palette or read()
        self.windows = list(windows or [])
        self._flash = None
        self._reset()
        self.hint.set_visible(True)
        self.area.queue_draw()

    def disarm(self) -> None:
        self.hint.remove_css_class(OPENING)
        self.native = self.texture = None
        self.windows = []
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
        for key, what in (("drag", "select"), ("click", "window"), ("Space", "move"),
                          ("C", "colour"), ("Esc", "cancel"), ("Enter", "this screen")):
            k = Gtk.Label(label=key)
            k.add_css_class("key")
            box.append(k)
            box.append(Gtk.Label(label=what))
        return box

    def _hole(self) -> tuple[float, float, float, float] | None:
        """What is left undimmed, in logical pixels: the selection, or the window under the pointer."""
        k = self._scale()
        if self.sel:
            x, y, w, h = self.sel
            return x / k, y / k, w / k, h / k
        if self.hover is not None and not self.dragging:
            return self._window_box(self.hover)
        return None

    def _window_box(self, win: Window) -> tuple[float, float, float, float]:
        width, height = self.logical_size()
        x0, y0 = max(0, win.x), max(0, win.y)
        x1, y1 = min(width, win.x + win.width), min(height, win.y + win.height)
        return float(x0), float(y0), float(max(0, x1 - x0)), float(max(0, y1 - y0))

    def _snapshot(self, snapshot: Gtk.Snapshot, width: int, height: int) -> None:
        if self.texture is None or self.native is None:
            return
        # The picture: native pixels onto a surface that is native / scale in
        # logical size, so one texture pixel is one device pixel. Plain
        # append_texture, not append_scaled_texture: measured on a 1.25x output,
        # the scaled variant resamples even at exactly 1:1 and softens a 1-px
        # pattern to a fifth of its contrast; this one is pixel-exact.
        snapshot.append_texture(self.texture, _rect(0, 0, width, height))

        hole = self._hole()
        shade = _colour(0, 0, 0, DIM)
        if hole is None:
            snapshot.append_color(shade, _rect(0, 0, width, height))
        else:
            x, y, w, h = hole
            snapshot.append_color(shade, _rect(0, 0, width, y))
            snapshot.append_color(shade, _rect(0, y + h, width, height - y - h))
            snapshot.append_color(shade, _rect(0, y, x, h))
            snapshot.append_color(shade, _rect(x + w, y, width - x - w, h))

        accent = _rgb01(self.palette.accent)
        if hole is not None:
            self._outline(snapshot, hole, accent)
            self._size_label(snapshot, hole, width, height)
        elif self.pointer and not self.dragging:
            px, py = self.pointer
            line = _colour(1, 1, 1, 0.35)
            snapshot.append_color(line, _rect(0, round(py), width, 1))
            snapshot.append_color(line, _rect(round(px), 0, 1, height))

        if self.pointer:
            self._loupe(snapshot, width, height, accent)

    def _outline(self, snapshot, hole, accent) -> None:
        x, y, w, h = hole
        ctx = snapshot.append_cairo(_rect(x - 2, y - 2, w + 4, h + 4))
        # A light line outside and the accent inside: visible on a white
        # page and on a black one.
        ctx.set_line_width(1)
        ctx.set_source_rgba(1, 1, 1, 0.9)
        ctx.rectangle(x - 0.5, y - 0.5, w + 1, h + 1)
        ctx.stroke()
        ctx.set_source_rgba(*accent, 1)
        ctx.set_line_width(1.5)
        ctx.rectangle(x + 0.75, y + 0.75, max(0, w - 1.5), max(0, h - 1.5))
        ctx.stroke()

    def _pango(self, ctx, text: str, family: str, size: float, weight=Pango.Weight.NORMAL):
        layout = PangoCairo.create_layout(ctx)
        description = Pango.FontDescription(f"{family} {size}px")
        description.set_weight(weight)
        layout.set_font_description(description)
        layout.set_text(text, -1)
        return layout

    def _pill(self, snapshot, text: str, cx: float, top: float, width: int, height: int,
              family: str = MONO, size: float = 12) -> None:
        _, logical = self._pango(_SCRATCH, text, family, size).get_pixel_extents()
        pw, ph = logical.width + 18, logical.height + 10
        x = max(6, min(width - pw - 6, cx - pw / 2))
        y = max(6, min(height - ph - 6, top))
        ctx = snapshot.append_cairo(_rect(x - 1, y - 1, pw + 2, ph + 2))
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
        PangoCairo.show_layout(ctx, self._pango(ctx, text, family, size))

    def _scale(self) -> float:
        """Native pixels per logical pixel on this monitor."""
        if self.native is None:
            return 1.0
        width = self.logical_size()[0] or 1
        return self.native.get_width() / width

    def _size_label(self, snapshot, hole, width, height) -> None:
        x, y, w, h = hole
        k = self._scale()
        label = f"{round(w * k)} × {round(h * k)}"
        below = y + h + 10
        self._pill(snapshot, label, x + w / 2, below if below < height - 40 else y - 34,
                   width, height)

    def _colour_here(self) -> str:
        """`#rrggbb` of the native pixel under the pointer."""
        px, py = self.pointer  # type: ignore[misc]
        k = self._scale()
        return pixel_hex(self.native.get_data(), self.native.get_stride(),
                         self.native.get_width(), self.native.get_height(),
                         math.floor(px * k), math.floor(py * k))

    def _loupe(self, snapshot, width: int, height: int, accent) -> None:
        px, py = self.pointer  # type: ignore[misc]
        k = self._scale()
        ix, iy = px * k, py * k
        cx = px + 26 + LOUPE_R if px + 26 + 2 * LOUPE_R < width - 8 else px - 26 - LOUPE_R
        cy = py + 26 + LOUPE_R if py + 26 + 2 * LOUPE_R < height - 40 else py - 26 - LOUPE_R
        ctx = snapshot.append_cairo(_rect(cx - LOUPE_R - 2, cy - LOUPE_R - 2,
                                          2 * LOUPE_R + 4, 2 * LOUPE_R + 4))
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
        if self._flash is not None:
            text = f"copied {self._flash[0]}"
        else:
            text = f"{math.floor(ix)}, {math.floor(iy)}  {self._colour_here()}"
        self._pill(snapshot, text, cx, cy + LOUPE_R + 8, width, height, size=11)

    # -- pointer ------------------------------------------------------------

    def _motion(self, _controller, x: float, y: float) -> None:
        self.pointer = (x, y)
        if not self.dragging:
            self.hover = window_at(self.windows, x, y)
        self.area.queue_draw()

    def _leave(self, _controller) -> None:
        if not self.dragging:
            self.pointer = None
            self.hover = None
            self.area.queue_draw()

    def _begin(self, _gesture, x: float, y: float) -> None:
        self.dragging = True
        self.anchor = (x, y)
        self._press = (x, y)
        self.pointer = (x, y)
        self._last = (x, y)
        self.nudge = (0, 0)
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

    def _rect(self, a, b) -> tuple[int, int, int, int]:
        """The rectangle between two logical points, as whole NATIVE pixels."""
        size = (self.native.get_width(), self.native.get_height()) if self.native is not None else (1, 1)
        return native_rect(a, b, self._scale(), size, self.nudge, self.shift)

    def _end(self, _gesture, _dx, _dy) -> None:
        self.dragging = False
        sel, self.sel, self.anchor = self.sel, None, None
        press, self._press = self._press, None
        k = self._scale()
        need = max(1, round(MIN_SIDE * k))
        box = None
        if sel and sel[2] >= need and sel[3] >= need:
            x, y, w, h = sel
            box = (x, y, x + w, y + h)
        elif press is not None:
            # A click, not a drag: take the window that was under it.
            win = window_at(self.windows, *press)
            if win is not None:
                x, y, w, h = self._window_box(win)
                if w >= MIN_SIDE and h >= MIN_SIDE:
                    nw, nh = self.native.get_width(), self.native.get_height()
                    box = (min(nw, round(x * k)), min(nh, round(y * k)),
                           min(nw, round((x + w) * k)), min(nh, round((y + h) * k)))
        self.area.queue_draw()
        if box is not None:
            self._on_region(self.index, box)
        else:
            self.hint.set_visible(True)

    # -- keys ---------------------------------------------------------------

    def _pressed(self, _c, keyval, _code, state) -> bool:
        if keyval == Gdk.KEY_space:
            self.space = True
            return True
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R):
            self.shift = True
            return False
        if keyval in (Gdk.KEY_c, Gdk.KEY_C) and self.pointer and not self.dragging:
            self._copy_colour()
            return True
        if self.dragging and self.anchor is not None:
            step = nudge_step(Gdk.keyval_name(keyval) or "", bool(state & Gdk.ModifierType.SHIFT_MASK))
            if step is not None:
                self.nudge = (self.nudge[0] + step[0], self.nudge[1] + step[1])
                self.sel = self._rect(self.anchor, self.pointer)
                self.area.queue_draw()
                return True
        # Swallowed here, acted on at the release: closing on the press hands
        # the keyboard to the window below before the key is up, and that
        # window then receives the release.
        return keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter)

    def _copy_colour(self) -> None:
        text = self._colour_here()
        try:
            subprocess.Popen(["wl-copy", "--", text], stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError:
            return
        self._flash = (text, GLib.timeout_add(1400, self._unflash))
        self.area.queue_draw()

    def _unflash(self) -> bool:
        self._flash = None
        self.area.queue_draw()
        return GLib.SOURCE_REMOVE

    def _released(self, _c, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_space:
            self.space = False
            return True
        if keyval in (Gdk.KEY_Shift_L, Gdk.KEY_Shift_R):
            self.shift = False
            return False
        if keyval in (Gdk.KEY_c, Gdk.KEY_C):
            return True
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
