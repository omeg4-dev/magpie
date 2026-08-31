"""Filling the store from things that already exist.

Both of these are idempotent and cheap to re-run, so they happen on every
start rather than being a setup step you have to remember: the clipboard you
had before magpie, and the screenshot folder that goes on filling up whether
magpie is running or not.
"""

from __future__ import annotations

import json
from pathlib import Path

from .store import Store

__all__ = ["import_noctalia", "import_screenshots", "NOCTALIA", "SCREENSHOTS"]

#: Noctalia's own clipboard store: an index.json rewritten in full on every
#: copy, which is why it caps out at a few hundred entries.
NOCTALIA = Path.home() / ".local/state/noctalia/clipboard"

#: Where grimblast drops things, month-foldered.
SCREENSHOTS = Path("/mnt/xv/Random/Screenshots")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".avif"}
SUFFIX_MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}


def import_noctalia(store: Store, root: Path | str = NOCTALIA) -> int:
    """Bring across whatever Noctalia's clipboard still holds. Returns how many."""
    index = Path(root) / "index.json"
    try:
        entries = json.loads(index.read_text())["entries"]
    except (OSError, ValueError, KeyError, TypeError):
        # No Noctalia, or a half-written index: there is nothing to import and
        # nothing to complain about.
        return 0

    added = 0
    for record in entries:
        payload = Path(record.get("payload_path", ""))
        try:
            data = payload.read_bytes()
        except OSError:
            continue  # the index outlived the payload
        before = store.count()
        entry = store.add(data, record.get("data_mime_type") or "text/plain",
                          source="clipboard", at_ms=record.get("captured_at_ms"))
        if record.get("pinned"):
            store.pin(entry.id)
        added += store.count() - before
    return added


def import_screenshots(store: Store, root: Path | str = SCREENSHOTS) -> int:
    """Index every image under `root` in place. Returns how many are new."""
    root = Path(root)
    if not root.is_dir():
        return 0

    added = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_SUFFIXES:
            continue
        before = store.count()
        store.add_file(path, source="screenshot", mime=_mime_of(path))
        added += store.count() - before
    return added


def _mime_of(path: Path) -> str:
    suffix = path.suffix.lower()
    return SUFFIX_MIME.get(suffix, f"image/{suffix.lstrip('.')}")
