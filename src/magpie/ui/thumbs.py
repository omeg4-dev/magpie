"""Thumbnails, cheaply.

The gallery scrolls over thousands of images, so nothing is loaded until it is
on screen and nothing is decoded twice. GTK's GridView only ever builds the
rows you can see, which does most of the work; this adds the memory so that
scrolling back up is instant.

Nothing here decodes a picture on the thread that draws the window. A request
goes to a small pool of workers, which first look in a cache of thumbnails on
disk (a few hundred bytes of JPEG against a screenshot that takes tens of
milliseconds to decode) and only then open the original; the finished pixels
come back to the main thread, which just wraps them in a texture. A second,
single worker makes the thumbnails for what is *about* to be on screen, so
that the first time you open a tab they are mostly already there.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from gi.repository import Gdk, GdkPixbuf, GLib

from . import thumbwork

__all__ = ["Thumbs"]

#: Textures held after they scroll away. A few hundred small ones cost little
#: and make the way back up the list free.
KEEP = 600

#: Previews are whole screens, so only a handful are worth keeping — but a
#: handful is enough for arrowing back and forth between two of them.
KEEP_PREVIEWS = 12

#: The biggest a preview is ever decoded at. Nothing in this window is shown
#: larger than this, and decoding a 4K screenshot to full size to display it
#: at 600 pixels is most of the pause you feel when you press Down.
PREVIEW_SIZE = 1400

#: Enough of a file for its header. Every format worth showing puts its size
#: in the first few bytes.
HEADER = 65_536


#: Workers that make what is on screen right now, and how many things the
#: look-ahead may have queued at once.
WORKERS = 3
AHEAD_MAX = 120

Wanted = Callable[[], bool]


class Thumbs:
    def __init__(self, store, cache: Path | None = None) -> None:
        self._store = store
        self._root = cache if cache is not None else thumbwork.cache_dir()
        self._stamps: dict[tuple, Gdk.Texture | None] = {}
        self._previews: dict[int, Gdk.Texture | None] = {}
        self._sizes: dict[int, tuple[int, int] | None] = {}
        self._now = ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix="thumb")
        self._ahead = ThreadPoolExecutor(max_workers=1, thread_name_prefix="thumb-ahead")
        # key -> who is waiting for it. Touched only on the main thread, except
        # that a worker may read it to see whether anyone still cares.
        self._waiting: dict[tuple, list[tuple[Callable, Wanted]]] = {}
        self._queued_ahead = 0
        self._lock = threading.Lock()

    # -- asking, without waiting -------------------------------------------

    def want(self, entry, width: int, height: int, callback: Callable,
             current: Wanted = lambda: True) -> None:
        """Have `callback(texture)` called when this thumbnail exists.

        Called straight away if it is already in memory. `current` is asked
        before the work is done and again before the answer is delivered: a row
        that has been recycled for another entry by then does not want this
        one, and nothing is spent on it.
        """
        key = (entry.id, width, height)
        if key in self._stamps:
            callback(self._stamps[key])
            return
        if key in self._waiting:
            self._waiting[key].append((callback, current))
            return
        self._waiting[key] = [(callback, current)]
        self._now.submit(self._make, key, entry, width, height)

    def look_ahead(self, entries, width: int, height: int) -> None:
        """Make these thumbnails in the background, for whoever opens the tab next."""
        for entry in entries:
            key = (entry.id, width, height)
            if not entry.is_image or key in self._stamps or key in self._waiting:
                continue
            if self._queued_ahead >= AHEAD_MAX:
                return
            self._queued_ahead += 1
            self._waiting[key] = []
            self._ahead.submit(self._make, key, entry, width, height, True)

    def _make(self, key, entry, width: int, height: int, ahead: bool = False) -> None:
        """Worker thread. No widgets, no textures, no store: files and pixels."""
        try:
            if not ahead and not any(cur() for _cb, cur in list(self._waiting.get(key, ()))):
                raw = False     # everyone who asked has moved on: do nothing
            else:
                raw = thumbwork.load_cached(self._root, entry.sha256, width, height)
                if raw is None:
                    raw = thumbwork.stamp(self._store.payload(entry), width, height)
                    if raw is not None:
                        thumbwork.store_cached(self._root, entry.sha256, raw)
        except OSError:
            raw = None
        GLib.idle_add(self._arrived, key, raw, ahead, priority=GLib.PRIORITY_DEFAULT_IDLE)

    def _arrived(self, key, raw, ahead: bool) -> bool:
        """Main thread: wrap the pixels, remember them, tell whoever is waiting."""
        if ahead:
            self._queued_ahead = max(0, self._queued_ahead - 1)
        waiting = self._waiting.pop(key, [])
        if raw is False:
            # Skipped as unwanted. Anyone who asked since is asked again.
            for callback, current in waiting:
                if current():
                    self.want_again(key, callback, current)
            return GLib.SOURCE_REMOVE
        texture = _texture(raw) if raw is not None else None
        _trim(self._stamps, KEEP)
        self._stamps[key] = texture
        for callback, current in waiting:
            if current():
                callback(texture)
        return GLib.SOURCE_REMOVE

    def want_again(self, key, callback, current) -> None:
        # Only reached for a request that was dropped as unwanted and then
        # wanted after all: rare, and cheap to do properly.
        self._waiting[key] = [(callback, current)]
        entry_id, width, height = key
        entry = self._store.get(entry_id)
        if entry is not None:
            self._now.submit(self._make, key, entry, width, height)
        else:
            self._waiting.pop(key, None)

    def want_preview(self, entry, callback: Callable, current: Wanted = lambda: True) -> None:
        """Have `callback(texture)` called with the detail-pane picture, off the UI thread."""
        if entry.id in self._previews:
            callback(self._previews[entry.id])
            return

        def work() -> None:
            try:
                raw = thumbwork.preview(self._store.payload(entry), PREVIEW_SIZE) \
                    if current() else False
            except OSError:
                raw = None
            GLib.idle_add(arrived, raw)

        def arrived(raw) -> bool:
            if raw is False:
                return GLib.SOURCE_REMOVE
            texture = _texture(raw) if raw is not None else None
            _trim(self._previews, KEEP_PREVIEWS)
            self._previews[entry.id] = texture
            if current():
                callback(texture)
            return GLib.SOURCE_REMOVE

        self._now.submit(work)

    def dimensions(self, entry) -> tuple[int, int] | None:
        """How big the picture really is, without decoding all of it.

        The preview is decoded no larger than it is shown, so its texture
        cannot answer this — and "1920 × 1080" is the first thing anyone wants
        to know about a screenshot.
        """
        if entry.id not in self._sizes:
            self._sizes[entry.id] = self._measure(entry)
        return self._sizes[entry.id]

    def known_dimensions(self, entry) -> tuple[int, int] | None:
        """The size if it has been measured already; never measures."""
        return self._sizes.get(entry.id)

    def measure_soon(self, entry, callback: Callable, current: Wanted = lambda: True) -> None:
        """Measure on a worker and call `callback()` when it is known.

        Reading a header is free from a warm file and a hundred milliseconds
        from a cold disk, and the second is not a thing to do on the thread
        that draws the window.
        """
        if entry.id in self._sizes:
            callback()
            return

        def work() -> None:
            size = self._measure(entry) if current() else False
            GLib.idle_add(arrived, size)

        def arrived(size) -> bool:
            if size is not False:
                self._sizes[entry.id] = size
                if current():
                    callback()
            return GLib.SOURCE_REMOVE

        self._now.submit(work)

    def _measure(self, entry) -> tuple[int, int] | None:
        if entry.path:
            # Reads the header and stops. Free, next to opening the file.
            info = GdkPixbuf.Pixbuf.get_file_info(entry.path)
            if info and info[0] is not None:
                return (info[1], info[2])
            return None
        try:
            # Only the header: reading all of a multi-megabyte blob to learn
            # its width was done on the thread that draws the window.
            data = self._store.payload_head(entry, HEADER)
        except OSError:
            return None
        found: list[tuple[int, int]] = []
        loader = GdkPixbuf.PixbufLoader()
        loader.connect("size-prepared", lambda _l, w, h: found.append((w, h)))
        try:
            # The header is in the first few kilobytes; closing on a truncated
            # file raises, which is exactly what we want it to do.
            loader.write(data[:HEADER])
            loader.close()
        except GLib.Error:
            pass
        return found[0] if found else None

    def preview(self, entry) -> Gdk.Texture | None:
        """The image for the detail pane, decoded no larger than it is shown."""
        if entry.id in self._previews:
            return self._previews[entry.id]
        _trim(self._previews, KEEP_PREVIEWS)
        texture = self._load(entry, PREVIEW_SIZE)
        self._previews[entry.id] = texture
        return texture

    def cached(self, entry, width: int, height: int) -> Gdk.Texture | None:
        """The stamp if it is already decoded, without decoding one if not.

        A view binds two hundred rows before it paints, and eight milliseconds
        of PNG each is most of a second of nothing on screen. Callers ask this
        first, draw what they have, and come back for the rest out of the way.
        """
        return self._stamps.get((entry.id, width, height))

    def stamp(self, entry, width: int, height: int) -> Gdk.Texture | None:
        """A texture cropped to exactly this size, for a row's little picture.

        Cropped rather than fitted because GTK reports a Picture's natural size
        from its paintable: a fitted thumbnail makes the row as wide as the
        screenshot was, and a column of rows each a different width is not a
        column. Exact bytes in, exact box out.
        """
        key = (entry.id, width, height)
        if key in self._stamps:
            return self._stamps[key]
        _trim(self._stamps, KEEP)
        texture = self._crop(entry, width, height)
        self._stamps[key] = texture
        return texture

    def _crop(self, entry, width: int, height: int) -> Gdk.Texture | None:
        pixbuf = self._pixbuf(entry, max(width, height) * 2)
        if pixbuf is None:
            return None
        scale = max(width / pixbuf.get_width(), height / pixbuf.get_height())
        wide = max(width, round(pixbuf.get_width() * scale))
        tall = max(height, round(pixbuf.get_height() * scale))
        scaled = pixbuf.scale_simple(wide, tall, GdkPixbuf.InterpType.BILINEAR)
        if scaled is None:
            return None
        # Centre of the picture, which is where the subject usually is.
        cropped = scaled.new_subpixbuf((wide - width) // 2, (tall - height) // 2,
                                       width, height)
        return Gdk.Texture.new_for_pixbuf(cropped or scaled)

    def full(self, entry) -> Gdk.Texture | None:
        """The image at its own size, for the preview and the pop-out."""
        return self._load(entry, None)

    def _load(self, entry, size: int | None) -> Gdk.Texture | None:
        pixbuf = self._pixbuf(entry, size)
        return Gdk.Texture.new_for_pixbuf(pixbuf) if pixbuf else None

    def _pixbuf(self, entry, size: int | None):
        try:
            data = self._store.payload(entry)
        except OSError:
            return None

        loader = GdkPixbuf.PixbufLoader()
        if size is not None:
            # A loader has no dimensions until it reads the header.  GTK only
            # honours set_size from size-prepared, so ask there rather than
            # sizing it before it knows what it is decoding.
            loader.connect("size-prepared", _fit, size)
        try:
            loader.write(data)
            loader.close()
        except GLib.Error:
            return None
        return loader.get_pixbuf()


def _texture(raw: thumbwork.Raw) -> Gdk.Texture:
    fmt = Gdk.MemoryFormat.R8G8B8A8 if raw.mode == "RGBA" else Gdk.MemoryFormat.R8G8B8
    return Gdk.MemoryTexture.new(raw.width, raw.height, fmt, GLib.Bytes.new(raw.data), raw.stride)


def _trim(cache: dict, keep: int) -> None:
    """Drop the oldest, one at a time.

    Clearing the whole cache when it filled up meant every few hundred rows of
    scrolling hit a wall where nothing was remembered any more. Dicts keep
    their insertion order, so the oldest is the one to lose.
    """
    while len(cache) >= keep:
        del cache[next(iter(cache))]


def _fit(loader, width: int, height: int, size: int) -> None:
    """Scale to fit the box, never past the image's own size."""
    if width <= 0 or height <= 0:
        return
    scale = min(size / width, size / height, 1.0)
    loader.set_size(max(1, round(width * scale)), max(1, round(height * scale)))
