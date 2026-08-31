"""Recovering the clipboard that ran before Noctalia.

cliphist held 750 entries with no timestamps. What comes across is the whole
run, in order, dated from the screenshots among it that were also saved to
disk — and honestly labelled as reconstructed rather than measured.
"""

from magpie.importers import import_cliphist

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
HOUR = 3_600_000


def test_every_entry_comes_across(store):
    added = import_cliphist(store, [(1, b"one"), (2, b"two")], first_ms=0, last_ms=HOUR)
    assert added == 2 and store.count() == 2


def test_they_come_out_in_the_order_they_went_in(store):
    import_cliphist(store, [(1, b"oldest"), (2, b"middle"), (3, b"newest")],
                    first_ms=0, last_ms=HOUR)

    assert [e.text for e in store.recent()] == ["newest", "middle", "oldest"]


def test_a_screenshot_among_them_dates_the_ones_around_it(store, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)
    store.add_file(shot, source="screenshot", mime="image/png", at_ms=5 * HOUR)

    import_cliphist(store, [(1, b"before"), (2, PNG), (3, b"after")],
                    first_ms=0, last_ms=10 * HOUR)

    by_text = {e.text or e.kind: e for e in store.recent(source="clipboard")}
    assert by_text["image"].first_seen_ms == 5 * HOUR
    assert by_text["before"].first_seen_ms < 5 * HOUR < by_text["after"].first_seen_ms


def test_a_time_that_was_measured_is_not_marked_approximate(store, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)
    store.add_file(shot, source="screenshot", mime="image/png", at_ms=5 * HOUR)

    import_cliphist(store, [(1, PNG)], first_ms=0, last_ms=10 * HOUR)

    assert store.recent(source="clipboard")[0].time_approx is False


def test_a_time_that_was_worked_out_says_so(store):
    import_cliphist(store, [(1, b"one")], first_ms=0, last_ms=HOUR)
    assert store.recent()[0].time_approx is True


def test_a_recovered_entry_is_still_a_clipboard_entry(store):
    # It belongs in the history, not in a museum wing of its own.
    import_cliphist(store, [(1, b"one")], first_ms=0, last_ms=HOUR)
    assert store.recent()[0].source == "clipboard"


def test_importing_twice_adds_nothing(store):
    entries = [(1, b"one"), (2, b"two")]
    import_cliphist(store, entries, first_ms=0, last_ms=HOUR)

    assert import_cliphist(store, entries, first_ms=0, last_ms=HOUR) == 0


def test_a_recovered_entry_does_not_outrank_one_that_is_really_newer(store, clock):
    # The recovered run is months old; nothing in it may sit above today's copy.
    clock.now = 100 * HOUR
    store.add(b"copied just now", "text/plain")
    import_cliphist(store, [(1, b"from june")], first_ms=0, last_ms=HOUR)

    assert store.recent()[0].text == "copied just now"


def test_an_image_among_them_keeps_its_bytes(store):
    import_cliphist(store, [(1, PNG)], first_ms=0, last_ms=HOUR)
    entry = store.recent()[0]

    assert entry.kind == "image" and store.payload(entry) == PNG


def test_an_empty_run_is_not_an_error(store):
    assert import_cliphist(store, [], first_ms=0, last_ms=HOUR) == 0
