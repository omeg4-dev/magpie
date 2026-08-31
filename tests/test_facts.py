"""What the pane under the preview says about the thing you are looking at.

One ellipsised line was fine for a copied string and useless for a picture: it
cut off exactly where the filename started, and never had room for the size of
the image in pixels, which is the first thing you want to know about one.
"""

from magpie.facts import lines
from magpie.store import Entry

#: 31 August 2026, 00:20 — the date on the screenshot these were written from.
_AUGUST_2026 = 1_788_128_400_000


def make(**kwargs) -> Entry:
    fields = dict(
        id=1, key="k", sha256="s", kind="text", mime="text/plain",
        source="clipboard", path=None, bytes=511, first_seen_ms=_AUGUST_2026, last_seen_ms=_AUGUST_2026, times_seen=1, starred=False,
        deleted_at_ms=None, time_approx=False, preview="hello", text="hello",
        ocr_ms=None)
    fields.update(kwargs)
    return Entry(**fields)


def test_a_copied_string_is_one_line():
    assert len(lines(make())) == 1


def test_that_line_says_when_what_and_how_big():
    said = lines(make())[0]
    assert "text/plain" in said and "511 B" in said and "2026" in said


def test_something_copied_more_than_once_says_so():
    assert "copied 3 times" in lines(make(times_seen=3))[0]


def test_a_reconstructed_time_admits_it():
    assert "reconstructed" in lines(make(time_approx=True))[0]


# -- pictures ---------------------------------------------------------------


def png(**kwargs) -> Entry:
    fields = dict(kind="image", mime="image/png", bytes=114_597,
                  preview="31-08-2026--00-20-26.png · 111.9 kB", text="")
    fields.update(kwargs)
    return make(**fields)


def test_a_picture_leads_with_its_size_in_pixels():
    # The first thing you want to know about an image, and the one thing the
    # old single line never had room for.
    assert lines(png(), dimensions=(1920, 1080))[0].startswith("1920 × 1080")


def test_a_picture_of_unknown_size_still_says_the_rest():
    assert "PNG" in lines(png())[0]


def test_a_screenshot_names_its_file_and_its_folder_on_separate_lines():
    said = lines(png(path="/mnt/xv/Random/Screenshots/2026-08/31-08-2026.png"))
    assert "31-08-2026.png" in said
    assert "/mnt/xv/Random/Screenshots/2026-08" in said


def test_a_pasted_image_has_no_file_lines():
    said = lines(png())
    assert not any(line.startswith("/") for line in said)


def test_the_pane_says_nothing_about_what_was_read():
    # The words OCR found are for the search box to match on, not for anyone
    # to read here: a quarter of a transcript under the picture told you
    # nothing you could not see in the picture itself.
    said = " ".join(lines(png(text="Total: 49,90 EUR", ocr_ms=1)))
    assert "Total" not in said
    assert "not read yet" not in said


def test_an_unread_picture_looks_like_any_other():
    assert lines(png(ocr_ms=None)) == lines(png(text="words", ocr_ms=1))
