"""Cutting text down to what a tile can hold.

Relying on the label to clip did not work — an overlaid label draws at its
natural height and runs off the bottom of the card and over the tiles below. So
the text is cut to fit before it is ever handed to GTK, which is also the only
version of this that is testable.
"""

from magpie.shape import to_tile


def test_short_text_is_left_alone():
    assert to_tile("hello", lines=3, width=20) == "hello"


def test_it_keeps_no_more_lines_than_asked_for():
    assert to_tile("a\nb\nc\nd\ne", lines=3, width=20).count("\n") == 2


def test_text_longer_than_the_tile_fills_it_and_is_marked():
    cut = to_tile("x" * 100, lines=3, width=20)
    assert cut.count("\n") == 2, "it should use all three lines"
    assert cut.endswith("…"), "and say there was more"


def test_a_line_that_just_fits_is_not_marked():
    assert to_tile("x" * 20, lines=3, width=20) == "x" * 20


def test_leading_blank_lines_are_dropped():
    # A copied paragraph often starts with a newline, and a tile that opens
    # with two blank lines wastes half of itself.
    assert to_tile("\n\nreal content", lines=3, width=20) == "real content"


def test_a_run_of_blank_lines_inside_becomes_one():
    assert to_tile("a\n\n\n\nb", lines=5, width=20) == "a\n\nb"


def test_tabs_do_not_blow_the_width_out():
    assert "\t" not in to_tile("a\tb", lines=3, width=20)


def test_text_that_was_cut_short_says_so():
    cut = to_tile("\n".join("line" for _ in range(20)), lines=3, width=20)
    assert cut.endswith("…")


def test_nothing_in_is_nothing_out():
    assert to_tile("", lines=3, width=20) == ""
    assert to_tile("   \n  ", lines=3, width=20) == ""


def test_a_long_line_wraps_into_the_lines_below_it():
    # A copied paragraph is one very long line. Truncating it to the first
    # twenty characters wastes six sevenths of the tile.
    out = to_tile("word " * 40, lines=4, width=20)
    assert out.count("\n") == 3
    assert all(len(line) <= 20 for line in out.split("\n"))


def test_wrapping_breaks_between_words_where_it_can():
    out = to_tile("alpha beta gamma delta", lines=3, width=12)
    assert out.split("\n")[0] == "alpha beta"


def test_a_long_unbroken_run_is_split_anyway():
    # A URL or a base64 blob has nowhere to break, and must still fill lines
    # rather than vanish.
    out = to_tile("x" * 60, lines=3, width=20)
    assert out.split("\n")[0] == "x" * 20


def test_explicit_line_breaks_are_still_kept():
    out = to_tile("first\nsecond", lines=4, width=20)
    assert out.split("\n")[:2] == ["first", "second"]
