"""The process the window lives in.

Two things make Super+V feel instant rather than like launching a program.

**One instance.** The second `magpie view` hands its request to the one already
running and exits; the window it built at login is simply shown. Starting GTK
and opening a store takes about half a second, and paying that on every keypress
would be the first thing you noticed about this program.

**A layer-shell surface**, not a floating toplevel. No border, no titlebar, no
open-animation, no place in the window stack to fight over — it appears where it
is put, takes the keyboard, and goes away again. It is a part of the desktop,
in the same sense the bar is.

Run `magpie view --hidden` from a login service to build the window once.
"""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gio, Gtk  # noqa: E402

from ..config import load  # noqa: E402
from ..store import Store  # noqa: E402
from . import style  # noqa: E402
from .window import Window  # noqa: E402

__all__ = ["run"]

APP_ID = "dev.omega.Magpie"

#: The namespace the compositor sees, so `layerrule` can find it.
NAMESPACE = "magpie"

try:
    gi.require_version("Gtk4LayerShell", "1.0")
    from gi.repository import Gtk4LayerShell
except (ValueError, ImportError):  # pragma: no cover - depends on the machine
    Gtk4LayerShell = None


class MagpieApp(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id=APP_ID,
                         flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._window: Window | None = None
        self.connect("command-line", self._on_command_line)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        style.apply()
        self.store = Store(load().store)

    def _on_command_line(self, _app, command_line) -> int:
        # Every invocation after the first arrives here rather than starting a
        # new process. That is the whole point of the single instance.
        argv = command_line.get_arguments()
        self._present(hidden="--hidden" in argv, mode=_mode_from(argv))
        return 0

    def _present(self, hidden: bool, mode: str | None = None) -> None:
        if self._window is None:
            self._window = Window(self, self.store)
            _as_layer(self._window)
            self._window.connect("close-request", self._on_close)
        if hidden:
            self.hold()  # nothing on screen, but stay alive for the next press
            return
        # `--mode screenshots` opens straight into the browser, so a key of its
        # own can go there without passing through the clipboard first.
        # Everything the opening does — refreshing, drawing, taking the
        # keyboard, the sound — is in `Window.open_at`, which does each of them
        # exactly once.
        self._window.open_at(mode or "clipboard")

    def _on_close(self, window) -> bool:
        """Closing hides the window; the process stays for the next Super+V."""
        window.set_visible(False)
        self.hold()
        return True


def _mode_from(argv: list[str]) -> str | None:
    """`--mode <name>`, if it is there and is a mode."""
    from ..browse import Browse

    if "--mode" in argv:
        at = argv.index("--mode") + 1
        if at < len(argv) and argv[at] in Browse.MODES:
            return argv[at]
    return None


def _as_layer(window: Gtk.Window) -> None:
    """Make this an overlay surface the compositor owns."""
    if Gtk4LayerShell is None:  # pragma: no cover - depends on the machine
        return
    Gtk4LayerShell.init_for_window(window)
    Gtk4LayerShell.set_namespace(window, NAMESPACE)
    Gtk4LayerShell.set_layer(window, Gtk4LayerShell.Layer.OVERLAY)
    # Exclusive, so the keyboard is ours the moment it appears and typing does
    # not go to whatever was underneath.
    Gtk4LayerShell.set_keyboard_mode(window, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)


def run(argv: list[str] | None = None) -> int:
    return MagpieApp().run(sys.argv if argv is None else argv)
