"""Indexing the screenshot folder.

The screenshots are not copied anywhere — /mnt/xv/Random/Screenshots is a real
folder full of real files that other things (a file manager, an editor) also
use, so magpie indexes it where it lies and never writes to it.
"""

import os

from magpie.importers import import_screenshots

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40


def shot(root, name, data=PNG, mtime=None):
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_images_anywhere_under_the_folder_are_indexed(tmp_path, store):
    root = tmp_path / "Screenshots"
    shot(root, "2026-08/a.png")
    shot(root, "2022-01/b.jpg", JPEG)

    assert import_screenshots(store, root) == 2
    assert store.count(source="screenshot") == 2


def test_the_file_keeps_its_own_date(tmp_path, store):
    root = tmp_path / "Screenshots"
    shot(root, "a.png", mtime=1_600_000_000)
    import_screenshots(store, root)

    assert store.recent(source="screenshot")[0].first_seen_ms == 1_600_000_000_000


def test_things_that_are_not_images_are_left_alone(tmp_path, store):
    root = tmp_path / "Screenshots"
    shot(root, "a.png")
    shot(root, "notes.txt", b"hello")

    assert import_screenshots(store, root) == 1


def test_indexing_twice_adds_nothing(tmp_path, store):
    root = tmp_path / "Screenshots"
    shot(root, "a.png")
    import_screenshots(store, root)

    assert import_screenshots(store, root) == 0


def test_a_new_screenshot_is_picked_up_on_the_next_pass(tmp_path, store):
    root = tmp_path / "Screenshots"
    shot(root, "a.png")
    import_screenshots(store, root)
    shot(root, "b.png", JPEG)

    assert import_screenshots(store, root) == 1


def test_the_files_are_not_copied_into_the_store(tmp_path, store):
    root = tmp_path / "Screenshots"
    shot(root, "a.png")
    import_screenshots(store, root)

    assert list((store.root / "blobs").rglob("*.bin")) == []


def test_no_screenshot_folder_is_not_an_error(tmp_path, store):
    assert import_screenshots(store, tmp_path / "nothing-here") == 0


def test_two_screenshots_with_identical_bytes_stay_two_entries(tmp_path, store):
    # Same picture saved twice is still two files on disk, and a browser that
    # silently showed one of them would be lying about the folder.
    root = tmp_path / "Screenshots"
    shot(root, "a.png")
    shot(root, "b.png")

    assert import_screenshots(store, root) == 2
