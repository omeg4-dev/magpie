"""Putting times back on entries that never had any.

cliphist stores a monotonic counter and no clock, so 750 entries survive in the
right *order* with no idea *when*. Some of them are screenshots that were also
saved to disk, and those files do have times — so a handful of entries are
datable exactly, and everything between two of them is bracketed by two things
that really happened.
"""

from magpie.reconstruct import interpolate

HOUR = 3_600_000


def test_an_anchored_entry_keeps_its_real_time(anchors={10: 1_000, 20: 5_000}):
    times = interpolate([10, 20], anchors, 0, 10_000)
    assert times[10] == 1_000 and times[20] == 5_000


def test_an_entry_halfway_between_anchors_lands_halfway():
    times = interpolate([10, 15, 20], {10: 1_000, 20: 5_000}, 0, 10_000)
    assert times[15] == 3_000


def test_the_gap_is_shared_out_by_id_not_by_position():
    # The ids are a counter with holes in it, and an entry two ids after an
    # anchor is nearer to it in time than one two hundred ids later.
    times = interpolate([10, 11, 90, 100], {10: 0, 100: 90_000}, -1, 100_000)
    assert times[11] == 1_000 and times[90] == 80_000


def test_time_never_goes_backwards():
    times = interpolate(list(range(10, 30)), {10: 1_000, 29: 2_000}, 0, 10_000)
    ordered = [times[i] for i in range(10, 30)]
    assert ordered == sorted(ordered)


def test_two_entries_never_share_a_millisecond():
    # They are a history; a list that cannot order them is not one.
    times = interpolate(list(range(10, 30)), {10: 1_000, 29: 1_005}, 0, 10_000)
    assert len(set(times.values())) == 20


def test_entries_before_the_first_anchor_stay_before_it():
    times = interpolate([1, 2, 3, 10], {10: 5 * HOUR}, 0, 10 * HOUR)
    assert times[1] < times[2] < times[3] < times[10]
    assert times[1] >= 0


def test_entries_after_the_last_anchor_stay_before_the_upper_bound():
    # The upper bound is real: it is when the database was last written.
    times = interpolate([10, 11, 12], {10: 5 * HOUR}, 0, 6 * HOUR)
    assert times[10] < times[11] < times[12] <= 6 * HOUR


def test_with_no_anchors_at_all_they_spread_across_the_window():
    times = interpolate([1, 2, 3], {}, 0, 3_000)
    assert list(times) == [1, 2, 3]
    assert 0 <= times[1] < times[2] < times[3] <= 3_000


def test_one_anchor_still_dates_everything_around_it():
    times = interpolate([1, 5, 9], {5: 5_000}, 0, 10_000)
    assert times[1] < 5_000 == times[5] < times[9]


def test_an_anchor_that_is_not_in_the_list_is_ignored():
    times = interpolate([1, 2], {99: 5_000}, 0, 10_000)
    assert set(times) == {1, 2}


def test_every_entry_gets_a_time():
    ids = list(range(100, 200, 3))
    times = interpolate(ids, {103: 1_000, 160: 90_000}, 0, 100_000)
    assert set(times) == set(ids)
