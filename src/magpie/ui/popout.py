"""An image on its own, in a window with nothing else in it.

No header bar, no buttons, no padding — the picture is the window, and you
resize it by dragging its corner like any other. It is for looking at something
properly, which the preview pane beside a list cannot do.

Escape closes it. Dragging anywhere inside moves it, because there is no title
bar to grab.
"""

from __future__ import annotations

from gi.repository import Gdk, Gtk

__all__ = ["popout"]

#: The window opens at the image's own size, within reason.
MAX_W, MAX_H = 1600, 1000
MIN = 220


def popout(entry, texture: Gdk.Texture, parent: Gtk.Window | None = None) -> Gtk.Window:
    window = Gtk.Window(title=_title(entry))
    window.add_css_class("popout")
    window.set_decorated(False)
    window.set_resizable(True)
    window.set_default_size(*_size(texture))

    picture = Gtk.Picture.new_for_paintable(texture)
    picture.set_can_shrink(True)
    picture.set_content_fit(Gtk.ContentFit.CONTAIN)
    window.set_child(picture)

    _close_on_escape(window)
    _drag_to_move(window)
    window.present()
    return window


def _title(entry) -> str:
    """Shown nowhere on screen, but it is what a window switcher will say."""
    return entry.preview or "Image"


def _size(texture: Gdk.Texture) -> tuple[int, int]:
    width, height = texture.get_width(), texture.get_height()
    scale = min(MAX_W / width, MAX_H / height, 1.0)
    return max(MIN, round(width * scale)), max(MIN, round(height * scale))


def _close_on_escape(window: Gtk.Window) -> None:
    keys = Gtk.EventControllerKey()

    def pressed(_controller, keyval, _code, _state):
        if keyval == Gdk.KEY_Escape:
            window.close()
            return True
        return False

    keys.connect("key-pressed", pressed)
    window.add_controller(keys)


def _drag_to_move(window: Gtk.Window) -> None:
    """There is no title bar, so the picture itself is the handle."""
    drag = Gtk.GestureDrag()

    def begin(gesture, _x, _y):
        surface = window.get_surface()
        if isinstance(surface, Gdk.Toplevel):
            sequence = gesture.get_current_sequence()
            event = gesture.get_last_event(sequence)
            device = gesture.get_device()
            if event is not None and device is not None:
                x, y = gesture.get_start_point()[1:]
                surface.begin_move(device, gesture.get_current_button(),
                                   x, y, event.get_time())

    drag.connect("drag-begin", begin)
    window.add_controller(drag)
