"""Putting times back on entries that never carried any.

cliphist keeps a monotonic counter and no clock. Seven hundred and fifty
entries survive in exactly the right order with no idea when any of them
happened, and a history sorted by "sometime before June" is not a history.

The way out is that some of those entries are screenshots which were also
*saved*, and a file on disk has a date. Hash the payloads, match them against
the screenshot folder, and a scattering of entries become datable exactly —
here, 65 of them, in strictly increasing id order, a median of 24 minutes
apart. Everything else is then bracketed between two things that really
happened, and linear interpolation over the id counter is a far better guess
than any single made-up number.

The result is still marked approximate. An entry between two anchors is right
to within the gap between them, which is usually minutes and occasionally
days, and the viewer should say so rather than pretend to a timestamp.
"""

from __future__ import annotations

__all__ = ["interpolate"]


def interpolate(ids: list[int], anchors: dict[int, int],
                first_ms: int, last_ms: int) -> dict[int, int]:
    """Date every id, given real times for some of them.

    `ids` is the counter, ascending. `anchors` maps some of those ids to times
    that are actually known. `first_ms` and `last_ms` bound the whole run — the
    earliest and latest it could possibly have happened, from the store's own
    file dates.

    Interpolation runs over the id counter, not over position in the list,
    because the counter keeps counting through entries that have since been
    deleted: an id two after an anchor really is closer in time than one two
    hundred after it.
    """
    ids = sorted(ids)
    if not ids:
        return {}

    known = sorted((i, t) for i, t in anchors.items() if i in set(ids))
    if not known:
        known = [(ids[0], first_ms), (ids[-1], last_ms)]

    # Bound the run at both ends, so entries outside the anchored stretch are
    # still pinned between two real dates rather than dangling.
    edges = list(known)
    if ids[0] < known[0][0]:
        edges.insert(0, (ids[0] - 1, min(first_ms, known[0][1])))
    if ids[-1] > known[-1][0]:
        edges.append((ids[-1] + 1, max(last_ms, known[-1][1])))

    times = {i: anchors[i] if i in anchors else _between(i, edges) for i in ids}
    return _make_strictly_increasing(ids, times)


def _between(target: int, edges: list[tuple[int, int]]) -> int:
    """Where `target` falls on the line through the surrounding known points."""
    if target <= edges[0][0]:
        return edges[0][1]
    if target >= edges[-1][0]:
        return edges[-1][1]
    for (low_id, low_ms), (high_id, high_ms) in zip(edges, edges[1:]):
        if low_id <= target <= high_id:
            span = high_id - low_id
            if span == 0:
                return low_ms
            return low_ms + round((high_ms - low_ms) * (target - low_id) / span)
    return edges[-1][1]


def _make_strictly_increasing(ids: list[int], times: dict[int, int]) -> dict[int, int]:
    """No two entries may share a millisecond: they have to be orderable.

    Anchors are moved rather than kept exact only when a run of interpolated
    entries has already caught up with one, which needs anchors less than a
    millisecond per entry apart.
    """
    previous = None
    for i in ids:
        if previous is not None and times[i] <= previous:
            times[i] = previous + 1
        previous = times[i]
    return times
