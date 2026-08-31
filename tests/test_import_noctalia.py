"""Bringing Noctalia's clipboard history across.

It runs once, on first start, and then again harmlessly every start — the point
is that magpie begins with the history you already had rather than an empty
list on day one.
"""

import json

import pytest

from magpie.importers import import_noctalia

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40


class Noctalia:
    """A stand-in for ~/.local/state/noctalia/clipboard, shaped like the real one."""

    def __init__(self, root):
        self.root = root
        (root / "entries").mkdir(parents=True)

    def write(self, entry_id, data, mime, at_ms, pinned=False, preview=""):
        payload = self.root / "entries" / f"{entry_id}.bin"
        payload.write_bytes(data)
        return {"id": entry_id, "byte_size": len(data), "captured_at_ms": at_ms,
                "data_mime_type": mime, "mime_types": [mime],
                "payload_path": str(payload), "pinned": pinned,
                "text_preview": preview}

    def save(self, entries):
        (self.root / "index.json").write_text(json.dumps({"entries": entries}))

    def __truediv__(self, name):
        return self.root / name

    def __fspath__(self):
        return str(self.root)


@pytest.fixture
def noctalia(tmp_path):
    return Noctalia(tmp_path / "noctalia")


def test_every_entry_comes_across(noctalia, store):
    noctalia.save([
        noctalia.write("1-0", b"first", "text/plain;charset=utf-8", 1_000, preview="first"),
        noctalia.write("2-0", PNG, "image/png", 2_000),
    ])

    assert import_noctalia(store, noctalia) == 2
    assert store.count() == 2


def test_an_entry_keeps_the_moment_noctalia_saw_it(noctalia, store):
    noctalia.save([noctalia.write("1-0", b"first", "text/plain", 1_700_000_000_000)])
    import_noctalia(store, noctalia)

    assert store.recent()[0].first_seen_ms == 1_700_000_000_000


def test_a_star_comes_across_with_it(noctalia, store):
    noctalia.save([noctalia.write("1-0", b"key", "text/plain", 1_000, pinned=True)])
    import_noctalia(store, noctalia)

    assert store.recent()[0].starred


def test_the_payload_comes_across_intact(noctalia, store):
    noctalia.save([noctalia.write("1-0", PNG, "image/png", 1_000)])
    import_noctalia(store, noctalia)

    assert store.payload(store.recent()[0]) == PNG


def test_importing_twice_adds_nothing(noctalia, store):
    noctalia.save([noctalia.write("1-0", b"first", "text/plain", 1_000)])
    import_noctalia(store, noctalia)

    assert import_noctalia(store, noctalia) == 0
    assert store.count() == 1


def test_an_entry_whose_payload_is_gone_is_skipped(noctalia, store):
    entry = noctalia.write("1-0", b"first", "text/plain", 1_000)
    (noctalia / "entries" / "1-0.bin").unlink()
    noctalia.save([entry, noctalia.write("2-0", b"second", "text/plain", 2_000)])

    assert import_noctalia(store, noctalia) == 1
    assert store.recent()[0].text == "second"


def test_no_noctalia_at_all_is_not_an_error(tmp_path, store):
    assert import_noctalia(store, tmp_path / "nothing-here") == 0


def test_a_corrupt_index_is_not_an_error(noctalia, store):
    (noctalia / "index.json").write_text("{ this is not json")
    assert import_noctalia(store, noctalia) == 0
