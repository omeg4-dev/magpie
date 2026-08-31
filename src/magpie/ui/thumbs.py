"""Thumbnails, cheaply.

The gallery scrolls over thousands of images, so nothing is loaded until it is
on screen and nothing is decoded twice. GTK's GridView only ever builds the
rows you can see, which does most of the work; this adds the memory so that
scrolling back up is instant.
"""

from __future__ import annotations

from gi.repository import Gdk, GdkPixbuf, GLib

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


class Thumbs:
    def __init__(self, store) -> None:
        self._store = store
        self._stamps: dict[tuple, Gdk.Texture | None] = {}
        self._previews: dict[int, Gdk.Texture | None] = {}
        self._sizes: dict[int, tuple[int, int] | None] = {}

    def dimensions(self, entry) -> tuple[int, int] | None:
        """How big the picture really is, without decoding all of it.

        The preview is decoded no larger than it is shown, so its texture
        cannot answer this — and "1920 × 1080" is the first thing anyone wants
        to know about a screenshot.
        """
        if entry.id not in self._sizes:
            self._sizes[entry.id] = self._measure(entry)
        return self._sizes[entry.id]

    def _measure(self, entry) -> tuple[int, int] | None:
        if entry.path:
            # Reads the header and stops. Free, next to opening the file.
            info = GdkPixbuf.Pixbuf.get_file_info(entry.path)
            if info and info[0] is not None:
                return (info[1], info[2])
            return None
        try:
            data = self._store.payload(entry)
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
            # Scaled while decoding: a 4K screenshot never becomes a full
            # bitmap in memory just to end up 168 pixels wide.
            loader.set_size(size, size)
            loader.connect("size-prepared", _fit, size)
        try:
            loader.write(data)
            loader.close()
        except GLib.Error:
            return None
        return loader.get_pixbuf()


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
