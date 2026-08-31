"""What gets taken from the clipboard, and what deliberately does not."""

import pytest

from magpie.capture import MAX_BYTES, capture, sniff

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
GIF = b"GIF89a" + b"\x00" * 40
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"\x00" * 40


@pytest.mark.parametrize("data, mime", [
    (PNG, "image/png"),
    (JPEG, "image/jpeg"),
    (GIF, "image/gif"),
    (WEBP, "image/webp"),
    ("hello".encode(), "text/plain"),
    ("café ☕".encode(), "text/plain"),
    (b"file:///home/user/a.txt\n", "text/uri-list"),
    (b"\x00\x01\x02\xff nonsense", "application/octet-stream"),
])
def test_the_type_is_read_off_the_bytes(data, mime):
    # wl-paste hands over bytes with no mime attached, so the bytes have to say.
    assert sniff(data) == mime


def test_a_copy_is_stored(store):
    entry = capture(store, b"ssh root@dietpi")
    assert store.recent()[0].id == entry.id


def test_a_password_manager_copy_is_not_stored(store):
    # wl-paste sets CLIPBOARD_STATE=sensitive for offers marked as such. A
    # history that keeps those is a liability, not a feature.
    assert capture(store, b"hunter2", state="sensitive") is None
    assert store.recent() == []


def test_clearing_the_clipboard_stores_nothing(store):
    assert capture(store, b"", state="clear") is None
    assert store.recent() == []


def test_an_empty_copy_is_ignored(store):
    assert capture(store, b"") is None


def test_whitespace_alone_is_ignored(store):
    assert capture(store, b"   \n\t ") is None


def test_whitespace_inside_real_text_is_kept(store):
    assert capture(store, b"  indented code\n") is not None


def test_something_enormous_is_refused(store):
    assert capture(store, b"x" * (MAX_BYTES + 1)) is None


def test_an_image_keeps_its_bytes(store):
    entry = capture(store, PNG)
    assert entry.kind == "image" and store.payload(entry) == PNG
