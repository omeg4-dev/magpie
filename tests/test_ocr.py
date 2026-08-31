"""Reading the words off a picture.

Most of this desktop's screenshots are light text on a dark background, at a
scale meant for a 4K screen — which is the case tesseract is worst at out of
the box, and the case this module is built for. Nothing here shells out: the
runner is injected, so what the tests pin down is *what would be run* and what
is made of the answer.
"""

import pytest

from magpie import ocr


class Fake:
    """Stands in for magick and tesseract, and remembers what it was asked."""

    def __init__(self, mean=0.5, size=(1920, 1080), text="hello world"):
        self.calls: list[list[str]] = []
        self.mean, self.size = mean, size
        self.text = text

    def __call__(self, argv, data=b""):
        self.calls.append(argv)
        if "info:" in argv:
            return f"{self.size[0]} {self.size[1]} {self.mean}".encode()
        if argv[0] == "tesseract":
            text = self.text(argv) if callable(self.text) else self.text
            return text.encode()
        return b"prepared-image-bytes"

    def argv_for(self, program):
        return [a for a in self.calls if a and a[0] == program]


def test_it_reads_the_words_out():
    assert ocr.read(b"png bytes", run=Fake(text="an invoice")) == "an invoice"


def test_a_dark_screenshot_is_turned_the_right_way_up():
    # Light text on black is the hard case for the enlarged variants: the
    # sharpening and the stretch both assume ink on paper.
    fake = Fake(mean=0.12)
    ocr.read(b"png bytes", run=fake)
    assert any("-negate" in argv for argv in fake.argv_for("magick"))


def test_a_light_screenshot_is_never_inverted():
    fake = Fake(mean=0.88)
    ocr.read(b"png bytes", run=fake)
    assert not any("-negate" in argv for argv in fake.argv_for("magick"))


def test_the_picture_is_flattened_before_anything_else():
    # A screenshot is RGBA, and inverting a transparent pixel makes the whole
    # picture one flat colour that reads as nothing at all.
    fake = Fake()
    ocr.read(b"png bytes", run=fake)
    for argv in fake.argv_for("magick")[1:]:
        assert "-alpha" in argv


def test_it_is_read_as_it_is_as_well_as_enlarged():
    # Tesseract is often better on the plain picture than on any amount of
    # help, and which one wins cannot be told from the bytes.
    fake = Fake()
    ocr.read(b"png bytes", run=fake)
    prepares = fake.argv_for("magick")[1:]
    assert any("-resize" not in argv for argv in prepares)
    assert any("-resize" in argv for argv in prepares)


def test_a_small_picture_is_tripled_as_well():
    fake = Fake(size=(600, 400))
    ocr.read(b"png bytes", run=fake)
    assert any("300%" in argv for argv in fake.argv_for("magick"))


def test_a_full_screen_is_not_tripled():
    # Twelve thousand pixels across, to read the same words.
    fake = Fake(size=(3840, 2160))
    ocr.read(b"png bytes", run=fake)
    assert not any("300%" in argv for argv in fake.argv_for("magick"))


def test_it_reads_in_the_languages_this_machine_has():
    fake = Fake()
    ocr.read(b"png bytes", run=fake)
    argv = fake.argv_for("tesseract")[0]
    assert argv[argv.index("-l") + 1] == ocr.languages()


def test_it_tries_more_than_one_layout_and_keeps_the_best():
    # A screenshot of a terminal and a screenshot of a web page want different
    # page-segmentation modes, and you cannot tell which is which up front.
    def by_psm(argv):
        psm = argv[argv.index("--psm") + 1]
        return "a b c" if psm == "3" else "the quick brown fox jumped over"

    fake = Fake(text=by_psm)
    assert ocr.read(b"png bytes", run=fake) == "the quick brown fox jumped over"
    assert len(fake.argv_for("tesseract")) > 1


def test_a_picture_it_cannot_read_is_not_an_exception():
    def broken(argv, data=b""):
        raise OSError("tesseract is not installed")

    assert ocr.read(b"png bytes", run=broken) == ""


def test_a_picture_with_nothing_in_it_reads_as_nothing():
    assert ocr.read(b"png bytes", run=Fake(text="   \n\n  ")) == ""


# -- what is made of the answer ---------------------------------------------


def test_lines_of_speckle_are_thrown_away():
    # OCR on a photograph produces pages of this, and every one of them is a
    # false match the next time you search for something.
    assert ocr.clean("| ~~ .-'\ni\nthe monthly invoice") == "the monthly invoice"


def test_real_lines_are_kept_as_they_were():
    assert ocr.clean("Total: 49,90 EUR") == "Total: 49,90 EUR"


def test_runs_of_spaces_become_one():
    assert ocr.clean("Name       Size") == "Name Size"


def test_blank_lines_do_not_pile_up():
    assert ocr.clean("first\n\n\n\nsecond") == "first\nsecond"


def test_a_line_of_symbols_is_not_words():
    assert ocr.clean("=== ### ---") == ""


def test_short_words_are_kept_when_they_are_in_a_sentence():
    assert "of" in ocr.clean("a slice of the whole thing")


@pytest.mark.parametrize("worse, better", [
    ("a b c", "invoice from the electricity people"),
    ("", "one two three"),
    ("|||| ....", "hello there friend"),
])
def test_the_wordier_reading_scores_higher(worse, better):
    assert ocr.score(ocr.clean(better)) > ocr.score(ocr.clean(worse))


# -- the languages this machine actually has --------------------------------


def test_it_asks_for_the_languages_that_are_installed():
    have = lambda: {"eng", "deu", "osd"}
    assert ocr.languages(installed=have) == "eng+deu"


def test_a_missing_language_is_dropped_rather_than_fatal():
    # `-l eng+deu` on a machine without the German data fails outright, and
    # every screenshot would come back empty.
    assert ocr.languages(installed=lambda: {"eng"}) == "eng"


def test_english_is_asked_for_even_if_nothing_is_installed():
    assert ocr.languages(installed=lambda: set()) == "eng"
