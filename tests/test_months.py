"""Grouping the months into years, for the date bar."""

from magpie.months import MONTH_NAMES, by_year, label
from magpie.store import Month


def test_nothing_groups_into_nothing():
    assert by_year([]) == []


def test_months_group_under_their_year():
    grouped = by_year([Month(2026, 8, 3), Month(2026, 6, 1), Month(2025, 12, 9)])
    assert [year for year, _ in grouped] == [2026, 2025]


def test_the_newest_year_comes_first():
    grouped = by_year([Month(2024, 1, 1), Month(2026, 1, 1)])
    assert grouped[0][0] == 2026


def test_a_year_keeps_its_months_newest_first():
    grouped = by_year([Month(2026, 6, 1), Month(2026, 8, 1), Month(2026, 7, 1)])
    assert [m.month for m in grouped[0][1]] == [8, 7, 6]


def test_a_year_carries_the_total_of_its_months():
    grouped = by_year([Month(2026, 6, 4), Month(2026, 8, 5)])
    assert sum(m.count for m in grouped[0][1]) == 9


def test_every_month_has_a_short_name():
    assert len(MONTH_NAMES) == 12
    assert MONTH_NAMES[0] == "JAN" and MONTH_NAMES[11] == "DEC"


def test_a_month_labels_as_its_name():
    assert label(Month(2026, 8, 3)) == "AUG"
