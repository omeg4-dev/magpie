"""The work of making a thumbnail, with no GTK in it.

Kept apart from `thumbs.py` for two reasons. It runs on worker threads, and a
worker must never touch a widget or a texture's owner. And it is the part with
arithmetic in it — crop to an exact box, cache on disk, say whether a picture
has transparency — which is worth being able to test without a display.

A finished thumbnail is `Raw`: a mode ("RGB" or "RGBA"), a size and the pixel
bytes. The main thread turns that into a `Gdk.MemoryTexture`, which is a copy
of a pointer rather than a decode.

The disk cache is keyed by the picture's own hash, so it can never be stale: a
different picture is a different file. A small JPEG decodes in a fraction of a
millisecond, where the screenshot it came from takes tens.
"""

from __future__ import annotations

import io
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

__all__ = ["Raw", "cache_dir", "cached_path", "load_cached", "stamp", "preview", "store_cached"]

#: JPEG quality for cached thumbnails. 4:4:4, because a thumbnail of a screenshot
#: is mostly thin text, and chroma subsampling is what makes that smear.
QUALITY = 88


@dataclass(frozen=True)
class Raw:
    mode: str       # "RGB" or "RGBA" (straight alpha)
    width: int
    height: int
    data: bytes

    @property
    def stride(self) -> int:
        return self.width * (4 if self.mode == "RGBA" else 3)


def cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "magpie" / "thumbs"


def cached_path(root: Path, sha: str, width: int, height: int, ext: str) -> Path:
    return root / sha[:2] / f"{sha}-{width}x{height}.{ext}"


def load_cached(root: Path, sha: str, width: int, height: int) -> Raw | None:
    """A thumbnail made earlier, or None. Never raises: a bad cache file is a miss."""
    for ext in ("jpg", "png"):
        path = cached_path(root, sha, width, height, ext)
        try:
            with Image.open(path) as im:
                im.load()
                return _raw(im)
        except (OSError, ValueError):
            continue
    return None


def store_cached(root: Path, sha: str, raw: Raw) -> None:
    """Write it down for next time. Best effort, and atomic: a half-written
    file must not be read back as a thumbnail."""
    ext = "png" if raw.mode == "RGBA" else "jpg"
    path = cached_path(root, sha, raw.width, raw.height, ext)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        im = Image.frombytes(raw.mode, (raw.width, raw.height), raw.data)
        if ext == "jpg":
            im.save(tmp, "JPEG", quality=QUALITY, subsampling=0)
        else:
            im.save(tmp, "PNG", compress_level=1)
        os.replace(tmp, path)
    except OSError:
        pass


def stamp(data: bytes, width: int, height: int) -> Raw | None:
    """The picture cropped to exactly width x height, from its centre.

    Exact because GTK sizes a Picture from its paintable: a thumbnail that is
    merely "about" the right size makes a column of rows of different widths.
    """
    try:
        with Image.open(io.BytesIO(data)) as im:
            _draft(im, width * 2, height * 2)
            im.load()
            scale = max(width / im.width, height / im.height)
            wide, tall = max(width, round(im.width * scale)), max(height, round(im.height * scale))
            im = _flatten(im).resize((wide, tall), Image.Resampling.BILINEAR,
                                     reducing_gap=2.0)
            left, top = (wide - width) // 2, (tall - height) // 2
            return _raw(im.crop((left, top, left + width, top + height)))
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def preview(data: bytes, size: int) -> Raw | None:
    """The picture fitted inside size x size, never enlarged."""
    try:
        with Image.open(io.BytesIO(data)) as im:
            _draft(im, size, size)
            im.load()
            scale = min(size / im.width, size / im.height, 1.0)
            if scale < 1.0:
                im = im.resize((max(1, round(im.width * scale)), max(1, round(im.height * scale))),
                               Image.Resampling.BILINEAR, reducing_gap=2.0)
            return _raw(_flatten(im))
    except (OSError, ValueError, Image.DecompressionBombError):
        return None


def _draft(im: Image.Image, width: int, height: int) -> None:
    """Let a JPEG decode at a fraction of its size. A no-op for formats that cannot."""
    try:
        im.draft("RGB", (width, height))
    except (AttributeError, ValueError):
        pass


def _flatten(im: Image.Image) -> Image.Image:
    """Opaque pictures as RGB; anything with transparency as RGBA."""
    if im.mode in ("RGB", "RGBA"):
        return im
    if im.mode in ("LA", "PA") or "transparency" in im.info:
        return im.convert("RGBA")
    return im.convert("RGB")


def _raw(im: Image.Image) -> Raw:
    im = _flatten(im)
    return Raw(im.mode, im.width, im.height, im.tobytes())
