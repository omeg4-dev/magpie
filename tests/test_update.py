"""Working out the smallest change that turns one list into the other.

Handing GTK a whole new list costs about ninety milliseconds however similar it
is to the one already there, because the view rebuilds every row it is holding.
Handing it "two new ones at the top" costs about one. Almost every refresh in
this program is that second thing — you opened the window again, and two things
have been copied since.
"""

from magpie.update import plan


def test_the_same_list_is_no_work_at_all():
    assert plan([1, 2, 3], [1, 2, 3]) == ("keep", 0, 0)


def test_new_copies_arrive_at_the_top():
    # The clipboard is newest-first, so a copy is an insert at zero.
    assert plan([1, 2, 3], [9, 8, 1, 2, 3]) == ("insert", 0, 2)


def test_entries_falling_off_the_top_are_a_removal():
    assert plan([9, 8, 1, 2, 3], [1, 2, 3]) == ("remove", 0, 2)


def test_a_deletion_in_the_middle_is_a_removal_there():
    assert plan([1, 2, 3, 4], [1, 2, 4]) == ("remove", 2, 1)


def test_an_insertion_in_the_middle_is_an_insertion_there():
    assert plan([1, 2, 4], [1, 2, 3, 4]) == ("insert", 2, 1)


def test_a_different_list_is_a_replacement():
    assert plan([1, 2, 3], [7, 8, 9])[0] == "replace"


def test_a_reordering_is_a_replacement():
    # Pinning moves a row without adding one, and there is no cheap splice
    # that expresses that.
    assert plan([1, 2, 3], [3, 1, 2])[0] == "replace"


def test_filling_an_empty_list_is_an_insertion():
    assert plan([], [1, 2]) == ("insert", 0, 2)


def test_emptying_a_list_is_a_removal():
    assert plan([1, 2], []) == ("remove", 0, 2)


def test_two_empty_lists_need_nothing():
    assert plan([], []) == ("keep", 0, 0)


def test_changes_at_both_ends_are_a_replacement():
    # One splice cannot both add at the top and remove at the bottom.
    assert plan([1, 2, 3], [9, 1, 2])[0] == "replace"
