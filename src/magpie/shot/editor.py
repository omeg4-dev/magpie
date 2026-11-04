"""The editor: a card in the middle of the screen, over a dimmed desktop.

It is a layer surface like the clipboard, not an ordinary window, so it appears
at once, takes the keyboard without a fight with the window manager, and has
nothing to focus, tile, animate or lose behind another window. The card in the
middle is the window as far as anyone can tell.

Two keys matter and they are the two the whole tool is built around:
**Enter** saves (to the folder, to the clipboard, and into magpie) and
**Escape** closes without saving. Everything else is optional.
"""

from __future__ import annotations

import copy
import math
from typing import Callable

import cairo
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
gi.require_version("Pango", "1.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from ..palette import Palette, _rgb, read  # noqa: E402
from . import icons  # noqa: E402
from .emojipicker import EmojiPicker  # noqa: E402
from .model import (PALETTE, Arrow, Badge, Blur, Doc, Ellipse, Highlighter, Item,  # noqa: E402
                    Line, Pen, Pixelate, Rect, Redact, Sticker, Text, Tool, rgba)
from .overlay import as_layer  # noqa: E402
from .render import Renderer, measure_text  # noqa: E402

__all__ = ["Editor"]

#: Stroke-width multipliers behind the four size buttons.
SIZES = (0.6, 1.0, 1.7, 2.7)

#: (tool, icon, tooltip, key). Order is the order on the rail.
TOOLS = (
    (Tool.SELECT, "select", "Select and move", "v"),
    (Tool.ARROW, "arrow", "Arrow", "a"),
    (Tool.LINE, "line", "Line", "l"),
    (Tool.RECT, "rect", "Rectangle", "r"),
    (Tool.ELLIPSE, "ellipse", "Ellipse", "o"),
    (Tool.PEN, "pen", "Pen", "p"),
    (Tool.HIGHLIGHTER, "highlighter", "Highlighter", "h"),
    (Tool.TEXT, "text", "Text", "t"),
    (Tool.BADGE, "badge", "Numbered step", "n"),
    (Tool.BLUR, "blur", "Blur", "b"),
    (Tool.PIXELATE, "pixelate", "Pixelate", "x"),
    (Tool.REDACT, "redact", "Redact (solid bar)", "d"),
    (Tool.STICKER, "sticker", "Emoji", "e"),
)

#: Colour each tool starts with, as an index into PALETTE.
DEFAULT_COLOR = {Tool.HIGHLIGHTER: 2, Tool.REDACT: 8}

HANDLE_PX = 9.0  # screen pixels, whatever the zoom

CURSORS = {"nw": "nwse-resize", "se": "nwse-resize", "ne": "nesw-resize",
           "sw": "nesw-resize", "p0": "crosshair", "p1": "crosshair"}


class _Dot(Gtk.DrawingArea):
    """A filled circle for the size buttons, coloured by CSS like an icon."""

    def __init__(self, radius: float) -> None:
        super().__init__()
        self.radius = radius
        self.set_content_width(22)
        self.set_content_height(22)
        self.set_halign(Gtk.Align.CENTER)
        self.set_valign(Gtk.Align.CENTER)
        self.set_draw_func(self._draw)
        self.connect("state-flags-changed", lambda *_: self.queue_draw())

    def _draw(self, _area, ctx, width, height) -> None:
        color = self.get_color()
        ctx.set_source_rgba(color.red, color.green, color.blue, color.alpha)
        ctx.arc(width / 2, height / 2, self.radius, 0, 2 * math.pi)
        ctx.fill()


def _unfocusable(widget: Gtk.Widget) -> Gtk.Widget:
    """Buttons that keep the keyboard make Enter press *them* instead of saving."""
    widget.set_focusable(False)
    widget.set_focus_on_click(False)
    return widget


def _key_label(text: str) -> Gtk.Label:
    label = Gtk.Label(label=text)
    label.add_css_class("key")
    return label


def _button(text: str, key: str, css: str, callback: Callable) -> Gtk.Button:
    box = Gtk.Box(spacing=0)
    box.append(Gtk.Label(label=text))
    box.append(_key_label(key))
    button = _unfocusable(Gtk.Button())
    button.set_child(box)
    button.add_css_class(css)
    button.connect("clicked", lambda *_: callback())
    return button


class Editor(Gtk.Window):
    def __init__(self, app: Gtk.Application, *, on_save: Callable, on_close: Callable,
                 recents_path=None) -> None:
        super().__init__(application=app, title="magpie-shot-editor")
        self.add_css_class("shot-editor")
        self.set_decorated(False)
        self._on_save, self._on_close = on_save, on_close
        self.palette: Palette = read()

        # Per-picture state, set by open().
        self.doc = Doc(1, 1)
        self.renderer: Renderer | None = None
        self.scale = 1.0
        self.selected: Item | None = None
        self.editing: Item | None = None
        self._drag: tuple | None = None
        self._eat_release: set[int] = set()
        self.picker_open = False

        # Drawing state that outlives a picture.
        self.tool = Tool.ARROW
        self.color_index = 0
        self.tool_color: dict[Tool, int] = dict(DEFAULT_COLOR)
        self.size_index = 1
        self.fill = False

        as_layer(self, None)
        self._build(recents_path)

        keys = Gtk.EventControllerKey()
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._pressed)
        keys.connect("key-released", self._released)
        self.add_controller(keys)

    # -- building -----------------------------------------------------------

    def _build(self, recents_path) -> None:
        root = Gtk.Box()
        root.set_halign(Gtk.Align.CENTER)
        root.set_valign(Gtk.Align.CENTER)
        self.card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        self.card.add_css_class("card")
        self.card.set_overflow(Gtk.Overflow.HIDDEN)
        root.append(self.card)
        self.set_child(root)

        # Clicking the dimmed area around the card does nothing; it must not
        # fall through to the desktop either, and a layer surface that covers
        # the monitor already guarantees that.

        body = Gtk.Box()
        self.card.append(self._options())
        self.card.append(body)
        body.append(self._rail())

        self.canvas = Gtk.DrawingArea()
        self.canvas.set_draw_func(self._draw)
        self.canvas.set_halign(Gtk.Align.CENTER)
        self.canvas.set_valign(Gtk.Align.CENTER)
        self.canvas.add_css_class("canvas-frame")
        self.canvas.set_cursor_from_name("crosshair")

        self.overlay = Gtk.Overlay()
        self.overlay.set_child(self.canvas)
        self.overlay.set_halign(Gtk.Align.CENTER)
        self.overlay.set_valign(Gtk.Align.CENTER)
        self.wrap = Gtk.Box()
        self.wrap.add_css_class("canvas-wrap")
        self.wrap.set_hexpand(True)
        self.wrap.set_vexpand(True)
        self.wrap.append(self.overlay)
        body.append(self.wrap)

        self.card.append(self._footer())

        drag = Gtk.GestureDrag()
        drag.set_button(1)
        drag.connect("drag-begin", self._drag_begin)
        drag.connect("drag-update", self._drag_update)
        drag.connect("drag-end", self._drag_end)
        self.canvas.add_controller(drag)

        click = Gtk.GestureClick()
        click.set_button(1)
        click.connect("pressed", self._clicked)
        self.canvas.add_controller(click)

        motion = Gtk.EventControllerMotion()
        motion.connect("motion", self._hover)
        self.canvas.add_controller(motion)

        self._build_text_entry()
        self.picker = EmojiPicker(recents_path)
        self.picker.set_parent(self._tool_buttons[Tool.STICKER])
        self.picker.connect("picked", self._sticker_picked)
        self.picker.connect("closed", self._picker_closed)

    def _rail(self) -> Gtk.Widget:
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        rail.add_css_class("rail")
        self._tool_buttons: dict[Tool, Gtk.ToggleButton] = {}
        group = None
        for tool, icon, tip, key in TOOLS:
            button = _unfocusable(Gtk.ToggleButton())
            button.add_css_class("tool")
            button.set_child(icons.Icon(icon, 20))
            button.set_tooltip_text(f"{tip}  ({key.upper()})")
            if group is None:
                group = button
            else:
                button.set_group(group)
            button.connect("toggled", self._tool_toggled, tool)
            self._tool_buttons[tool] = button
            rail.append(button)

        spacer = Gtk.Box()
        spacer.set_vexpand(True)
        rail.append(spacer)
        self.undo_button = self._action("undo", "Undo  (Ctrl+Z)", self._undo)
        self.redo_button = self._action("redo", "Redo  (Ctrl+Shift+Z)", self._redo)
        self.delete_button = self._action("trash", "Delete selected  (Del)", self._delete)
        for b in (self.undo_button, self.redo_button, self.delete_button):
            rail.append(b)
        return rail

    def _action(self, icon: str, tip: str, callback: Callable) -> Gtk.Button:
        button = _unfocusable(Gtk.Button())
        button.add_css_class("action")
        button.set_child(icons.Icon(icon, 20))
        button.set_tooltip_text(tip)
        button.connect("clicked", lambda *_: callback())
        return button

    def _options(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=2)
        bar.add_css_class("toolbar")

        self.swatch_box = Gtk.Box(spacing=0)
        self._swatches: list[Gtk.ToggleButton] = []
        group = None
        for i, colour in enumerate(PALETTE):
            swatch = _unfocusable(Gtk.ToggleButton())
            swatch.add_css_class("swatch")
            swatch.add_css_class(f"sw{i}")
            swatch.set_tooltip_text(f"Colour {i + 1}  ({i + 1})")
            if group is None:
                group = swatch
            else:
                swatch.set_group(group)
            swatch.connect("toggled", self._swatch_toggled, i)
            self._swatches.append(swatch)
            self.swatch_box.append(swatch)
        bar.append(self.swatch_box)

        self.size_sep = self._sep()
        bar.append(self.size_sep)
        self.size_box = Gtk.Box(spacing=0)
        self._sizes: list[Gtk.ToggleButton] = []
        group = None
        for i, radius in enumerate((2.2, 3.6, 5.2, 7.4)):
            button = _unfocusable(Gtk.ToggleButton())
            button.add_css_class("size")
            button.set_child(_Dot(radius))
            button.set_tooltip_text("Size  ([ and ])")
            if group is None:
                group = button
            else:
                button.set_group(group)
            button.connect("toggled", self._size_toggled, i)
            self._sizes.append(button)
            self.size_box.append(button)
        bar.append(self.size_box)

        self.fill_sep = self._sep()
        bar.append(self.fill_sep)
        self.fill_button = _unfocusable(Gtk.ToggleButton())
        self.fill_button.add_css_class("tool")
        self.fill_button.set_child(icons.Icon("fill", 20))
        self.fill_button.set_tooltip_text("Filled  (F)")
        self.fill_button.connect("toggled", self._fill_toggled)
        bar.append(self.fill_button)
        return bar

    def _sep(self) -> Gtk.Widget:
        sep = Gtk.Box()
        sep.add_css_class("sep")
        return sep

    def _footer(self) -> Gtk.Widget:
        bar = Gtk.Box(spacing=10)
        bar.add_css_class("footer")
        self.info = Gtk.Label(xalign=0)
        self.info.add_css_class("info")
        self.info.set_hexpand(True)
        bar.append(self.info)
        bar.append(_button("Close", "Esc", "ghost", self.cancel))
        bar.append(_button("Save", "Enter", "cta", self.save))
        return bar

    def _build_text_entry(self) -> None:
        self.entry = Gtk.TextView()
        self.entry.add_css_class("annotation")
        self.entry.set_wrap_mode(Gtk.WrapMode.NONE)
        self.entry.set_halign(Gtk.Align.START)
        self.entry.set_valign(Gtk.Align.START)
        self.entry.set_visible(False)
        self.entry.set_accepts_tab(False)
        self.buffer = self.entry.get_buffer()
        self.tag = self.buffer.create_tag("all")
        self.buffer.connect("changed", self._text_changed)
        self.overlay.add_overlay(self.entry)

    # -- opening and closing ------------------------------------------------

    def open(self, image: cairo.ImageSurface, gdk_monitor, pixels_per_logical: float,
             destination: str = "") -> None:
        """Show `image` for editing on `gdk_monitor`. Nothing is saved until Enter."""
        from gi.repository import Gtk4LayerShell

        self.palette = read()
        Gtk4LayerShell.set_monitor(self, gdk_monitor)
        self.doc = Doc(image.get_width(), image.get_height())
        self.renderer = Renderer(image)
        self.selected = None
        self.editing = None
        self._drag = None
        self._eat_release.clear()
        self.entry.set_visible(False)

        geometry = gdk_monitor.get_geometry()
        # Room for the rail, the two bars, and a margin round the picture.
        avail_w = geometry.width * 0.92 - 64 - 56
        avail_h = geometry.height * 0.90 - 56 - 58 - 56
        natural = 1.0 / pixels_per_logical           # one image pixel = one device pixel
        fit = min(avail_w / self.doc.width, avail_h / self.doc.height)
        self.scale = min(fit, natural)
        if self.doc.width * self.scale < 420 < fit * self.doc.width:
            self.scale = min(fit, 420 / self.doc.width, natural * 3)
        width = max(1, round(self.doc.width * self.scale))
        height = max(1, round(self.doc.height * self.scale))
        self.scale = width / self.doc.width
        self.canvas.set_content_width(width)
        self.canvas.set_content_height(height)
        self.wrap.set_size_request(max(width + 56, 640), max(height + 56, 470))

        self.info.set_label(f"{self.doc.width} × {self.doc.height} px"
                            + (f"   ·   {destination}" if destination else ""))
        self._set_tool(Tool.ARROW if self.tool is Tool.SELECT else self.tool, force=True)
        self._refresh_actions()
        self.canvas.queue_draw()
        self.present()

    def save(self) -> None:
        self._finish_text()
        if self.renderer is None:
            return
        renderer, items = self.renderer, copy.deepcopy(self.doc.items)
        self._close()
        self._on_save(renderer, items)

    def cancel(self) -> None:
        self._finish_text(discard=True)
        self._close()
        self._on_close()

    def _close(self) -> None:
        self.picker.popdown()
        self.set_visible(False)
        self.renderer = None
        self.selected = self.editing = None

    # -- tool state ---------------------------------------------------------

    def _tool_toggled(self, button: Gtk.ToggleButton, tool: Tool) -> None:
        if button.get_active():
            self._set_tool(tool)

    def _set_tool(self, tool: Tool, force: bool = False) -> None:
        if tool is Tool.STICKER:
            # The emoji tool is a picker, not a mode: pick one and it lands on
            # the picture, ready to move.
            self._tool_buttons[self.tool].set_active(True)
            self._open_picker()
            return
        if tool is self.tool and not force:
            return
        self._finish_text()
        self.tool = tool
        self._tool_buttons[tool].set_active(True)
        if tool is not Tool.SELECT:
            self._select(None)
        self.color_index = self.tool_color.get(tool, self.color_index)
        self._swatches[self.color_index].set_active(True)
        self._sync_options()
        self.canvas.set_cursor_from_name("default" if tool is Tool.SELECT else "crosshair")

    def _sync_options(self) -> None:
        """Show only the controls that mean something for what is selected."""
        subject = self.selected.kind if self.selected else self.tool.value
        has_colour = subject not in ("blur", "pixelate", "select")
        has_size = subject not in ("redact", "select")
        has_fill = subject in ("rect", "ellipse")
        self.swatch_box.set_visible(has_colour)
        self.size_sep.set_visible(has_colour and has_size)
        self.size_box.set_visible(has_size)
        self.fill_sep.set_visible(has_fill)
        self.fill_button.set_visible(has_fill)
        if has_fill:
            self.fill_button.set_active(bool(getattr(self.selected, "fill", self.fill)))
        self._sizes[self.size_index].set_active(True)

    def _swatch_toggled(self, button: Gtk.ToggleButton, index: int) -> None:
        if not button.get_active():
            return
        changed = index != self.color_index
        self.color_index = index
        self.tool_color[self.tool] = index
        item = self.selected
        if (changed and item is not None and hasattr(item, "color")
                and not isinstance(item, (Blur, Pixelate))):
            self.doc.checkpoint()
            item.color = self._color()
            self._changed()

    def _size_toggled(self, button: Gtk.ToggleButton, index: int) -> None:
        if not button.get_active():
            return
        self.size_index = index
        if self.selected is not None:
            self.doc.checkpoint()
            self._apply_size(self.selected)
            self._changed()

    def _fill_toggled(self, button: Gtk.ToggleButton) -> None:
        self.fill = button.get_active()
        item = self.selected
        if item is not None and hasattr(item, "fill") and item.fill != self.fill:
            self.doc.checkpoint()
            item.fill = self.fill
            self._changed()

    def _color(self) -> tuple[float, float, float, float]:
        return rgba(PALETTE[self.color_index])

    def _factor(self) -> float:
        return SIZES[self.size_index]

    def _apply_size(self, item: Item) -> None:
        f, doc = self._factor(), self.doc
        if isinstance(item, (Arrow, Line, Rect, Ellipse, Pen, Highlighter)):
            item.width = doc.default_width() * f
        elif isinstance(item, Text):
            item.size = doc.default_text_size() * f
            measure_text(item)
        elif isinstance(item, Badge):
            item.radius = doc.badge_radius() * f
        elif isinstance(item, (Blur, Pixelate)):
            item.strength = max(6.0, max(doc.width, doc.height) / 90) * f
        elif isinstance(item, Sticker):
            item.size = doc.default_text_size() * 3.4 * f

    def _select(self, item: Item | None) -> None:
        self.selected = item
        if item is not None:
            color = getattr(item, "color", None)
            if color is not None and not isinstance(item, (Blur, Pixelate)):
                for i, hexcolor in enumerate(PALETTE):
                    if all(abs(a - b) < 0.01 for a, b in zip(rgba(hexcolor)[:3], color[:3])):
                        self.color_index = i
                        self._swatches[i].set_active(True)
                        break
        self._sync_options()
        self._refresh_actions()
        self.canvas.queue_draw()

    def _refresh_actions(self) -> None:
        self.undo_button.set_sensitive(self.doc.can_undo)
        self.redo_button.set_sensitive(self.doc.can_redo)
        self.delete_button.set_sensitive(self.selected is not None)

    def _changed(self) -> None:
        self._refresh_actions()
        self.canvas.queue_draw()

    # -- drawing ------------------------------------------------------------

    def _draw(self, _area, ctx: cairo.Context, width: int, height: int) -> None:
        if self.renderer is None:
            return
        scale = width / self.doc.width
        hide = self.editing.id if self.editing is not None else None
        self.renderer.paint(ctx, self.doc.items, scale, hide=hide)
        if self.selected is not None and self.selected is not self.editing:
            self._paint_selection(ctx, self.selected, scale)

    def _paint_selection(self, ctx: cairo.Context, item: Item, scale: float) -> None:
        r, g, b = (c / 255 for c in _rgb(self.palette.accent))
        handles = item.handles()
        linear = set(handles) == {"p0", "p1"}
        ctx.save()
        if not linear:
            x, y, w, h = item.bounds()
            ctx.set_dash([5, 4])
            ctx.set_line_width(1.2)
            ctx.set_source_rgba(1, 1, 1, 0.9)
            ctx.rectangle(x * scale, y * scale, w * scale, h * scale)
            ctx.stroke()
            ctx.set_dash([5, 4], 4.5)
            ctx.set_source_rgba(r, g, b, 1)
            ctx.rectangle(x * scale, y * scale, w * scale, h * scale)
            ctx.stroke()
        ctx.set_dash([])
        for hx, hy in handles.values():
            ctx.arc(hx * scale, hy * scale, HANDLE_PX / 2, 0, 2 * math.pi)
            ctx.set_source_rgba(1, 1, 1, 1)
            ctx.fill_preserve()
            ctx.set_source_rgba(r, g, b, 1)
            ctx.set_line_width(2)
            ctx.stroke()
        ctx.restore()

    # -- pointer ------------------------------------------------------------

    def _pos(self, x: float, y: float) -> tuple[float, float]:
        return x / self.scale, y / self.scale

    def _handle_at(self, item: Item | None, x: float, y: float) -> str | None:
        if item is None:
            return None
        reach = HANDLE_PX / self.scale
        for name, (hx, hy) in item.handles().items():
            if math.hypot(x - hx, y - hy) <= reach:
                return name
        return None

    def _hover(self, _controller, sx: float, sy: float) -> None:
        if self._drag is not None or self.renderer is None:
            return
        x, y = self._pos(sx, sy)
        name = self._handle_at(self.selected, x, y)
        if name:
            cursor = CURSORS.get(name, "default")
        elif self.tool is Tool.SELECT:
            cursor = "move" if self.doc.pick(x, y, 6 / self.scale) else "default"
        else:
            cursor = "crosshair"
        self.canvas.set_cursor_from_name(cursor)

    def _clicked(self, _gesture, n_press: int, sx: float, sy: float) -> None:
        if n_press != 2 or self.renderer is None:
            return
        item = self.doc.pick(*self._pos(sx, sy), 6 / self.scale)
        if isinstance(item, Text):
            self._edit_text(item)

    def _drag_begin(self, _gesture, sx: float, sy: float) -> None:
        if self.renderer is None:
            return
        self.canvas.grab_focus()
        self._finish_text()
        x, y = self._pos(sx, sy)

        name = self._handle_at(self.selected, x, y)
        if name is not None:
            self.doc.checkpoint()
            self._drag = ("handle", self.selected, name, x, y)
            return

        tool = self.tool
        if tool is Tool.SELECT:
            item = self.doc.pick(x, y, 6 / self.scale)
            self._select(item)
            if item is not None:
                self.doc.checkpoint()
                self.doc.raise_to_top(item.id)
                self._drag = ("move", item, x, y, False)
            return

        if tool is Tool.TEXT:
            existing = self.doc.pick(x, y, 6 / self.scale)
            if isinstance(existing, Text):
                self._edit_text(existing)
            else:
                self._new_text(x, y)
            return

        self.doc.checkpoint()
        item = self._make(tool, x, y)
        self.doc.add(item)
        self._select(item)
        if tool is Tool.BADGE:
            self._drag = ("placed", item, x, y)
        else:
            self._drag = ("draw", item, x, y)
        self.canvas.queue_draw()

    def _make(self, tool: Tool, x: float, y: float) -> Item:
        color, doc, f = self._color(), self.doc, self._factor()
        width = doc.default_width() * f
        if tool is Tool.ARROW:
            return Arrow(p0=(x, y), p1=(x, y), color=color, width=width)
        if tool is Tool.LINE:
            return Line(p0=(x, y), p1=(x, y), color=color, width=width)
        if tool is Tool.RECT:
            return Rect(p0=(x, y), p1=(x, y), color=color, width=width, fill=self.fill)
        if tool is Tool.ELLIPSE:
            return Ellipse(p0=(x, y), p1=(x, y), color=color, width=width, fill=self.fill)
        if tool is Tool.PEN:
            return Pen(points=[(x, y)], color=color, width=width)
        if tool is Tool.HIGHLIGHTER:
            return Highlighter(points=[(x, y)], color=color, width=width)
        if tool is Tool.BADGE:
            return Badge(x=x, y=y, n=doc.next_badge(), color=color, radius=doc.badge_radius() * f)
        strength = max(6.0, max(doc.width, doc.height) / 90) * f
        if tool is Tool.BLUR:
            return Blur(p0=(x, y), p1=(x, y), strength=strength)
        if tool is Tool.PIXELATE:
            return Pixelate(p0=(x, y), p1=(x, y), strength=strength)
        return Redact(p0=(x, y), p1=(x, y), color=color)

    def _drag_update(self, gesture, dx: float, dy: float) -> None:
        if self._drag is None:
            return
        _, sx, sy = gesture.get_start_point()
        x, y = self._pos(sx + dx, sy + dy)
        kind = self._drag[0]
        shift = bool(gesture.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK)

        if kind == "move":
            _, item, lx, ly, moved = self._drag
            item.translate(x - lx, y - ly)
            self._drag = ("move", item, x, y, moved or (x != lx or y != ly))
        elif kind == "handle":
            _, item, name, *_ = self._drag
            item.drag_handle(name, x, y, keep_ratio=shift)
            if isinstance(item, Text):
                measure_text(item)
        elif kind == "draw":
            item = self._drag[1]
            if isinstance(item, (Pen, Highlighter)):
                last = item.points[-1]
                if math.hypot(x - last[0], y - last[1]) * self.scale >= 1.5:
                    item.points.append((x, y))
            elif isinstance(item, (Arrow, Line)):
                item.drag_handle("p1", x, y, keep_ratio=shift)
            else:
                self._drag_box(item, x, y, shift)
        elif kind == "placed":
            # A badge follows the pointer until it is let go.
            _, item, lx, ly = self._drag
            item.translate(x - lx, y - ly)
            self._drag = ("placed", item, x, y)
        self.canvas.queue_draw()

    def _drag_box(self, item, x: float, y: float, shift: bool) -> None:
        """Rectangles and the regions: the corner you started at stays put."""
        start = self._drag[2], self._drag[3]
        if shift:
            side = max(abs(x - start[0]), abs(y - start[1]))
            x = start[0] + math.copysign(side, x - start[0] or 1)
            y = start[1] + math.copysign(side, y - start[1] or 1)
        item.p0, item.p1 = start, (x, y)

    def _drag_end(self, _gesture, _dx, _dy) -> None:
        drag, self._drag = self._drag, None
        if drag is None:
            return
        kind, item = drag[0], drag[1]
        if kind == "move" and not drag[4]:
            self.doc.discard_checkpoint()
        elif kind == "draw" and self._degenerate(item):
            self.doc.discard_checkpoint()
            self.doc.remove(item.id)
            self._select(None)
        self._refresh_actions()
        self.canvas.queue_draw()

    def _degenerate(self, item: Item) -> bool:
        reach = 4 / self.scale
        if isinstance(item, (Arrow, Line)):
            return item.length() < reach
        if isinstance(item, (Rect, Ellipse, Blur, Pixelate, Redact)):
            _, _, w, h = item.bounds()
            return w < reach and h < reach
        return False

    # -- text ---------------------------------------------------------------

    def _new_text(self, x: float, y: float) -> None:
        self.doc.checkpoint()
        item = Text(x=x, y=y, text="", color=self._color(),
                    size=self.doc.default_text_size() * self._factor())
        measure_text(item)
        self.doc.add(item)
        self._select(item)
        self._begin_editing(item, new=True)

    def _edit_text(self, item: Text) -> None:
        self.doc.checkpoint()
        self._select(item)
        self._begin_editing(item, new=False)

    def _begin_editing(self, item: Text, new: bool) -> None:
        self.editing = item
        self._editing_new = new
        self.buffer.set_text(item.text)
        self._style_entry(item)
        self.entry.set_margin_start(round(item.x * self.scale))
        self.entry.set_margin_top(round(item.y * self.scale))
        self.entry.set_visible(True)
        self.entry.grab_focus()
        self.buffer.place_cursor(self.buffer.get_end_iter())
        self.canvas.queue_draw()

    def _style_entry(self, item: Text) -> None:
        r, g, b, _ = item.color
        self.tag.set_property("font", f"IBM Plex Sans SemiBold {item.size * self.scale}px")
        rgba_ = Gdk.RGBA()
        rgba_.red, rgba_.green, rgba_.blue, rgba_.alpha = r, g, b, 1.0
        self.tag.set_property("foreground-rgba", rgba_)
        self.buffer.apply_tag(self.tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())

    def _text_changed(self, _buffer) -> None:
        if self.editing is None:
            return
        self.buffer.apply_tag(self.tag, self.buffer.get_start_iter(), self.buffer.get_end_iter())
        self.editing.text = self.buffer.get_text(self.buffer.get_start_iter(),
                                                 self.buffer.get_end_iter(), False)
        measure_text(self.editing)

    def _finish_text(self, discard: bool = False) -> None:
        item = self.editing
        if item is None:
            return
        self.editing = None
        self.entry.set_visible(False)
        item.text = item.text.rstrip("\n")
        if not item.text.strip():
            self.doc.discard_checkpoint()
            self.doc.remove(item.id)
            if self.selected is item:
                self.selected = None
        else:
            measure_text(item)
        self._sync_options()
        self._refresh_actions()
        self.canvas.queue_draw()

    # -- emoji --------------------------------------------------------------

    def _open_picker(self) -> None:
        self._finish_text()
        self.picker_open = True
        self.picker.popup()

    def _picker_closed(self, _popover) -> None:
        self.picker_open = False

    def _sticker_picked(self, _picker, surface, char: str, platform: str) -> None:
        self.picker.popdown()
        if self.renderer is None:
            return
        self.doc.checkpoint()
        size = self.doc.default_text_size() * 3.4 * self._factor()
        item = Sticker(x=self.doc.width / 2, y=self.doc.height / 2, size=size,
                       char=char, platform=platform, surface=surface)
        self.doc.add(item)
        self._tool_buttons[Tool.SELECT].set_active(True)
        self._select(item)

    # -- editing commands ---------------------------------------------------

    def _undo(self) -> None:
        self._finish_text()
        if self.doc.undo():
            self._after_history()

    def _redo(self) -> None:
        if self.doc.redo():
            self._after_history()

    def _after_history(self) -> None:
        # The restored objects are copies; the selection points at the old ones.
        if self.selected is not None and self.doc.get(self.selected.id) is None:
            self.selected = None
        elif self.selected is not None:
            self.selected = self.doc.get(self.selected.id)
        self._sync_options()
        self._changed()

    def _delete(self) -> None:
        if self.selected is None:
            return
        self.doc.checkpoint()
        self.doc.remove(self.selected.id)
        self._select(None)

    # -- keys ---------------------------------------------------------------

    def _pressed(self, _c, keyval, _code, state) -> bool:
        ctrl = bool(state & Gdk.ModifierType.CONTROL_MASK)
        shift = bool(state & Gdk.ModifierType.SHIFT_MASK)

        if self.picker_open:
            if keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
                self._eat_release.add(keyval)
            return False  # the picker's own search box takes the typing

        if self.editing is not None:
            if keyval == Gdk.KEY_Escape or (
                    keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and not shift):
                # Finishing the text is not the same as saving or closing: eat
                # the release too, or it would do one of them.
                self._eat_release.add(keyval)
                self._finish_text()
                return True
            return False

        if keyval in (Gdk.KEY_Escape, Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            return True  # acted on at the release

        if ctrl and keyval in (Gdk.KEY_z, Gdk.KEY_Z):
            (self._redo if shift else self._undo)()
            return True
        if ctrl and keyval in (Gdk.KEY_y, Gdk.KEY_Y):
            self._redo()
            return True
        if keyval in (Gdk.KEY_Delete, Gdk.KEY_BackSpace):
            self._delete()
            return True
        if keyval in (Gdk.KEY_bracketleft, Gdk.KEY_bracketright):
            step = -1 if keyval == Gdk.KEY_bracketleft else 1
            self._sizes[max(0, min(3, self.size_index + step))].set_active(True)
            return True
        if Gdk.KEY_1 <= keyval <= Gdk.KEY_9 and not ctrl:
            self._swatches[keyval - Gdk.KEY_1].set_active(True)
            return True
        if keyval in (Gdk.KEY_Left, Gdk.KEY_Right, Gdk.KEY_Up, Gdk.KEY_Down) and self.selected:
            step = (10 if shift else 1)
            dx = {Gdk.KEY_Left: -step, Gdk.KEY_Right: step}.get(keyval, 0)
            dy = {Gdk.KEY_Up: -step, Gdk.KEY_Down: step}.get(keyval, 0)
            self.doc.checkpoint()
            self.selected.translate(dx, dy)
            self._changed()
            return True
        if not ctrl:
            name = Gdk.keyval_name(keyval) or ""
            if name.lower() == "f" and self.fill_button.get_visible():
                self.fill_button.set_active(not self.fill_button.get_active())
                return True
            for tool, _icon, _tip, key in TOOLS:
                if name.lower() == key:
                    self._set_tool(tool)
                    return True
        return False

    def _released(self, _c, keyval, _code, _state) -> bool:
        if keyval in self._eat_release:
            self._eat_release.discard(keyval)
            return True
        if self.editing is not None or self.picker_open:
            return False
        if keyval == Gdk.KEY_Escape:
            GLib.idle_add(self.cancel)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            GLib.idle_add(self.save)
            return True
        return False
