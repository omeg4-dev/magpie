"""What the pane under the preview says about the thing you are looking at.

One ellipsised line was enough for a copied string and no use at all for a
picture: it ran out exactly where the filename began, and it never had room for
the size in pixels, which is the first thing anyone wants to know about an
image.

So a picture gets a short block instead — what it is, when it arrived, where it
lives, and what was read off it — and everything else keeps its one line. No
GTK in here, because deciding what to say is not drawing.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

__all__ = ["lines", "QUIET"]

#: Lines that are the absence of a fact rather than a fact. The window draws
#: these more quietly, because "no words in it" is not something to read.
QUIET = ("not read yet", "no words in it")

#: How much of an OCR reading is worth showing. It is there to tell you this is
#: the right screenshot, not to be read.
READING = 96


def lines(entry, dimensions: tuple[int, int] | None = None) -> list[str]:
    """The facts about this entry, one string per line."""
    if entry.kind == "image":
        return _picture(entry, dimensions)
    return [_one_line(entry)]


def _one_line(entry) -> str:
    bits = [_when(entry), entry.mime, size(entry.bytes)]
    if entry.times_seen > 1:
        bits.append(f"copied {entry.times_seen} times")
    if entry.path:
        bits.append(entry.path)
    return "   ·   ".join(bits)


def _picture(entry, dimensions: tuple[int, int] | None) -> list[str]:
    head = []
    if dimensions is not None:
        head.append(f"{dimensions[0]} × {dimensions[1]}")
    head.append(_format_of(entry.mime))
    head.append(size(entry.bytes))
    if entry.times_seen > 1:
        head.append(f"copied {entry.times_seen} times")

    said = ["   ·   ".join(head), _when(entry)]
    if entry.path:
        # The name and the folder on separate lines: the name is what you are
        # looking for and the folder is the long part that used to push it off
        # the end of the line.
        said.append(Path(entry.path).name)
        said.append(str(Path(entry.path).parent))
    said.append(_reading(entry))
    return said


def _reading(entry) -> str:
    """What OCR made of it — or which kind of nothing it made of it."""
    if not entry.read_yet:
        return QUIET[0]
    words = " ".join(entry.text.split())
    if not words:
        return QUIET[1]
    if len(words) > READING:
        words = words[:READING - 1].rstrip() + "…"
    return f"“{words}”"


def _when(entry) -> str:
    when = datetime.fromtimestamp(entry.first_seen_ms / 1000)
    said = when.strftime("%d %B %Y, %H:%M")
    return said + " (reconstructed)" if entry.time_approx else said


def _format_of(mime: str) -> str:
    """PNG, rather than image/png. There is no doubt about the first half."""
    return mime.split("/", 1)[-1].split(";")[0].upper()


def size(count: float) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if count < 1024 or unit == "GB":
            return f"{count:.0f} {unit}" if unit == "B" else f"{count:.1f} {unit}"
        count /= 1024.0
    return f"{count} B"
