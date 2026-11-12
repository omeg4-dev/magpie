"""Pages: the first few hundred entries now, more when the reader gets near the end."""

from magpie.browse import Browse
from magpie.store import LIST_TEXT, Store


def _store(tmp_path, n):
    s = Store(tmp_path)
    for i in range(n):
        s.add(f"entry {i}".encode(), "text/plain")
    return s


def test_first_page_only(tmp_path):
    b = Browse(_store(tmp_path, 50), limit=40, page=10)
    assert len(b.entries()) == 10


def test_more_grows_by_a_page_until_the_cap(tmp_path):
    b = Browse(_store(tmp_path, 50), limit=25, page=10)
    assert b.more() and len(b.entries()) == 20
    assert b.more() and len(b.entries()) == 25
    assert not b.more()                      # the cap
    assert len(b.entries()) == 25


def test_more_is_a_no_op_when_everything_is_already_loaded(tmp_path):
    b = Browse(_store(tmp_path, 5), limit=40, page=10)
    assert not b.more()


def test_more_keeps_the_selection(tmp_path):
    b = Browse(_store(tmp_path, 50), limit=40, page=10)
    b.move(3)
    chosen = b.selected.id
    b.more()
    assert b.selected.id == chosen


def test_a_new_query_starts_from_the_first_page(tmp_path):
    b = Browse(_store(tmp_path, 50), limit=40, page=10)
    b.more()
    b.set_query("entry")
    assert len(b.entries()) == 10


def test_list_and_grid_share_their_answer(tmp_path):
    b = Browse(_store(tmp_path, 20), limit=40, page=10)
    b.more()
    first = b.entries()
    b.move(2)
    b.set_mode("grid")
    assert b.entries() is first             # no second query
    assert b.position == 0                  # but the selection is back at the top
    b.set_mode("starred")
    assert b.entries() is not first


def test_list_queries_carry_only_the_start_of_a_long_text(tmp_path):
    s = Store(tmp_path)
    big = "x" * (LIST_TEXT * 3)
    s.add(big.encode(), "text/plain")
    row = Browse(s).entries()[0]
    assert len(row.text) == LIST_TEXT
    assert len(s.get(row.id).text) == len(big)      # the whole of it is one get away
