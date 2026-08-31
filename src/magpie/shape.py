"""Cutting text down to what a tile can hold.

A GTK label overlaid on a card draws at its natural height, so a long copy runs
off the bottom of the tile and over the ones below it — clipping the card did
not reliably stop it. Deciding the exact lines here does, and unlike a clip it
is something that can be tested.

Two rules, both of them about recognising a thing at a glance:

**Explicit line breaks are kept.** Most of what lands on this clipboard is
code, paths and command lines, and those are far easier to recognise with their
shape intact than reflowed into a paragraph.

**Long lines wrap rather than truncate.** A copied paragraph arrives as one
enormous line, and cutting it at the first twenty-five characters would waste
six sevenths of the tile.
"""

from __future__ import annotations

import textwrap

__all__ = ["to_tile"]

ELLIPSIS = "…"


def to_tile(text: str, lines: int, width: int) -> str:
    """At most `lines` lines of at most `width` characters."""
    kept: list[str] = []
    pending_blank = False

    for raw in text.expandtabs(4).splitlines():
        line = raw.rstrip()
        if not line.strip():
            # One blank line carries the break; a run of them just wastes the
            # tile, and copied text is full of them.
            pending_blank = bool(kept)
            continue
        if pending_blank:
            if len(kept) >= lines:
                return _mark(kept)
            kept.append("")
            pending_blank = False
        for piece in _wrap(line, width):
            if len(kept) >= lines:
                return _mark(kept)
            kept.append(piece)

    return "\n".join(kept)


def _wrap(line: str, width: int) -> list[str]:
    """Break one long line at spaces, and mid-word when there are none.

    `break_long_words` matters: a URL or a base64 blob has nowhere to break,
    and must still fill the tile rather than disappear from it.
    """
    if len(line) <= width:
        return [line]
    return textwrap.wrap(line, width=width, break_long_words=True,
                         break_on_hyphens=False, replace_whitespace=False,
                         drop_whitespace=True) or [line[:width]]


def _mark(kept: list[str]) -> str:
    """Say that there was more, on the last line there is room for."""
    if kept and not kept[-1].endswith(ELLIPSIS):
        kept[-1] = kept[-1][:max(0, len(kept[-1]) - 1)] + ELLIPSIS
    return "\n".join(kept)
