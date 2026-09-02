"""Putting an entry back on the clipboard.

The one thing the viewer exists to do. It goes back through `wl-copy` rather
than through GTK's own clipboard because the viewer closes the instant you
press Enter, and a GTK clipboard offer dies with the process that made it —
wl-copy forks a tiny server that outlives it.
"""

from __future__ import annotations

import subprocess

from .store import Entry, Store

__all__ = ["to_clipboard"]


def _run(argv: list[str], data: bytes) -> int:
    return subprocess.run(argv, input=data).returncode


def to_clipboard(store: Store, entry: Entry, run=_run) -> bool:
    """Offer this entry to everything else. True if wl-copy took it."""
    try:
        data = store.payload(entry)
    except OSError:
        return False  # the file moved, or the blob is gone

    # The stored mime is a header — "text/plain;charset=utf-8" — and wl-copy
    # wants a type. Handing it the header makes an offer nothing will accept.
    mime = entry.mime.split(";", 1)[0].strip() or "text/plain"
    try:
        # Screenshot entries keep their payload in the original file rather
        # than in Magpie's blob store.  Passing those bytes to wl-copy here is
        # intentional: it offers the actual image, not its filesystem path.
        return run(["wl-copy", "--type", mime], data) == 0
    except OSError:
        # Keep a missing wl-copy/Wayland connection from taking down the
        # already-warm viewer.  The selected screenshot remains available for
        # another attempt once the session is ready.
        return False
