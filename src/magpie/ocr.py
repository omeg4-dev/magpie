"""Reading the words off a picture.

A screenshot is a document you cannot search, which is the whole problem with
a folder of three thousand of them. This turns each one into words the index
can hold, and it is deliberately slow: a screenshot is read once and searched
for years, so a second of CPU to read it properly is a bargain and half a
second to read it badly is a waste.

Three things make the difference on *this* desktop's screenshots, and they are
why this is not simply `tesseract file.png`:

**Polarity.** Nearly everything here is light text on a dark background, and
tesseract is trained on ink on paper. Inverting a dark screenshot is the single
biggest improvement there is — the difference between a transcript and a page
of nonsense.

**Scale.** Small pictures — a cropped dialog, a phone screenshot — are doubled
first. Tesseract wants roughly 30 pixels of cap height and gives up well below
that.

**Layout.** A terminal, a web page and a chat window want different page
segmentation, and there is no telling which is which from the bytes. So it is
read more than once, and the wordiest answer wins.

Then the answer is cleaned. OCR on a photograph produces pages of speckle, and
every line of it is a false match the next time you search for something.
"""

from __future__ import annotations

import re
import subprocess
import sys
from functools import lru_cache

__all__ = ["read", "clean", "score", "languages", "read_later"]

#: Both, in one pass. This clipboard is half German and tesseract is perfectly
#: happy to be given two dictionaries at once — but only if they are installed,
#: and `-l eng+deu` without the German data fails outright rather than falling
#: back, which would empty every reading on a machine that lacks it.
WANTED = ("eng", "deu")

#: Page segmentation modes to try. 3 is "a page, work it out"; 6 is "one block
#: of uniform text", which is what a terminal or an editor actually is and
#: which 3 regularly breaks into columns.
LAYOUTS = (3, 6)

#: Under this many pixels across, a picture is small enough to be worth
#: tripling. Tesseract wants roughly thirty pixels of cap height.
SMALL = 1400

#: Below this mean brightness the picture is dark, and the enlarged variants
#: are inverted.
DARK = 0.5

#: How long one picture gets. A 4K screenshot takes a second or two; a minute
#: means something has gone wrong and the backlog should move on.
TIMEOUT = 60

#: Onto a flat grey background first, always. A screenshot is RGBA, and
#: everything after this — inverting most of all — treats a transparent pixel
#: as a black one and turns the whole picture into a single flat colour. This
#: was worth an entire afternoon.
FLATTEN = ["-background", "black", "-alpha", "remove", "-alpha", "off",
           "-colorspace", "Gray", "-depth", "8"]

_WORD = re.compile(r"[^\W\d_]{2,}", re.UNICODE)
_ALNUM = re.compile(r"[^\W_]", re.UNICODE)


@lru_cache(maxsize=1)
def installed() -> set[str]:
    """Which language packs tesseract has, asked once."""
    try:
        out = subprocess.run(["tesseract", "--list-langs"], stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, timeout=TIMEOUT).stdout
    except (OSError, subprocess.SubprocessError):
        return set()
    return {line.strip() for line in out.decode("utf-8", "replace").splitlines()}


def languages(installed=installed) -> str:
    """The `-l` argument for this machine. English is asked for regardless."""
    have = installed()
    return "+".join(want for want in WANTED if want in have) or "eng"


def _run(argv: list[str], data: bytes = b"") -> bytes:
    done = subprocess.run(argv, input=data, stdout=subprocess.PIPE,
                          stderr=subprocess.DEVNULL, timeout=TIMEOUT)
    return done.stdout


def _spawn(argv: list[str]) -> None:
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)


def read_later(entry_id: int, run=_spawn) -> None:
    """Read this picture in the background, now rather than on the hour.

    A screenshot you just copied is the one you are most likely to search for
    in the next minute, and waiting for the hourly job to come round means the
    preview says "not read yet" about the only picture you care about. It is
    nice'd because it happens while you are still working in the window you
    copied from, and detached because `magpie store` is wl-paste's child and
    must not hold the clipboard watcher open.
    """
    try:
        run(["nice", "-n", "19", sys.executable, "-m", "magpie",
             "ocr-one", str(entry_id)])
    except OSError:
        pass  # the copy is stored; the reading is a convenience


def read(data: bytes, run=_run) -> str:
    """Every word this picture has in it, or "" — never an exception.

    The picture is prepared several ways and read several ways, and the
    wordiest answer wins. That is six runs of tesseract for one screenshot,
    which is absurd for a keystroke and perfectly reasonable for a thing done
    once to a file you will search for the next five years — no two of these
    variants win on the same kind of picture, and there is nothing in the bytes
    that says which kind you have.

    A picture that cannot be read is a picture with no words in it as far as
    the index is concerned; it is not a reason to stop the backlog.
    """
    try:
        width, _height, mean = _describe(data, run)
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return ""

    best = ""
    for recipe in _variants(width, mean):
        try:
            prepared = run(["magick", "-", *recipe, "png:-"], data)
        except (OSError, subprocess.SubprocessError):
            continue
        for layout in LAYOUTS:
            try:
                out = run(_tesseract_argv(layout), prepared)
            except (OSError, subprocess.SubprocessError):
                continue
            text = clean(out.decode("utf-8", "replace"))
            if score(text) > score(best):
                best = text
    return best


def _variants(width: int, mean: float) -> list[list[str]]:
    """The ways this particular picture is worth preparing.

    *As it is* — flattened and grey, nothing else. Tesseract 5 is better at
    small clean text than any amount of help, and this wins often enough that
    dropping it costs readings.

    *Enlarged* — doubled, sharpened and contrast-stretched, inverted first if
    the picture is dark. This is the one that reads a dark UI at 100% scale.

    *Enlarged further* — tripled, for pictures small enough that their text is
    below what tesseract can resolve at all. Skipped on a full screen, where it
    would mean a twelve-thousand-pixel bitmap for nothing.
    """
    upright = ["-negate"] if mean < DARK else []
    bigger = ["-filter", "Lanczos", "-resize"]
    sharper = ["-unsharp", "0x1+0.7+0"]
    variants = [
        list(FLATTEN),
        FLATTEN + upright + bigger + ["200%"] + sharper + ["-contrast-stretch", "2x2%"],
    ]
    if width < SMALL:
        variants.append(FLATTEN + upright + bigger + ["300%"] + sharper)
    return variants


def _describe(data: bytes, run) -> tuple[int, int, float]:
    """Width, height and mean brightness, in one pass over the file."""
    out = run(["magick", "-", "-format", "%w %h %[fx:mean]", "info:"], data)
    width, height, mean = out.decode("utf-8", "replace").split()[:3]
    return int(width), int(height), float(mean)


def _tesseract_argv(layout: int) -> list[str]:
    return ["tesseract", "stdin", "stdout", "-l", languages(),
            "--oem", "1",              # the LSTM engine, not the 2010 one
            "--psm", str(layout),
            "-c", "preserve_interword_spaces=1"]


def clean(text: str) -> str:
    """Keep the lines that are words and throw away the speckle."""
    kept = []
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if _is_words(line):
            kept.append(line)
    return "\n".join(kept)


def _is_words(line: str) -> bool:
    """Whether this line is language rather than the edge of a photograph."""
    if len(line) < 3:
        return False
    letters = len(_ALNUM.findall(line))
    if letters < 3 or letters / len(line) < 0.5:
        return False
    return bool(_WORD.search(line))


def score(text: str) -> int:
    """How much of a reading this is, for choosing between two of them."""
    return sum(len(word) for word in _WORD.findall(text))
