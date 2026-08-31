"""The store: what magpie keeps, and what it can find again.

Everything the clipboard ever held goes in here and nothing falls off the end,
so the two things that matter are that a repeat costs nothing and that a
million entries are still searchable.
"""

PNG = (b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)


def test_a_copied_string_comes_back(store):
    entry = store.add(b"ssh root@192.0.2.26", "text/plain")
    assert store.get(entry.id).text == "ssh root@192.0.2.26"


def test_the_bytes_come_back_exactly(store):
    entry = store.add(PNG, "image/png")
    assert store.payload(entry) == PNG


def test_copying_the_same_thing_twice_is_one_entry(store, clock):
    first = store.add(b"hello", "text/plain")
    clock.advance(5_000)
    again = store.add(b"hello", "text/plain")

    assert again.id == first.id
    assert len(store.recent()) == 1
    assert again.times_seen == 2


def test_a_repeat_moves_to_the_top(store, clock):
    old = store.add(b"first", "text/plain")
    clock.advance(1_000)
    store.add(b"second", "text/plain")
    clock.advance(1_000)
    store.add(b"first", "text/plain")

    assert [e.id for e in store.recent()][0] == old.id


def test_a_repeat_keeps_the_moment_it_first_appeared(store, clock):
    first = store.add(b"hello", "text/plain")
    clock.advance(5_000)
    again = store.add(b"hello", "text/plain")

    assert again.first_seen_ms == first.first_seen_ms
    assert again.last_seen_ms == first.first_seen_ms + 5_000


def test_the_newest_thing_is_first(store, clock):
    for word in (b"one", b"two", b"three"):
        store.add(word, "text/plain")
        clock.advance(1_000)

    assert [e.text for e in store.recent()] == ["three", "two", "one"]


def test_identical_bytes_are_stored_once(store):
    a = store.add(PNG, "image/png")
    store.delete(a.id)
    b = store.add(PNG, "image/png")

    assert store.payload(b) == PNG
    assert len(list((store.root / "blobs").rglob("*"))) == 2  # one shard, one blob


# -- finding things --------------------------------------------------------


def test_search_finds_a_word_from_the_middle(store):
    store.add(b"the quick brown fox", "text/plain")
    store.add(b"nothing to do with it", "text/plain")

    assert [e.text for e in store.search("brown")] == ["the quick brown fox"]


def test_search_ignores_case(store):
    store.add(b"Hyprland", "text/plain")
    assert len(store.search("hyprland")) == 1


def test_search_survives_punctuation_in_the_query(store):
    # A clipboard is full of URLs and paths, and typing one into the box must
    # not be read as FTS5 syntax.
    store.add(b"https://github.com/omega/magpie", "text/plain")
    assert len(store.search("github.com/omega")) == 1


def test_an_empty_query_is_the_recent_list(store):
    store.add(b"one", "text/plain")
    assert len(store.search("")) == 1


def test_search_does_not_return_deleted_entries(store):
    entry = store.add(b"a mistake", "text/plain")
    store.delete(entry.id)

    assert store.search("mistake") == []


def test_text_added_later_becomes_searchable(store):
    # This is how OCR reaches the index: the image is stored first and read
    # minutes later.
    entry = store.add(PNG, "image/png")
    store.set_text(entry.id, "a screenshot of a terminal")

    assert [e.id for e in store.search("terminal")] == [entry.id]


def test_search_can_be_narrowed_to_images(store):
    store.add(b"a terminal window", "text/plain")
    image = store.add(PNG, "image/png")
    store.set_text(image.id, "a terminal window")

    assert [e.id for e in store.search("terminal", kind="image")] == [image.id]


# -- keeping and losing things ---------------------------------------------


def test_deleting_hides_an_entry_without_losing_it(store):
    entry = store.add(b"oops", "text/plain")
    store.delete(entry.id)

    assert store.recent() == []
    assert store.get(entry.id).deleted_at_ms is not None


def test_a_delete_can_be_undone(store):
    entry = store.add(b"oops", "text/plain")
    store.delete(entry.id)
    store.restore(entry.id)

    assert [e.id for e in store.recent()] == [entry.id]


def test_purging_drops_what_was_deleted_long_ago(store, clock):
    entry = store.add(b"gone", "text/plain")
    store.delete(entry.id)
    clock.advance(31 * 86_400_000)
    store.purge(after_ms=30 * 86_400_000)

    assert store.get(entry.id) is None


def test_purging_leaves_a_recent_delete_alone(store, clock):
    entry = store.add(b"gone", "text/plain")
    store.delete(entry.id)
    clock.advance(86_400_000)
    store.purge(after_ms=30 * 86_400_000)

    assert store.get(entry.id) is not None


def test_purging_takes_the_bytes_with_it(store, clock):
    entry = store.add(PNG, "image/png")
    store.delete(entry.id)
    clock.advance(31 * 86_400_000)
    store.purge(after_ms=30 * 86_400_000)

    assert list((store.root / "blobs").rglob("*.bin")) == []


# -- what an entry is ------------------------------------------------------


def test_an_image_is_recognised_as_one(store):
    assert store.add(PNG, "image/png").kind == "image"


def test_text_is_recognised_as_text(store):
    assert store.add(b"plain", "text/plain;charset=utf-8").kind == "text"


def test_a_pasted_file_list_is_recognised(store):
    entry = store.add(b"file:///home/user/a.txt\n", "text/uri-list")
    assert entry.kind == "files"


def test_an_image_previews_as_its_size_not_its_bytes(store):
    # The list shows the preview, so it must never be a screenful of PNG.
    entry = store.add(PNG, "image/png")
    assert "PNG" in entry.preview and "\x89" not in entry.preview


def test_a_long_string_previews_to_one_line(store):
    entry = store.add(("a" * 500 + "\nsecond line").encode(), "text/plain")
    assert "\n" not in entry.preview and len(entry.preview) <= 200


def test_the_full_text_is_kept_even_when_the_preview_is_short(store):
    body = "a" * 500
    entry = store.add(body.encode(), "text/plain")
    assert store.get(entry.id).text == body


def test_undecodable_bytes_do_not_crash_the_store(store):
    entry = store.add(b"\xff\xfe\x00garbage", "application/octet-stream")
    assert entry.kind == "binary" and entry.text == ""


# -- files that live somewhere else ----------------------------------------


def test_a_screenshot_is_indexed_where_it_lies(store, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)

    entry = store.add_file(shot, source="screenshot", mime="image/png")

    assert entry.source == "screenshot"
    assert entry.path == str(shot)
    assert store.payload(entry) == PNG
    assert list((store.root / "blobs").rglob("*.bin")) == [], "not copied into the store"


def test_indexing_the_same_screenshot_twice_is_one_entry(store, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)

    first = store.add_file(shot, source="screenshot", mime="image/png")
    again = store.add_file(shot, source="screenshot", mime="image/png")

    assert first.id == again.id


def test_a_screenshot_and_the_same_image_copied_are_separate(store, tmp_path):
    # Same bytes, two different things: one is a file you can reveal in a file
    # manager, the other is a moment in the clipboard's history.
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)

    copied = store.add(PNG, "image/png")
    indexed = store.add_file(shot, source="screenshot", mime="image/png")

    assert copied.id != indexed.id


def test_the_screenshot_browser_can_be_listed_on_its_own(store, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)
    store.add(b"clipboard text", "text/plain")
    store.add_file(shot, source="screenshot", mime="image/png")

    assert [e.source for e in store.recent(source="screenshot")] == ["screenshot"]


def test_a_screenshot_that_has_been_deleted_from_disk_is_dropped(store, tmp_path):
    shot = tmp_path / "shot.png"
    shot.write_bytes(PNG)
    entry = store.add_file(shot, source="screenshot", mime="image/png")
    shot.unlink()

    store.forget_missing_files()

    assert store.get(entry.id) is None


# -- surviving a restart ---------------------------------------------------


def test_the_store_reopens_on_what_is_already_there(tmp_path, clock):
    from magpie.store import Store

    root = tmp_path / "store"
    entry = Store(root, clock=clock).add(b"remembered", "text/plain")

    assert Store(root, clock=clock).get(entry.id).text == "remembered"


def test_counting_is_cheap_enough_to_show(store):
    for i in range(20):
        store.add(f"line {i}".encode(), "text/plain")
    assert store.count() == 20


# -- starring ---------------------------------------------------------------


def test_a_starred_entry_says_so(store):
    entry = store.add(b"keep this", "text/plain")
    store.star(entry.id)
    assert store.get(entry.id).starred


def test_starring_can_be_undone(store):
    entry = store.add(b"keep this", "text/plain")
    store.star(entry.id)
    store.star(entry.id, False)
    assert not store.get(entry.id).starred


def test_the_starred_list_is_only_the_starred_ones(store):
    kept = store.add(b"kept", "text/plain")
    store.add(b"passing through", "text/plain")
    store.star(kept.id)
    assert [e.id for e in store.recent(starred=True)] == [kept.id]


def test_starred_things_are_still_in_the_clipboard(store):
    # Starring is a bookmark, not a move: the entry stays where it was.
    kept = store.add(b"kept", "text/plain")
    store.star(kept.id)
    assert kept.id in [e.id for e in store.recent()]


def test_searching_can_be_narrowed_to_the_starred_ones(store):
    kept = store.add(b"alpha kept", "text/plain")
    store.add(b"alpha passing", "text/plain")
    store.star(kept.id)
    assert [e.id for e in store.search("alpha", starred=True)] == [kept.id]


def test_a_starred_entry_survives_the_purge(store, clock):
    entry = store.add(b"keep this", "text/plain")
    store.star(entry.id)
    store.delete(entry.id)
    clock.advance(60 * 86_400_000)
    store.purge()
    assert store.get(entry.id) is not None


def test_a_store_written_before_the_rename_still_opens(tmp_path):
    # The column was called `pinned` for the first few weeks. Losing a
    # clipboard to a renamed column would be an absurd way to lose one.
    import sqlite3

    from magpie.store import Store

    Store(tmp_path)  # make it, then put it back the way it was
    db = sqlite3.connect(tmp_path / "magpie.db", isolation_level=None)
    db.execute("ALTER TABLE entry RENAME COLUMN starred TO pinned")
    db.execute("INSERT INTO entry (key, sha256, kind, mime, source, bytes,"
               " first_seen_ms, last_seen_ms, pinned, preview)"
               " VALUES ('k','s','text','text/plain','clipboard',1,1,1,1,'old')")
    db.close()

    store = Store(tmp_path)
    assert store.recent()[0].starred


# -- what still needs reading ------------------------------------------------


def test_images_are_offered_up_for_reading(store, png):
    image = store.add(png, "image/png")
    store.add(b"words already", "text/plain")
    assert [e.id for e in store.unread_images()] == [image.id]


def test_an_image_that_has_been_read_is_not_offered_again(store, png):
    image = store.add(png, "image/png")
    store.set_ocr(image.id, "some words")
    assert store.unread_images() == []


def test_an_image_with_nothing_in_it_is_not_offered_again_either(store, png):
    # Most screenshots of a video have no text in them at all. Reading one
    # every hour for ever is how a background job becomes a space heater.
    image = store.add(png, "image/png")
    store.set_ocr(image.id, "")
    assert store.unread_images() == []


def test_what_was_read_can_be_searched_for(store, png):
    image = store.add(png, "image/png")
    store.set_ocr(image.id, "invoice from the electricity people")
    assert [e.id for e in store.search("electricity")] == [image.id]


def test_the_newest_images_are_read_first(store, png):
    old = store.add(png, "image/png", at_ms=1_000)
    new = store.add(png + b"\x00", "image/png", at_ms=2_000)
    assert [e.id for e in store.unread_images()] == [new.id, old.id]
