"""Putting an entry back on the clipboard.

The one thing the viewer exists to do, so the shape of the wl-copy call is
worth pinning down: the wrong mime turns a copied PNG into a paste of binary
rubbish in the next text field.
"""

from magpie.paste import to_clipboard

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


class Recorder:
    """Stands in for wl-copy."""

    def __init__(self):
        self.calls = []

    def __call__(self, argv, data):
        self.calls.append((argv, data))
        return 0


def test_text_goes_back_as_text(store):
    entry = store.add(b"a copied line", "text/plain")
    run = Recorder()
    to_clipboard(store, entry, run)

    argv, data = run.calls[0]
    assert data == b"a copied line"
    assert argv[:1] == ["wl-copy"] and "text/plain" in argv


def test_an_image_goes_back_as_its_own_type(store):
    entry = store.add(PNG, "image/png")
    run = Recorder()
    to_clipboard(store, entry, run)

    argv, data = run.calls[0]
    assert data == PNG and "image/png" in argv


def test_the_charset_is_not_passed_through_as_a_type(store):
    # wl-copy wants a mime type, not a mime header.
    entry = store.add(b"hello", "text/plain;charset=utf-8")
    run = Recorder()
    to_clipboard(store, entry, run)

    assert "text/plain;charset=utf-8" not in run.calls[0][0]
    assert "text/plain" in run.calls[0][0]


def test_a_screenshot_is_copied_from_the_file_on_disk(store, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)
    entry = store.add_file(shot, source="screenshot", mime="image/png")
    run = Recorder()
    to_clipboard(store, entry, run)

    assert run.calls[0][1] == PNG


def test_copying_does_not_mark_the_clipboard_sensitive(store):
    # The watcher drops sensitive offers, so a copy from the viewer that set
    # that flag would vanish from the history the moment it was made.
    entry = store.add(b"hello", "text/plain")
    run = Recorder()
    to_clipboard(store, entry, run)

    assert "--sensitive" not in run.calls[0][0]


def test_it_says_whether_it_worked(store):
    entry = store.add(b"hello", "text/plain")
    assert to_clipboard(store, entry, lambda argv, data: 0) is True
    assert to_clipboard(store, entry, lambda argv, data: 1) is False


def test_a_missing_file_is_a_failure_not_a_crash(store, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)
    entry = store.add_file(shot, source="screenshot", mime="image/png")
    shot.unlink()

    assert to_clipboard(store, entry, Recorder()) is False
