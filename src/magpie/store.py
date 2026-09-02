"""Everything magpie keeps, and how it finds it again.

Two ideas hold this up.

**Nothing falls off the end.** Noctalia's clipboard is a JSON file rewritten in
full on every copy, which is why it caps out; this is SQLite, so a hundred
thousand entries cost no more per copy than ten. Deleting is a tombstone and a
thirty-day window, not a shredder.

**Content addressing.** A payload is stored once under the sha256 of its bytes,
so copying the same screenshot back and forth all afternoon costs one file. A
repeat is not a new entry either — it moves the entry it already had to the top
and counts it — because a history that lists the same string forty times is a
history you cannot read.

Files on disk (screenshots) are *indexed where they lie* rather than copied.
The store knows about them; it does not own them, and deleting one in the
browser is a decision about a file, not about a clipboard entry.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

__all__ = ["Store", "Entry", "Month", "kind_of", "month_bounds"]

#: How much of an entry the list shows. Long enough to recognise a paragraph,
#: short enough that a copied file never lands a screenful in the sidebar.
PREVIEW = 200

SCHEMA = """
CREATE TABLE IF NOT EXISTS entry (
    id            INTEGER PRIMARY KEY,
    key           TEXT    NOT NULL,   -- what makes it the same thing twice
    sha256        TEXT    NOT NULL,
    kind          TEXT    NOT NULL,   -- text | image | files | binary
    mime          TEXT    NOT NULL,
    source        TEXT    NOT NULL,   -- clipboard | screenshot | noctalia
    path          TEXT,               -- set when the bytes live outside the store
    bytes         INTEGER NOT NULL,
    first_seen_ms INTEGER NOT NULL,
    last_seen_ms  INTEGER NOT NULL,
    times_seen    INTEGER NOT NULL DEFAULT 1,
    starred       INTEGER NOT NULL DEFAULT 0,
    deleted_at_ms INTEGER,
    -- Set when the time was reconstructed rather than measured: everything
    -- recovered from cliphist, which kept a counter and no clock.
    time_approx   INTEGER NOT NULL DEFAULT 0,
    preview       TEXT    NOT NULL,
    text          TEXT    NOT NULL DEFAULT '',
    -- When the picture was read. Set even when nothing was found in it, so
    -- the reader does not come back to the same blank screenshot every hour.
    ocr_ms        INTEGER
);

CREATE UNIQUE INDEX IF NOT EXISTS entry_identity ON entry(source, key);
CREATE INDEX IF NOT EXISTS entry_recent ON entry(deleted_at_ms, last_seen_ms DESC);
CREATE INDEX IF NOT EXISTS entry_sha ON entry(sha256);

CREATE VIRTUAL TABLE IF NOT EXISTS entry_fts USING fts5(
    text,
    tokenize = "unicode61 remove_diacritics 2"
);
"""


#: Columns added after the first release, applied to a store that predates
#: them. Append here rather than editing SCHEMA alone.
COLUMNS_ADDED_LATER = [
    ("time_approx", "time_approx INTEGER NOT NULL DEFAULT 0"),
    ("ocr_ms", "ocr_ms INTEGER"),
]

#: Columns that changed their name. `pinned` became `starred` when pinning
#: became a starred list you can open on its own.
COLUMNS_RENAMED = [("pinned", "starred")]


@dataclass(frozen=True)
class Month:
    """One month that has something in it, and how much."""

    year: int
    month: int
    count: int

    @property
    def key(self) -> tuple[int, int]:
        return (self.year, self.month)


@dataclass(frozen=True)
class Entry:
    id: int
    key: str
    sha256: str
    kind: str
    mime: str
    source: str
    path: str | None
    bytes: int
    first_seen_ms: int
    last_seen_ms: int
    times_seen: int
    starred: bool
    deleted_at_ms: int | None
    time_approx: bool
    preview: str
    text: str
    ocr_ms: int | None = None

    @property
    def read_yet(self) -> bool:
        """Whether this picture has been through OCR (however little it said)."""
        return self.ocr_ms is not None

    @property
    def is_image(self) -> bool:
        return self.kind == "image"


def kind_of(mime: str) -> str:
    """What a mime type means to a person looking at a list."""
    mime = mime.split(";", 1)[0].strip().lower()
    if mime.startswith("image/"):
        return "image"
    if mime == "text/uri-list":
        return "files"
    if mime.startswith("text/") or mime in ("application/json", "application/xml"):
        return "text"
    return "binary"


def month_bounds(year: int, month: int) -> tuple[int, int]:
    """The half-open range of milliseconds this month covers, in UTC.

    Half-open so the last second of the month is inside it and the first
    second of the next one is not — the rollover from December is where an
    inclusive range goes wrong.
    """
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    end = (datetime(year + 1, 1, 1, tzinfo=timezone.utc) if month == 12
           else datetime(year, month + 1, 1, tzinfo=timezone.utc))
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000)


def _now_ms() -> int:
    return int(time.time() * 1000)


class Store:
    def __init__(self, root: Path | str, clock=_now_ms) -> None:
        self.root = Path(root)
        self._clock = clock
        self._blobs = self.root / "blobs"
        self._blobs.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.root / "magpie.db", isolation_level=None)
        self.db.row_factory = sqlite3.Row
        # The watcher writes while the viewer reads, so both need to get on
        # with it rather than block each other.
        self.db.execute("PRAGMA journal_mode = WAL")
        self.db.execute("PRAGMA synchronous = NORMAL")
        self.db.executescript(SCHEMA)
        self._migrate()

    def _migrate(self) -> None:
        """Bring an older store up to the current schema.

        The store outlives the code that made it, and losing a clipboard to a
        new column would be an absurd way to lose one.
        """
        have = {row["name"] for row in self.db.execute("PRAGMA table_info(entry)")}
        for old, new in COLUMNS_RENAMED:
            if old in have and new not in have:
                self.db.execute(f"ALTER TABLE entry RENAME COLUMN {old} TO {new}")
                have.discard(old)
                have.add(new)
        for column, definition in COLUMNS_ADDED_LATER:
            if column not in have:
                self.db.execute(f"ALTER TABLE entry ADD COLUMN {definition}")

    # -- putting things in -------------------------------------------------

    def add(self, data: bytes, mime: str, *, source: str = "clipboard",
            at_ms: int | None = None, time_approx: bool = False) -> Entry:
        """Take a copy of these bytes. Seeing them again just bumps the entry."""
        digest = hashlib.sha256(data).hexdigest()
        existing = self._by_identity(source, digest)
        if existing is not None:
            return self._seen_again(existing, at_ms)

        self._write_blob(digest, data)
        return self._insert(key=digest, digest=digest, data=data, mime=mime,
                            source=source, path=None, size=len(data), at_ms=at_ms,
                            time_approx=time_approx)

    def add_file(self, path: Path | str, *, source: str = "screenshot",
                 mime: str = "application/octet-stream",
                 at_ms: int | None = None) -> Entry:
        """Index a file where it lies. The store points at it; it does not own it."""
        path = Path(path).resolve()
        # The file's own date, decided before the identity check: `sync` walks
        # the whole folder hourly, and noticing that a file is still there is
        # not the same as it being new.
        if at_ms is None:
            at_ms = int(path.stat().st_mtime * 1000)

        existing = self._by_identity(source, str(path))
        if existing is not None:
            return self._seen_again(existing, at_ms)

        data = path.read_bytes()
        return self._insert(key=str(path), digest=hashlib.sha256(data).hexdigest(),
                            data=data, mime=mime, source=source, path=str(path),
                            size=len(data), at_ms=at_ms, name=path.name)

    def _insert(self, *, key, digest, data, mime, source, path, size, at_ms,
                name: str | None = None, time_approx: bool = False) -> Entry:
        at_ms = self._clock() if at_ms is None else at_ms
        kind = kind_of(mime)
        text = _text_of(data, kind)
        preview = _preview_of(text, kind, mime, size, name)
        cursor = self.db.execute(
            "INSERT INTO entry (key, sha256, kind, mime, source, path, bytes,"
            "  first_seen_ms, last_seen_ms, time_approx, preview, text)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (key, digest, kind, mime, source, path, size, at_ms, at_ms,
             1 if time_approx else 0, preview, text))
        row_id = cursor.lastrowid
        self.db.execute("INSERT INTO entry_fts (rowid, text) VALUES (?,?)",
                        (row_id, text or preview))
        return self.get(row_id)

    def _seen_again(self, entry: Entry, at_ms: int | None) -> Entry:
        at_ms = self._clock() if at_ms is None else at_ms
        self.db.execute(
            "UPDATE entry SET last_seen_ms = MAX(last_seen_ms, ?),"
            "  times_seen = times_seen + 1, deleted_at_ms = NULL WHERE id = ?",
            (at_ms, entry.id))
        return self.get(entry.id)

    def set_text(self, entry_id: int, text: str) -> None:
        """Give an entry words it did not arrive with."""
        self.db.execute("UPDATE entry SET text = ? WHERE id = ?", (text, entry_id))
        self.db.execute("UPDATE entry_fts SET text = ? WHERE rowid = ?", (text, entry_id))

    def set_ocr(self, entry_id: int, text: str) -> None:
        """What was read off a picture, and the fact that it has been read.

        The time is recorded even when the text is empty. Most screenshots are
        of something with no words in it at all, and a reader that treats "no
        text" as "not read yet" comes back to every one of them for ever.
        """
        self.set_text(entry_id, text)
        self.db.execute("UPDATE entry SET ocr_ms = ? WHERE id = ?",
                        (self._clock(), entry_id))

    def unread_images(self, limit: int = 5_000) -> list[Entry]:
        """Pictures nobody has read yet, newest first.

        Newest first because the screenshot you want to find is far more often
        one from this week than one from 2022, and a backlog of thousands is
        worth something long before it is finished.
        """
        rows = self.db.execute(
            "SELECT * FROM entry WHERE kind = 'image' AND ocr_ms IS NULL"
            "  AND deleted_at_ms IS NULL"
            " ORDER BY last_seen_ms DESC, id DESC LIMIT ?", (limit,))
        return [_entry(row) for row in rows]

    # -- getting things out ------------------------------------------------

    def get(self, entry_id: int) -> Entry | None:
        row = self.db.execute("SELECT * FROM entry WHERE id = ?", (entry_id,)).fetchone()
        return _entry(row) if row else None

    def payload(self, entry: Entry) -> bytes:
        if entry.path is not None:
            return Path(entry.path).read_bytes()
        return self._blob_path(entry.sha256).read_bytes()

    def months(self, source: str | None = None) -> list[Month]:
        """Which months have anything in them, oldest first, with counts.

        This is what the screenshot browser is navigated by. Loading 2,700
        files to show you the twelve you took in June is what made it fall
        over; asking the index which months exist costs one grouped scan.
        """
        where, params = ["deleted_at_ms IS NULL"], []
        if source is not None:
            where.append("source = ?")
            params.append(source)
        rows = self.db.execute(
            "SELECT CAST(strftime('%Y', last_seen_ms / 1000, 'unixepoch') AS INTEGER)"
            "         AS year,"
            "       CAST(strftime('%m', last_seen_ms / 1000, 'unixepoch') AS INTEGER)"
            "         AS month,"
            "       COUNT(*) AS count"
            f" FROM entry WHERE {' AND '.join(where)}"
            " GROUP BY year, month ORDER BY year ASC, month ASC", params)
        return [Month(row["year"], row["month"], row["count"]) for row in rows]

    def recent(self, limit: int = 200, *, kind: str | None = None,
               source: str | None = None, starred: bool | None = None,
               month: tuple[int, int] | None = None) -> list[Entry]:
        where, params = ["deleted_at_ms IS NULL"], []
        if kind is not None:
            where.append("kind = ?")
            params.append(kind)
        if source is not None:
            where.append("source = ?")
            params.append(source)
        if starred is not None:
            where.append("starred = ?")
            params.append(1 if starred else 0)
        if month is not None:
            where.append("last_seen_ms >= ? AND last_seen_ms < ?")
            params.extend(month_bounds(*month))
        params.append(limit)
        rows = self.db.execute(
            f"SELECT * FROM entry WHERE {' AND '.join(where)}"
            " ORDER BY last_seen_ms DESC, id DESC LIMIT ?", params)
        return [_entry(row) for row in rows]

    def search(self, query: str, limit: int = 200, *, kind: str | None = None,
               source: str | None = None, starred: bool | None = None,
               month: tuple[int, int] | None = None) -> list[Entry]:
        """Find entries by their words. An empty query is just the recent list."""
        if not query.strip():
            return self.recent(limit, kind=kind, source=source, starred=starred,
                               month=month)

        where, params = ["entry.deleted_at_ms IS NULL"], [_fts_query(query)]
        if kind is not None:
            where.append("entry.kind = ?")
            params.append(kind)
        if source is not None:
            where.append("entry.source = ?")
            params.append(source)
        if starred is not None:
            where.append("entry.starred = ?")
            params.append(1 if starred else 0)
        if month is not None:
            where.append("entry.last_seen_ms >= ? AND entry.last_seen_ms < ?")
            params.extend(month_bounds(*month))
        params.append(limit)
        rows = self.db.execute(
            "SELECT entry.* FROM entry_fts JOIN entry ON entry.id = entry_fts.rowid"
            f" WHERE entry_fts MATCH ? AND {' AND '.join(where)}"
            " ORDER BY entry.last_seen_ms DESC, entry.id DESC LIMIT ?", params)
        return [_entry(row) for row in rows]

    def count(self, *, source: str | None = None,
              starred: bool | None = None) -> int:
        sql = "SELECT COUNT(*) FROM entry WHERE deleted_at_ms IS NULL"
        params: list = []
        if source is not None:
            sql += " AND source = ?"
            params.append(source)
        if starred is not None:
            sql += " AND starred = ?"
            params.append(1 if starred else 0)
        return self.db.execute(sql, params).fetchone()[0]

    # -- keeping and losing things ----------------------------------------

    def star(self, entry_id: int, starred: bool = True) -> None:
        """Keep this one. A star is a bookmark, not a move: it stays where it is."""
        self.db.execute("UPDATE entry SET starred = ? WHERE id = ?",
                        (1 if starred else 0, entry_id))

    def delete(self, entry_id: int) -> None:
        """Hide it now; the bytes stay until `purge`, so undo is always possible."""
        self.db.execute("UPDATE entry SET deleted_at_ms = ? WHERE id = ?",
                        (self._clock(), entry_id))

    def restore(self, entry_id: int) -> None:
        self.db.execute("UPDATE entry SET deleted_at_ms = NULL WHERE id = ?", (entry_id,))

    def purge(self, after_ms: int = 30 * 86_400_000) -> int:
        """Really drop what has been in the bin longer than `after_ms`."""
        cutoff = self._clock() - after_ms
        rows = self.db.execute(
            "SELECT id, sha256 FROM entry"
            " WHERE deleted_at_ms IS NOT NULL AND deleted_at_ms < ? AND starred = 0",
            (cutoff,)).fetchall()
        for row in rows:
            self._forget(row["id"], row["sha256"])
        return len(rows)

    def forget_missing_files(self) -> int:
        """Drop indexed files that are no longer on disk."""
        rows = self.db.execute(
            "SELECT id, sha256, path FROM entry WHERE path IS NOT NULL").fetchall()
        gone = [row for row in rows if not os.path.exists(row["path"])]
        for row in gone:
            self._forget(row["id"], row["sha256"])
        return len(gone)

    def _forget(self, entry_id: int, digest: str) -> None:
        self.db.execute("DELETE FROM entry WHERE id = ?", (entry_id,))
        self.db.execute("DELETE FROM entry_fts WHERE rowid = ?", (entry_id,))
        self._drop_blob_if_unused(digest)

    # -- the blobs ---------------------------------------------------------

    def _blob_path(self, digest: str) -> Path:
        return self._blobs / digest[:2] / f"{digest}.bin"

    def _write_blob(self, digest: str, data: bytes) -> None:
        blob = self._blob_path(digest)
        if blob.exists():
            return
        blob.parent.mkdir(parents=True, exist_ok=True)
        # Written beside and renamed, so a half-written payload is never
        # readable under its own hash.
        partial = blob.with_suffix(".part")
        partial.write_bytes(data)
        partial.replace(blob)

    def _drop_blob_if_unused(self, digest: str) -> None:
        still_used = self.db.execute(
            "SELECT 1 FROM entry WHERE sha256 = ? AND path IS NULL LIMIT 1",
            (digest,)).fetchone()
        if still_used:
            return
        self._blob_path(digest).unlink(missing_ok=True)

    def _by_identity(self, source: str, key: str) -> Entry | None:
        row = self.db.execute("SELECT * FROM entry WHERE source = ? AND key = ?",
                              (source, key)).fetchone()
        return _entry(row) if row else None


# -- turning bytes into something a list can show --------------------------


def _entry(row: sqlite3.Row) -> Entry:
    return Entry(id=row["id"], key=row["key"], sha256=row["sha256"], kind=row["kind"],
                 mime=row["mime"], source=row["source"], path=row["path"],
                 bytes=row["bytes"], first_seen_ms=row["first_seen_ms"],
                 last_seen_ms=row["last_seen_ms"], times_seen=row["times_seen"],
                 starred=bool(row["starred"]), deleted_at_ms=row["deleted_at_ms"],
                 time_approx=bool(row["time_approx"]),
                 preview=row["preview"], text=row["text"], ocr_ms=row["ocr_ms"])


def _text_of(data: bytes, kind: str) -> str:
    if kind not in ("text", "files"):
        return ""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("utf-8", "replace")


def _preview_of(text: str, kind: str, mime: str, size: int, name: str | None) -> str:
    if kind == "image":
        label = mime.split("/", 1)[-1].split(";")[0].upper()
        return f"{name or label + ' image'} · {_size(size)}"
    if kind == "files":
        names = [line.rsplit("/", 1)[-1] for line in text.split() if line.strip()]
        return ", ".join(names)[:PREVIEW] or "(no files)"
    if kind == "binary":
        return f"{mime} · {_size(size)}"
    # One line: the sidebar is a list, and a copied file would otherwise put a
    # screenful of it in there.
    line = " ".join(text.split())
    return line[:PREVIEW] if line else "(blank)"


def _size(size: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size} B"


def _fts_query(query: str) -> str:
    """Make a user's typing safe for FTS5.

    A clipboard is mostly URLs, paths and command lines, so anything typed into
    the filter box is full of characters FTS5 reads as syntax. Quoting the lot
    as one phrase makes it literal; the trailing star keeps the list narrowing
    as you type rather than only on whole words.
    """
    return '"' + query.replace('"', '""') + '"*'
