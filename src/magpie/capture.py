"""Taking things off the clipboard.

Driven by wl-paste, which is the only thing on Wayland that reliably knows when
a selection changed:

    wl-paste --type text  --watch magpie store
    wl-paste --type image --watch magpie store

Two watchers because wl-paste negotiates one type per invocation, and it hands
the new content over on stdin with no mime attached — so the type is read back
off the bytes here.

The one thing this deliberately drops on the floor is a selection wl-paste
marks sensitive. Password managers set that flag precisely so a clipboard
history does not keep the password, and a history that ignores it is a
liability rather than a feature.
"""

from __future__ import annotations

__all__ = ["capture", "sniff", "MAX_BYTES"]

#: Above this a copy is refused. A screenshot is a megabyte or two; anything at
#: this size is a file that wandered into the clipboard, and writing it on every
#: copy would cost more than it is ever worth reading back.
MAX_BYTES = 64 * 1024 * 1024

#: (magic bytes, offset, mime). Ordered, so the RIFF check runs after the ones
#: that cannot be confused with it.
MAGIC = [
    (b"\x89PNG\r\n\x1a\n", 0, "image/png"),
    (b"\xff\xd8\xff", 0, "image/jpeg"),
    (b"GIF87a", 0, "image/gif"),
    (b"GIF89a", 0, "image/gif"),
    (b"WEBP", 8, "image/webp"),
    (b"BM", 0, "image/bmp"),
    (b"<svg", 0, "image/svg+xml"),
]


def sniff(data: bytes) -> str:
    """What these bytes are, given that nobody said."""
    for magic, offset, mime in MAGIC:
        if data[offset:offset + len(magic)] == magic:
            return mime
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return "application/octet-stream"
    if text.startswith(("file://", "http://", "https://")) and _is_uri_list(text):
        return "text/uri-list"
    return "text/plain"


def _is_uri_list(text: str) -> bool:
    lines = [line for line in text.splitlines() if line.strip()]
    return bool(lines) and all(line.startswith("file://") for line in lines)


def capture(store, data: bytes, state: str = "data", *, at_ms: int | None = None):
    """Store one clipboard offer, or decide it is not worth keeping.

    `state` is wl-paste's own CLIPBOARD_STATE: "data", "clear" or "sensitive".
    """
    if state != "data":
        return None
    if not data or not data.strip() or len(data) > MAX_BYTES:
        return None
    return store.add(data, sniff(data), source="clipboard", at_ms=at_ms)
