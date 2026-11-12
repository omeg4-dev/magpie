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

import os

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")

from gi.repository import Gdk, Gio, GLib, Gtk  # noqa: E402

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
        # A second `magpie view` normally activates the window that is
        # already running -- which is right for a clipboard bound to a
        # single key, and wrong when MAGPIE_CONFIG has deliberately pointed
        # this process at a different store: the running instance would
        # answer, holding the real clipboard, and the sandbox would be
        # silently ignored. So a sandboxed viewer takes its own identity.
        sandboxed = bool(os.environ.get("MAGPIE_CONFIG"))
        super().__init__(
            application_id=None if sandboxed else APP_ID,
            flags=(Gio.ApplicationFlags.HANDLES_COMMAND_LINE
                   | (Gio.ApplicationFlags.NON_UNIQUE if sandboxed
                      else Gio.ApplicationFlags.DEFAULT_FLAGS)))
        self._window: Window | None = None
        self._held = False
        self._warming = False
        self.connect("command-line", self._on_command_line)

    def do_startup(self) -> None:
        Gtk.Application.do_startup(self)
        if Gdk.Display.get_default() is None:
            # Started before the compositor was up (a login service can be).
            # Exit *non-zero*: a clean exit is not restarted, and a resident
            # process that quietly is not resident is why Super+V felt slow.
            print("magpie: no display yet", file=sys.stderr)
            sys.stderr.flush()
            os._exit(1)    # not sys.exit: SystemExit inside a GLib callback is swallowed
        style.apply()
        # The window is open for the life of the session, and the wallpaper is
        # not: Noctalia rewrites the palette and this follows it.
        style.watch()
        self.store = Store(load().store)
        self._start_shot()
        self._start_view()

    def _start_view(self) -> None:
        """`view` as a D-Bus action, so the key is a ~10 ms message, not a new Python."""
        action = Gio.SimpleAction.new("view", GLib.VariantType.new("s"))
        action.connect("activate", self._on_view_action)
        self.add_action(action)

    def _on_view_action(self, _action, mode) -> None:
        if not self._held:
            self._held = True
            self.hold()
        wanted = mode.get_string() if mode is not None else ""
        self._present(hidden=False, mode=wanted if wanted in _modes() else None)

    def _start_shot(self) -> None:
        """The screenshot tool, in this process so a keypress finds it running.

        Isolated: if it cannot start, the clipboard must still work.
        """
        self.shot = None
        try:
            from ..shot.session import Session

            self.shot = Session(self)
            action = Gio.SimpleAction.new("shot", GLib.VariantType.new("s"))
            action.connect("activate", lambda _a, mode: self.shot.trigger(mode.get_string()))
            self.add_action(action)
            GLib.idle_add(self.shot.warm)
        except Exception:  # pragma: no cover - depends on the machine
            import traceback

            traceback.print_exc()

    def _on_command_line(self, _app, command_line) -> int:
        # Every invocation after the first arrives here rather than starting a
        # new process. That is the whole point of the single instance.
        argv = command_line.get_arguments()
        if argv[1:2] == ["shot"]:
            if self.shot is not None:
                if not self._held:
                    self._held = True
                    self.hold()  # a screenshot process stays up for the next key
                self.shot.trigger(argv[2] if len(argv) > 2 else "region")
            return 0
        self._present(hidden="--hidden" in argv, mode=_mode_from(argv))
        return 0

    def _present(self, hidden: bool, mode: str | None = None) -> None:
        if self._window is None:
            self._window = Window(self, self.store)
            _as_layer(self._window)
            self._window.connect("close-request", self._on_close)
        if hidden:
            self.hold()  # nothing on screen, but stay alive for the next press
            self._window.rest()
            GLib.idle_add(self._warm)
            return
        if self._warming:       # a real opening beats the warm-up: see _warm
            self._warming = False
            if Gtk4LayerShell is not None:
                Gtk4LayerShell.set_keyboard_mode(
                    self._window, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        # `--mode screenshots` opens straight into the browser, so a key of its
        # own can go there without passing through the clipboard first.
        # Everything the opening does — refreshing, drawing, taking the
        # keyboard, the sound — is in `Window.open_at`, which does each of them
        # exactly once.
        self._window.open_at(mode or "clipboard")

    def _warm(self) -> bool:
        """Map the window once, invisibly, so the first Super+V is as quick as the rest.

        Building the widgets is not what the first press pays for; creating the
        layer surface and the renderer's first frame is, and that cannot happen
        without being on screen. So it happens here: transparent, taking no
        keys, for a quarter of a second, at login.
        """
        w = self._window
        if w is None or w.get_visible() or Gtk4LayerShell is None:
            return GLib.SOURCE_REMOVE
        self._warming = True
        Gtk4LayerShell.set_keyboard_mode(w, Gtk4LayerShell.KeyboardMode.NONE)
        w.set_opacity(0.0)
        w.present()
        # GTK builds a couple of hundred rows the first time a view is shown,
        # and that is most of what the first switch to the grid cost. Show
        # each view once now, while nobody can see it.
        for at, mode in enumerate(("grid", "starred", "screenshots", "clipboard")):
            GLib.timeout_add(120 + 130 * at, self._warm_mode, mode)
        GLib.timeout_add(120 + 130 * 4 + 120, self._warm_done)
        return GLib.SOURCE_REMOVE

    def _warm_mode(self, mode: str) -> bool:
        if self._warming and self._window is not None:
            self._window.set_mode(mode)
        return GLib.SOURCE_REMOVE

    def _warm_done(self) -> bool:
        w = self._window
        if self._warming and w is not None:
            self._warming = False
            w.set_visible(False)
            w.set_opacity(1.0)
            Gtk4LayerShell.set_keyboard_mode(w, Gtk4LayerShell.KeyboardMode.EXCLUSIVE)
        return GLib.SOURCE_REMOVE

    def _on_close(self, window) -> bool:
        """Closing hides the window; the process stays for the next Super+V."""
        window.set_visible(False)
        self.hold()
        window.rest()   # while nobody is looking: ready for the next Super+V
        return True


def _modes() -> tuple:
    from ..browse import Browse

    return tuple(Browse.MODES)


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
