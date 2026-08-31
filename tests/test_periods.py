"""Looking at one month at a time.

The screenshot folder is 2,700 files and grows every day. Loading all of it to
show you the twelve pictures you took in June is what made the browser fall
over, so the store has to be able to answer "which months are there" and "just
that one, please".
"""

from datetime import datetime, timezone

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


def at(year, month, day=1, hour=12):
    return int(datetime(year, month, day, hour, tzinfo=timezone.utc).timestamp() * 1000)


def test_a_store_with_nothing_in_it_has_no_months(store):
    assert store.months() == []


def test_it_lists_the_months_that_have_something_in_them(store):
    store.add(b"june", "text/plain", at_ms=at(2026, 6))
    store.add(b"august", "text/plain", at_ms=at(2026, 8))

    assert [(m.year, m.month) for m in store.months()] == [(2026, 8), (2026, 6)]


def test_the_newest_month_comes_first(store):
    for year, month in ((2024, 1), (2026, 8), (2025, 12)):
        store.add(f"{year}-{month}".encode(), "text/plain", at_ms=at(year, month))

    assert [(m.year, m.month) for m in store.months()][0] == (2026, 8)


def test_a_month_says_how_many_are_in_it(store):
    store.add(b"one", "text/plain", at_ms=at(2026, 6, 1))
    store.add(b"two", "text/plain", at_ms=at(2026, 6, 2))
    store.add(b"three", "text/plain", at_ms=at(2026, 7, 1))

    counts = {(m.year, m.month): m.count for m in store.months()}
    assert counts == {(2026, 6): 2, (2026, 7): 1}


def test_months_can_be_asked_for_one_source(store, tmp_path):
    shot = tmp_path / "a.png"
    shot.write_bytes(PNG)
    store.add(b"copied", "text/plain", at_ms=at(2026, 6))
    store.add_file(shot, source="screenshot", mime="image/png", at_ms=at(2020, 1))

    assert [(m.year, m.month) for m in store.months(source="screenshot")] == [(2020, 1)]


def test_a_deleted_entry_is_not_counted(store):
    entry = store.add(b"gone", "text/plain", at_ms=at(2026, 6))
    store.delete(entry.id)

    assert store.months() == []


# -- asking for just one month ---------------------------------------------


def test_a_month_can_be_asked_for_on_its_own(store):
    store.add(b"june", "text/plain", at_ms=at(2026, 6, 15))
    store.add(b"july", "text/plain", at_ms=at(2026, 7, 15))

    found = store.recent(month=(2026, 6))
    assert [e.text for e in found] == ["june"]


def test_the_last_day_of_a_month_is_in_it(store):
    # December is the one that catches an off-by-one in the year rollover.
    store.add(b"new year's eve", "text/plain", at_ms=at(2026, 12, 31, 23))

    assert len(store.recent(month=(2026, 12))) == 1


def test_the_first_moment_of_a_month_is_in_it(store):
    store.add(b"midnight", "text/plain", at_ms=at(2026, 6, 1, 0))
    assert len(store.recent(month=(2026, 6))) == 1


def test_searching_can_be_held_to_one_month(store):
    store.add(b"a screenshot of a terminal", "text/plain", at_ms=at(2026, 6, 15))
    store.add(b"a screenshot of a browser", "text/plain", at_ms=at(2026, 7, 15))

    found = store.search("screenshot", month=(2026, 7))
    assert [e.text for e in found] == ["a screenshot of a browser"]


def test_no_month_means_all_of_them(store):
    store.add(b"june", "text/plain", at_ms=at(2026, 6))
    store.add(b"july", "text/plain", at_ms=at(2026, 7))

    assert len(store.recent()) == 2
