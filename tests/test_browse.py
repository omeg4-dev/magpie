"""What the window is looking at.

All of the viewer's decisions that are not drawing: which entries a mode shows,
what the filter box does to them, and where the selection goes when the list
moves under it. Kept out of the GTK code so it can be tested without a screen —
and so that "the selection jumped" is a test failure rather than a bug report.
"""

import pytest

from magpie.browse import Browse

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


@pytest.fixture
def filled(store, tmp_path, clock):
    """A clipboard with something of everything in it."""
    store.add(b"a copied line", "text/plain")
    clock.advance(1000)
    store.add(PNG, "image/png")
    clock.advance(1000)
    shot = tmp_path / "2026-08" / "shot.png"
    shot.parent.mkdir()
    shot.write_bytes(PNG + b"different")
    store.add_file(shot, source="screenshot", mime="image/png")
    return store


def test_it_opens_on_the_clipboard(filled):
    assert Browse(filled).mode == "clipboard"


def test_the_clipboard_is_what_you_copied(filled):
    browse = Browse(filled)
    assert {e.source for e in browse.entries()} == {"clipboard"}


def test_the_screenshot_folder_is_not_in_the_clipboard(filled):
    # The whole point of the two lists: 2,700 files would bury 800 copies.
    browse = Browse(filled)
    assert len(browse.entries()) == 2


def test_the_grid_is_the_whole_clipboard_not_just_the_pictures(filled):
    # It is the same history seen denser, so you can take in more of it at a
    # glance — a grid of only the images hides most of what you copied.
    browse = Browse(filled)
    browse.set_mode("grid")
    assert {e.source for e in browse.entries()} == {"clipboard"}
    assert {e.kind for e in browse.entries()} == {"text", "image"}


def test_the_screenshot_browser_is_the_folder(filled):
    browse = Browse(filled)
    browse.set_mode("screenshots")
    assert {e.source for e in browse.entries()} == {"screenshot"}


# -- one month at a time ---------------------------------------------------


def test_the_screenshot_browser_opens_on_its_newest_month(filled):
    # Never the whole folder. 2,700 files decoded at once is what made this
    # fall over, and the pictures you want are almost always the recent ones.
    browse = Browse(filled)
    browse.set_mode("screenshots")
    assert browse.month == browse.months()[0].key


def test_the_clipboard_is_not_held_to_a_month(filled):
    # A few hundred one-line rows cost nothing, and a clipboard you have to
    # navigate by date is not a clipboard.
    browse = Browse(filled)
    assert browse.month is None


def test_it_lists_the_months_there_are_to_choose_from(filled):
    browse = Browse(filled)
    browse.set_mode("screenshots")
    assert [m.key for m in browse.months()] == [m.key for m in
                                                filled.months(source="screenshot")]


def test_choosing_a_month_narrows_the_list(store, tmp_path):
    from datetime import datetime, timezone

    def at(year, month):
        return int(datetime(year, month, 5, tzinfo=timezone.utc).timestamp() * 1000)

    for name, when in (("june.png", at(2026, 6)), ("july.png", at(2026, 7))):
        shot = tmp_path / name
        shot.write_bytes(PNG + name.encode())
        store.add_file(shot, source="screenshot", mime="image/png", at_ms=when)

    browse = Browse(store)
    browse.set_mode("screenshots")
    browse.set_month((2026, 6))

    assert [e.path.rsplit("/", 1)[-1] for e in browse.entries()] == ["june.png"]


def test_a_month_of_nothing_is_an_empty_list_not_an_error(filled):
    browse = Browse(filled)
    browse.set_mode("screenshots")
    browse.set_month((1999, 1))
    assert browse.entries() == [] and browse.selected is None


def test_leaving_the_screenshot_browser_forgets_the_month(filled):
    browse = Browse(filled)
    browse.set_mode("screenshots")
    browse.set_mode("clipboard")
    assert browse.month is None


def test_searching_screenshots_looks_past_the_chosen_month(filled):
    # Typing is asking a question of the whole folder. Being silently answered
    # from one month of it is how you conclude a screenshot is gone.
    browse = Browse(filled)
    browse.set_mode("screenshots")
    browse.set_month((1999, 1))
    browse.set_query("shot")

    assert browse.month is None and browse.entries() != []


def test_the_newest_is_at_the_top(filled):
    clips = filled.recent(source="clipboard")
    assert clips[0].last_seen_ms >= clips[-1].last_seen_ms


# -- the filter box --------------------------------------------------------


def test_typing_narrows_the_list(filled):
    browse = Browse(filled)
    browse.set_query("copied")
    assert [e.text for e in browse.entries()] == ["a copied line"]


def test_the_filter_stays_inside_the_mode(filled, clock):
    # Searching the screenshot browser must not turn up clipboard entries.
    browse = Browse(filled)
    browse.set_mode("screenshots")
    browse.set_query("shot")
    assert {e.source for e in browse.entries()} == {"screenshot"}


def test_clearing_the_box_brings_everything_back(filled):
    browse = Browse(filled)
    browse.set_query("copied")
    browse.set_query("")
    assert len(browse.entries()) == 2


def test_a_query_that_matches_nothing_is_an_empty_list_not_an_error(filled):
    browse = Browse(filled)
    browse.set_query("no such thing anywhere")
    assert browse.entries() == [] and browse.selected is None


# -- the selection ---------------------------------------------------------


def test_the_top_entry_starts_selected(filled):
    browse = Browse(filled)
    assert browse.selected.id == filled.recent(source="clipboard")[0].id


def test_down_moves_down_the_list(filled):
    browse = Browse(filled)
    first = browse.selected.id
    browse.move(1)
    assert browse.selected.id != first


def test_up_at_the_top_stays_at_the_top(filled):
    # Nothing wraps. A list that jumps to the bottom when you overshoot is a
    # list you have to look at to use.
    browse = Browse(filled)
    browse.move(-1)
    assert browse.selected.id == filled.recent(source="clipboard")[0].id


def test_down_at_the_bottom_stays_at_the_bottom(filled):
    browse = Browse(filled)
    for _ in range(10):
        browse.move(1)
    assert browse.selected.id == filled.recent(source="clipboard")[-1].id


def test_typing_puts_the_selection_on_the_first_match(filled):
    browse = Browse(filled)
    browse.move(1)
    browse.set_query("copied")
    assert browse.selected.text == "a copied line"


def test_changing_mode_selects_the_top_of_the_new_list(filled):
    browse = Browse(filled)
    browse.set_mode("screenshots")
    assert browse.selected.source == "screenshot"


def test_the_selection_stays_on_the_same_entry_when_the_list_reloads(filled):
    # A copy landing while you are reading something must not move what you
    # are reading out from under you.
    browse = Browse(filled)
    browse.move(1)
    chosen = browse.selected.id
    filled.add(b"something new arrived", "text/plain")
    browse.reload()

    assert browse.selected.id == chosen


def test_deleting_the_selected_entry_selects_its_neighbour(filled):
    browse = Browse(filled)
    doomed = browse.selected.id
    browse.delete_selected()

    assert browse.selected is not None and browse.selected.id != doomed


def test_deleting_the_only_entry_leaves_nothing_selected(store):
    store.add(b"the only one", "text/plain")
    browse = Browse(store)
    browse.delete_selected()

    assert browse.entries() == [] and browse.selected is None


def test_a_delete_can_be_undone_and_comes_back_selected(filled):
    browse = Browse(filled)
    doomed = browse.selected.id
    browse.delete_selected()
    browse.undo()

    assert browse.selected.id == doomed


def test_undo_with_nothing_to_undo_does_nothing(filled):
    browse = Browse(filled)
    before = [e.id for e in browse.entries()]
    browse.undo()
    assert [e.id for e in browse.entries()] == before


def test_pinning_the_selection_sticks(filled):
    browse = Browse(filled)
    browse.pin_selected()
    assert browse.selected.pinned


def test_pinning_twice_unpins(filled):
    browse = Browse(filled)
    browse.pin_selected()
    browse.pin_selected()
    assert not browse.selected.pinned


# -- what the modes are ----------------------------------------------------


def test_the_modes_are_the_three_buttons_on_the_rail():
    assert Browse.MODES == ("clipboard", "grid", "screenshots")


def test_a_mode_that_does_not_exist_is_refused(filled):
    browse = Browse(filled)
    with pytest.raises(ValueError):
        browse.set_mode("nonsense")


def test_it_knows_where_the_selection_is_without_a_search(store):
    # The window used to find the selected row by scanning the whole list on
    # every keypress. Arrowing through two thousand screenshots is the case
    # that has to stay cheap.
    for text in ("one", "two", "three"):
        store.add(text.encode(), "text/plain")
    browse = Browse(store)
    browse.move(2)
    assert browse.position == 2
    assert browse.entries()[browse.position] is browse.selected


def test_the_position_of_nothing_is_nothing(store):
    assert Browse(store).position is None
