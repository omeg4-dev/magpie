"""Getting gtk4-layer-shell into the process, and only where it belongs."""

from magpie import preload


def test_only_the_window_needs_it():
    # LD_PRELOAD is inherited by every child, and the OCR job spawns thousands
    # of them. A batch of tesseract runs has no business loading a Wayland
    # layer-shell library.
    assert preload.wanted(["view"])
    assert preload.wanted(["view", "--mode", "starred"])
    assert not preload.wanted(["ocr"])
    assert not preload.wanted(["store"])
    assert not preload.wanted(["sync"])


def test_no_arguments_at_all_is_not_the_window():
    assert not preload.wanted([])
