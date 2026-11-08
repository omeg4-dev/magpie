"""One screenshot, from the key press to the file.

This is the conductor. It lives inside the resident magpie process — the same
one that holds the clipboard window — which is the whole reason a screenshot
appears the instant the key goes down: nothing starts, nothing is imported,
no toolkit is initialised. The picture is grabbed, shown frozen, cropped and
handed to the editor, all by objects that were built at login and have been
sitting hidden ever since.

The order is deliberate. Everything that has to be right is done while the
screen is still frozen (the grab); everything slow (encoding, writing, the
clipboard, the index, the notification) happens after the editor has gone,
on a thread, so that Enter is never a pause.
"""

from __future__ import annotations

import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib  # noqa: E402

from ..config import load  # noqa: E402
from ..store import Store  # noqa: E402
from . import grab, output, style  # noqa: E402

__all__ = ["Session", "MODES"]

MODES = ("region", "monitor", "all")


class Session:
    def __init__(self, app) -> None:
        self.app = app
        self.state = "idle"             # idle | grabbing | overlay | editor
        self.editor = None
        self.overlays: dict[str, object] = {}
        self.shots: list[tuple[grab.Monitor, object, object]] = []  # monitor, PIL image, surface
        style.apply()
        style.watch()
        # An output that is switched off and on (or unplugged) comes back as a new
        # Gdk.Monitor under the same connector name; the overlay that was bound to
        # the old one would then land on whichever output the compositor likes.
        Gdk.Display.get_default().get_monitors().connect(
            "items-changed", lambda *_a: GLib.idle_add(self._monitors_changed))

    # -- the way in ---------------------------------------------------------

    def warm(self) -> bool:
        """Build the windows now, hidden, so the first key press is as fast as the rest."""
        try:
            self._editor()
            for mon in self._gdk_monitors():
                self._overlay(mon)
        except Exception:  # pragma: no cover - never let this stop the clipboard
            traceback.print_exc()
        return GLib.SOURCE_REMOVE

    def trigger(self, spec: str) -> None:
        """`region`, `monitor` or `all`; `monitor:now` saves without the editor."""
        mode, _, flag = (spec or "region").partition(":")
        if mode not in MODES:
            mode = "region"
        if self.state == "editor" and not (self.editor and self.editor.get_visible()):
            self.state = "idle"     # never let a stuck state lock the key
        if self.state == "overlay":
            self._abandon()     # the key again closes what the key opened
            return
        if self.state != "idle":
            return
        self.state = "grabbing"
        try:
            monitors = grab.monitors()
            focused = grab.focused_monitor(monitors)
            if mode == "region":
                self._region(monitors, focused)
            elif mode == "monitor":
                self._whole(grab.grab_monitor(focused), focused, flag == "now")
            else:
                self._whole(grab.grab_all(), focused, flag == "now")
        except Exception as error:
            self.state = "idle"
            traceback.print_exc()
            _notify_error("Screenshot failed", str(error))

    # -- region -------------------------------------------------------------

    def _region(self, monitors: list, focused) -> None:
        with ThreadPoolExecutor(max_workers=len(monitors) or 1) as pool:
            grabbed = list(pool.map(self._grab_one, monitors))
        self.shots = grabbed
        self.state = "overlay"
        for index, (mon, _img, surface) in enumerate(grabbed):
            gdk = self._gdk_monitor(mon.name)
            if gdk is None:
                continue
            overlay = self._overlay(gdk)
            overlay.arm(surface, index)
            overlay.present()

    @staticmethod
    def _grab_one(mon):
        image = grab.grab_monitor(mon)
        return mon, image, grab.to_surface(image)

    def _on_region(self, index: int, box: tuple[int, int, int, int]) -> None:
        mon, image, _surface = self.shots[index]
        crop = image.crop(box)
        self._hide_overlays()
        self._edit(grab.to_surface(crop), mon)

    def _on_whole(self, index: int) -> None:
        # Enter with nothing selected: the screen the pointer is on.
        for i, (mon, _img, _surface) in enumerate(self.shots):
            overlay = self.overlays.get(mon.name)
            if overlay is not None and overlay.pointer is not None:
                index = i
        mon, image, surface = self.shots[index]
        self._hide_overlays()
        self._edit(surface, mon)

    def _abandon(self) -> None:
        self._hide_overlays()
        self.state = "idle"

    def _hide_overlays(self) -> None:
        for overlay in self.overlays.values():
            overlay.disarm()

    # -- editing ------------------------------------------------------------

    def _whole(self, image, mon, now: bool) -> None:
        if now:
            self.state = "idle"
            self._deliver_png_async(lambda: _png(image))
            return
        self._edit(grab.to_surface(image), mon)

    def _edit(self, surface, mon: grab.Monitor) -> None:
        try:
            self._open_editor(surface, mon)
        except Exception as error:
            self.state = "idle"
            traceback.print_exc()
            _notify_error("Screenshot failed", str(error))

    def _open_editor(self, surface, mon: grab.Monitor) -> None:
        gdk = self._gdk_monitor(mon.name) or self._gdk_monitors()[0]
        config = load()
        path, fell_back = output.target_path(datetime.now(), root=config.shots_root,
                                             fallback=config.shots_fallback)
        where = f"saves to {path.parent.name}" + ("  (drive missing: Pictures)" if fell_back else "")
        self.state = "editor"
        self._editor().open(surface, gdk, mon.pixel_width / max(1, mon.width), where)

    def _editor(self):
        if self.editor is None:
            from .editor import Editor

            self.editor = Editor(self.app, on_save=self._on_save, on_close=self._on_close)
        return self.editor

    def _on_close(self) -> None:
        self.state = "idle"

    def _on_save(self, renderer, items) -> None:
        self.state = "idle"
        self._deliver_png_async(lambda: renderer.export_png(items))

    # -- delivery (never on the UI thread) ----------------------------------

    def _deliver_png_async(self, make_png: Callable[[], bytes]) -> None:
        threading.Thread(target=self._deliver, args=(make_png,), daemon=True).start()

    def _deliver(self, make_png: Callable[[], bytes]) -> None:
        try:
            png = make_png()
            config = load()
            quiet = bool(os.environ.get("MAGPIE_CONFIG"))   # a demo or a test: no noise
            store = Store(config.store)
            try:
                saved = output.deliver(
                    png, store, root=config.shots_root, fallback=config.shots_fallback)
            finally:
                store.db.close()
            if not quiet:
                output.notify(saved)
        except Exception as error:
            traceback.print_exc()
            _notify_error("Screenshot not saved cleanly", str(error))

    # -- monitors -----------------------------------------------------------

    @staticmethod
    def _gdk_monitors() -> list[Gdk.Monitor]:
        model = Gdk.Display.get_default().get_monitors()
        return [model.get_item(i) for i in range(model.get_n_items())]

    def _gdk_monitor(self, name: str):
        return next((m for m in self._gdk_monitors() if m.get_connector() == name), None)

    def _monitors_changed(self) -> bool:
        """Drop overlays that belong to a monitor that is gone, then rebuild them hidden."""
        if self.state == "overlay":
            self._abandon()
        self._prune_overlays()
        self.warm()
        return GLib.SOURCE_REMOVE

    def _prune_overlays(self) -> None:
        current = {m.get_connector(): m for m in self._gdk_monitors()}
        for name, overlay in list(self.overlays.items()):
            if current.get(name) is not overlay.gdk_monitor:
                del self.overlays[name]
                overlay.destroy()

    def _overlay(self, gdk_monitor):
        from .overlay import RegionOverlay

        name = gdk_monitor.get_connector()
        overlay = self.overlays.get(name)
        if overlay is not None and overlay.gdk_monitor is not gdk_monitor:
            del self.overlays[name]     # bound to a monitor that no longer exists
            overlay.destroy()
            overlay = None
        if overlay is None:
            overlay = RegionOverlay(self.app, gdk_monitor, on_region=self._on_region,
                                    on_whole=self._on_whole, on_cancel=self._abandon)
            self.overlays[name] = overlay
        return overlay


def _notify_error(title: str, body: str) -> None:
    import subprocess

    try:
        subprocess.Popen(["notify-send", "-a", "Screenshot", "-u", "critical",
                          "-i", "dialog-error", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


def _png(image) -> bytes:
    import io

    out = io.BytesIO()
    image.save(out, "PNG")
    return out.getvalue()
