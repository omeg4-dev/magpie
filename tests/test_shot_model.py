import math

from magpie.shot.model import (Arrow, Badge, Doc, Ellipse, Highlighter, Pen, Rect,
                               Redact, Sticker, Text, contrast, rgba)


def test_rgba_and_contrast():
    assert rgba("#ff0000") == (1.0, 0.0, 0.0, 1.0)
    assert contrast(rgba("#ffffff"))[:3] == (0.0, 0.0, 0.0)
    assert contrast(rgba("#000000"))[:3] == (1.0, 1.0, 1.0)


def test_ids_and_pick_topmost():
    doc = Doc(200, 100)
    a = doc.add(Rect(p0=(10, 10), p1=(60, 60), fill=True))
    b = doc.add(Rect(p0=(30, 30), p1=(80, 80), fill=True))
    assert (a.id, b.id) == (1, 2)
    assert doc.pick(40, 40) is b
    assert doc.pick(12, 12) is a
    assert doc.pick(150, 90) is None


def test_outline_rect_is_hollow():
    r = Rect(p0=(0, 0), p1=(100, 100), width=4)
    assert r.hit(50, 1)           # on the border
    assert not r.hit(50, 50)      # the picture under a frame stays clickable
    r.fill = True
    assert r.hit(50, 50)


def test_ellipse_outline_and_fill():
    e = Ellipse(p0=(0, 0), p1=(100, 60), width=4)
    assert e.hit(50, 0)
    assert not e.hit(50, 30)
    assert not e.hit(2, 2)        # a corner of the box is outside the ellipse
    e.fill = True
    assert e.hit(50, 30)


def test_arrow_hit_follows_the_segment():
    a = Arrow(p0=(0, 0), p1=(100, 0), width=4)
    assert a.hit(50, 4)
    assert not a.hit(50, 30)
    assert a.hit(100, 0)


def test_arrow_endpoint_drag_and_shift_snap():
    a = Arrow(p0=(0, 0), p1=(10, 10))
    a.drag_handle("p1", 100, 7, keep_ratio=True)   # nearly horizontal -> horizontal
    assert a.p1[1] == 0 or abs(a.p1[1]) < 1e-9
    assert math.isclose(a.p1[0], math.hypot(100, 7), rel_tol=1e-9)
    a.drag_handle("p0", 5, 5)
    assert a.p0 == (5, 5)


def test_box_corner_drag_keeps_the_opposite_corner():
    r = Rect(p0=(10, 20), p1=(50, 60))
    r.drag_handle("se", 90, 100)
    assert r.bounds() == (10, 20, 80, 80)
    r.drag_handle("nw", 0, 0)                       # opposite corner (90,100) fixed
    assert r.bounds() == (0, 0, 90, 100)
    r.drag_handle("nw", 200, 200)                   # dragged past: flips, stays valid
    x, y, w, h = r.bounds()
    assert w >= 0 and h >= 0


def test_box_keep_ratio_is_square():
    r = Rect(p0=(0, 0), p1=(10, 10))
    r.drag_handle("se", 40, 25, keep_ratio=True)
    _, _, w, h = r.bounds()
    assert w == h == 40


def test_translate_moves_everything():
    items = [Arrow(p0=(0, 0), p1=(5, 5)), Pen(points=[(0, 0), (1, 1)]),
             Text(x=1, y=1), Badge(x=1, y=1), Sticker(x=1, y=1), Redact(p0=(0, 0), p1=(2, 2))]
    for i in items:
        before = i.bounds()
        i.translate(10, 20)
        after = i.bounds()
        assert (after[0] - before[0], after[1] - before[1]) == (10, 20), i.kind


def test_pen_hit_and_single_point():
    p = Pen(points=[(0, 0), (50, 0), (50, 50)], width=4)
    assert p.hit(25, 2) and p.hit(50, 25)
    assert not p.hit(10, 40)
    assert Pen(points=[(5, 5)], width=4).hit(6, 6)


def test_highlighter_is_fatter_than_its_pen_width():
    h = Highlighter(points=[(0, 0), (100, 0)], width=4)
    assert h.hit(50, 4 * Highlighter.SCALE / 2 - 1, tol=0)


def test_badge_numbers_continue_from_the_highest():
    doc = Doc(100, 100)
    assert doc.next_badge() == 1
    doc.add(Badge(n=1))
    doc.add(Badge(n=2))
    doc.remove(1)
    assert doc.next_badge() == 3


def test_sticker_resize_keeps_it_square_and_anchored():
    s = Sticker(x=100, y=100, size=100)
    s.drag_handle("se", 250, 230)         # nw corner (50,50) stays
    assert s.bounds()[:2] == (50, 50)
    assert s.size == 200


def test_undo_redo_round_trip():
    doc = Doc(100, 100)
    doc.checkpoint()
    r = doc.add(Rect(p0=(0, 0), p1=(10, 10)))
    doc.checkpoint()
    r.translate(5, 5)
    assert doc.items[0].bounds()[:2] == (5, 5)
    assert doc.undo()
    assert doc.items[0].bounds()[:2] == (0, 0)
    assert doc.undo()
    assert len(doc) == 0
    assert not doc.undo()
    assert doc.redo() and doc.redo()
    assert doc.items[0].bounds()[:2] == (5, 5)
    assert not doc.redo()


def test_new_change_clears_redo():
    doc = Doc(10, 10)
    doc.checkpoint(); doc.add(Rect())
    doc.undo()
    assert doc.can_redo
    doc.checkpoint()
    assert not doc.can_redo


def test_undo_does_not_alias_live_objects():
    doc = Doc(10, 10)
    r = doc.add(Rect(p0=(0, 0), p1=(1, 1)))
    doc.checkpoint()
    r.translate(9, 9)
    doc.undo()
    assert r.bounds()[:2] == (9, 9)             # the old object is untouched
    assert doc.items[0].bounds()[:2] == (0, 0)  # the restored one is a copy


def test_sticker_pixels_are_shared_not_copied_by_undo():
    doc = Doc(10, 10)
    pixels = object()
    doc.add(Sticker(surface=pixels))
    doc.checkpoint()
    doc.items[0].translate(1, 1)
    doc.undo()
    assert doc.items[0].surface is pixels


def test_discard_checkpoint_for_a_gesture_that_changed_nothing():
    doc = Doc(10, 10)
    doc.checkpoint()
    doc.discard_checkpoint()
    assert not doc.can_undo


def test_default_sizes_scale_with_the_picture():
    small, big = Doc(800, 600), Doc(3840, 2160)
    assert big.default_width() > small.default_width() >= 3
    assert big.default_text_size() > small.default_text_size() >= 20


def test_raise_to_top_and_remove():
    doc = Doc(10, 10)
    a = doc.add(Rect()); b = doc.add(Rect())
    doc.raise_to_top(a.id)
    assert doc.items[-1] is a and doc.items[0] is b
    assert doc.remove(a.id) and not doc.remove(a.id)
