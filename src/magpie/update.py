"""The smallest splice that turns the list on screen into the list you want.

GTK's list views hold a couple of hundred rows ready around wherever you are
looking, and replacing a model's contents makes it rebuild all of them —
ninety milliseconds, whether one entry changed or every one did. An insertion
or a removal only shifts them, and costs about one.

Nearly every refresh here is an insertion of one or two at the top: you pressed
Super+V again, and something has been copied since. So the cheap cases are
worth finding, and the expensive one is worth keeping as the fallback it is.

This is one common prefix and one common suffix — not a diff. Anything that is
neither an insertion nor a removal at a single point is a replacement, because
a wrong answer here shows the wrong rows.
"""

from __future__ import annotations

__all__ = ["plan"]


def plan(old: list[int], new: list[int]) -> tuple[str, int, int]:
    """`(what, at, count)`, where `what` is keep, insert, remove or replace.

    `insert` means: put `count` of the new entries in at `at`. `remove` means:
    take `count` out at `at`. Both leave everything else where it was.
    """
    same = _common_prefix(old, new)
    if same == len(old) == len(new):
        return ("keep", 0, 0)

    tail = _common_suffix(old, new, same)
    if same + tail == len(old):
        return ("insert", same, len(new) - len(old))
    if same + tail == len(new):
        return ("remove", same, len(old) - len(new))
    return ("replace", 0, len(old))


def _common_prefix(old: list[int], new: list[int]) -> int:
    limit = min(len(old), len(new))
    at = 0
    while at < limit and old[at] == new[at]:
        at += 1
    return at


def _common_suffix(old: list[int], new: list[int], after: int) -> int:
    limit = min(len(old), len(new)) - after
    at = 0
    while at < limit and old[len(old) - 1 - at] == new[len(new) - 1 - at]:
        at += 1
    return at
