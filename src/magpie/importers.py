"""Filling the store from things that already exist.

Both of these are idempotent and cheap to re-run, so they happen on every
start rather than being a setup step you have to remember: the clipboard you
had before magpie, and the screenshot folder that goes on filling up whether
magpie is running or not.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from .capture import sniff
from .reconstruct import interpolate
from .store import Store

__all__ = ["import_noctalia", "import_screenshots", "import_cliphist",
           "read_cliphist", "NOCTALIA", "SCREENSHOTS", "CLIPHIST_DB"]

#: Noctalia's own clipboard store: an index.json rewritten in full on every
#: copy, which is why it caps out at a few hundred entries.
NOCTALIA = Path.home() / ".local/state/noctalia/clipboard"

#: Where grimblast drops things, month-foldered.
SCREENSHOTS = Path("/mnt/xv/Random/Screenshots")

#: cliphist's store, from before Noctalia. A counter and no clock, which is
#: what `reconstruct` exists to deal with.
CLIPHIST_DB = Path.home() / ".cache/cliphist/db"

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
            store.star(entry.id)
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


def read_cliphist(db: Path | str = CLIPHIST_DB) -> tuple[list, int, int]:
    """Read cliphist out through its own binary. Returns entries and time bounds.

    Shelling out rather than parsing the bbolt file: cliphist owns that format
    and `cliphist decode` is the only thing that is going to keep agreeing with
    it. The bounds are the database's own file dates — the run happened
    somewhere inside them, and nothing else on disk says when.
    """
    db = Path(db)
    if not db.exists():
        return [], 0, 0
    try:
        listing = subprocess.run(["cliphist", "list"], capture_output=True,
                                 text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return [], 0, 0

    entries = []
    for line in listing.splitlines():
        entry_id = line.split("\t", 1)[0].strip()
        if not entry_id.isdigit():
            continue
        data = subprocess.run(["cliphist", "decode"], input=entry_id.encode(),
                              capture_output=True).stdout
        if data:
            entries.append((int(entry_id), data))

    stat = db.stat()
    return entries, int(stat.st_ctime * 1000), int(stat.st_mtime * 1000)


def import_cliphist(store: Store, entries, *, first_ms: int, last_ms: int) -> int:
    """Bring a cliphist run across, dated as well as it can honestly be.

    `entries` is (id, bytes), the id being cliphist's own monotonic counter.
    Screenshots already indexed in the store date the entries whose bytes match
    them exactly; everything else is interpolated between those and marked
    approximate.
    """
    entries = sorted(entries)
    if not entries:
        return 0

    anchors = _anchor_times(store, entries)
    times = interpolate([i for i, _ in entries], anchors, first_ms, last_ms)

    added = 0
    for entry_id, data in entries:
        before = store.count()
        store.add(data, sniff(data), source="clipboard", at_ms=times[entry_id],
                  time_approx=entry_id not in anchors)
        added += store.count() - before
    return added


def _anchor_times(store: Store, entries) -> dict[int, int]:
    """Entries whose bytes are a screenshot the store already has a date for."""
    dated = {row["sha256"]: row["first_seen_ms"] for row in store.db.execute(
        "SELECT sha256, MIN(first_seen_ms) AS first_seen_ms FROM entry"
        " WHERE path IS NOT NULL GROUP BY sha256")}
    anchors = {}
    for entry_id, data in entries:
        at_ms = dated.get(hashlib.sha256(data).hexdigest())
        if at_ms is not None:
            anchors[entry_id] = at_ms
    return anchors
