import math
from magpie.shot.model import (
    Arrow,
    Badge,
    Blur,
    Doc,
    Ellipse,
    Highlighter,
    Line,
    Pen,
    Pixelate,
    Rect,
    Redact,
    Sticker,
    Text,
)


def _assert_close(a, b, tol=1e-9):
    if isinstance(a, (int, float)):
        assert math.isclose(a, b, abs_tol=tol), f"{a} != {b}"
    elif isinstance(a, tuple):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            _assert_close(x, y, tol)
    elif isinstance(a, list):
        assert len(a) == len(b)
        for x, y in zip(a, b):
            _assert_close(x, y, tol)


def test_item_scaling_concrete_classes():
    # 1. Arrow
    arrow = Arrow(p0=(10.0, 20.0), p1=(30.0, 40.0), width=4.0, color=(1.0, 0.2, 0.3, 1.0))
    arrow.scaled(2.0)
    assert arrow.p0 == (20.0, 40.0)
    assert arrow.p1 == (60.0, 80.0)
    assert arrow.width == 8.0
    assert arrow.color == (1.0, 0.2, 0.3, 1.0)
    arrow.scaled(0.5)
    _assert_close(arrow.p0, (10.0, 20.0))
    _assert_close(arrow.p1, (30.0, 40.0))
    _assert_close(arrow.width, 4.0)

    # 2. Line
    line = Line(p0=(12.0, 24.0), p1=(36.0, 48.0), width=6.0, color=(0.1, 0.2, 0.3, 1.0))
    line.scaled(2.0)
    assert line.p0 == (24.0, 48.0)
    assert line.p1 == (72.0, 96.0)
    assert line.width == 12.0
    assert line.color == (0.1, 0.2, 0.3, 1.0)
    line.scaled(0.5)
    _assert_close(line.p0, (12.0, 24.0))
    _assert_close(line.p1, (36.0, 48.0))
    _assert_close(line.width, 6.0)

    # 3. Rect
    rect = Rect(p0=(5.0, 10.0), p1=(15.0, 25.0), width=3.0, fill=True, color=(0.2, 0.4, 0.6, 1.0))
    rect.scaled(2.0)
    assert rect.p0 == (10.0, 20.0)
    assert rect.p1 == (30.0, 50.0)
    assert rect.width == 6.0
    assert rect.fill is True
    assert rect.color == (0.2, 0.4, 0.6, 1.0)
    rect.scaled(0.5)
    _assert_close(rect.p0, (5.0, 10.0))
    _assert_close(rect.p1, (15.0, 25.0))
    _assert_close(rect.width, 3.0)

    # 4. Ellipse
    ellipse = Ellipse(p0=(8.0, 16.0), p1=(32.0, 64.0), width=5.0, fill=False, color=(0.3, 0.5, 0.7, 1.0))
    ellipse.scaled(2.0)
    assert ellipse.p0 == (16.0, 32.0)
    assert ellipse.p1 == (64.0, 128.0)
    assert ellipse.width == 10.0
    assert ellipse.fill is False
    assert ellipse.color == (0.3, 0.5, 0.7, 1.0)
    ellipse.scaled(0.5)
    _assert_close(ellipse.p0, (8.0, 16.0))
    _assert_close(ellipse.p1, (32.0, 64.0))
    _assert_close(ellipse.width, 5.0)

    # 5. Pen
    pen = Pen(points=[(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)], width=2.0, color=(0.4, 0.6, 0.8, 1.0))
    pen.scaled(2.0)
    assert pen.points == [(2.0, 4.0), (6.0, 8.0), (10.0, 12.0)]
    assert pen.width == 4.0
    assert pen.color == (0.4, 0.6, 0.8, 1.0)
    pen.scaled(0.5)
    _assert_close(pen.points, [(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)])
    _assert_close(pen.width, 2.0)

    # 6. Highlighter
    hl = Highlighter(points=[(10.0, 20.0), (30.0, 40.0)], width=8.0, color=(1.0, 1.0, 0.0, 0.4))
    hl.scaled(2.0)
    assert hl.points == [(20.0, 40.0), (60.0, 80.0)]
    assert hl.width == 16.0
    assert hl.color == (1.0, 1.0, 0.0, 0.4)
    hl.scaled(0.5)
    _assert_close(hl.points, [(10.0, 20.0), (30.0, 40.0)])
    _assert_close(hl.width, 8.0)

    # 7. Text
    text = Text(x=10.0, y=20.0, size=24.0, w=100.0, h=50.0, text="sample", color=(0.9, 0.1, 0.1, 1.0))
    text.scaled(2.0)
    assert text.x == 20.0
    assert text.y == 40.0
    assert text.size == 48.0
    assert text.w == 200.0
    assert text.h == 100.0
    assert text.text == "sample"
    assert text.color == (0.9, 0.1, 0.1, 1.0)
    text.scaled(0.5)
    _assert_close(text.x, 10.0)
    _assert_close(text.y, 20.0)
    _assert_close(text.size, 24.0)
    _assert_close(text.w, 100.0)
    _assert_close(text.h, 50.0)

    # 8. Badge
    badge = Badge(x=50.0, y=60.0, radius=16.0, n=7, color=(0.2, 0.8, 0.2, 1.0))
    badge.scaled(2.0)
    assert badge.x == 100.0
    assert badge.y == 120.0
    assert badge.radius == 32.0
    assert badge.n == 7
    assert badge.color == (0.2, 0.8, 0.2, 1.0)
    badge.scaled(0.5)
    _assert_close(badge.x, 50.0)
    _assert_close(badge.y, 60.0)
    _assert_close(badge.radius, 16.0)

    # 9. Blur
    blur = Blur(p0=(10.0, 20.0), p1=(40.0, 50.0), width=2.0, strength=14.0, color=(0.0, 0.0, 0.0, 1.0))
    blur.scaled(2.0)
    assert blur.p0 == (20.0, 40.0)
    assert blur.p1 == (80.0, 100.0)
    assert blur.width == 4.0
    assert blur.strength == 28.0
    assert blur.color == (0.0, 0.0, 0.0, 1.0)
    blur.scaled(0.5)
    _assert_close(blur.p0, (10.0, 20.0))
    _assert_close(blur.p1, (40.0, 50.0))
    _assert_close(blur.width, 2.0)
    _assert_close(blur.strength, 14.0)

    # 10. Pixelate
    pix = Pixelate(p0=(15.0, 25.0), p1=(45.0, 55.0), width=3.0, strength=12.0, color=(0.0, 0.0, 0.0, 1.0))
    pix.scaled(2.0)
    assert pix.p0 == (30.0, 50.0)
    assert pix.p1 == (90.0, 110.0)
    assert pix.width == 6.0
    assert pix.strength == 24.0
    pix.scaled(0.5)
    _assert_close(pix.p0, (15.0, 25.0))
    _assert_close(pix.p1, (45.0, 55.0))
    _assert_close(pix.width, 3.0)
    _assert_close(pix.strength, 12.0)

    # 11. Redact
    redact = Redact(p0=(20.0, 30.0), p1=(60.0, 70.0), width=4.0, strength=10.0, color=(0.0, 0.0, 0.0, 1.0))
    redact.scaled(2.0)
    assert redact.p0 == (40.0, 60.0)
    assert redact.p1 == (120.0, 140.0)
    assert redact.width == 8.0
    assert redact.strength == 20.0
    assert redact.color == (0.0, 0.0, 0.0, 1.0)
    redact.scaled(0.5)
    _assert_close(redact.p0, (20.0, 30.0))
    _assert_close(redact.p1, (60.0, 70.0))
    _assert_close(redact.width, 4.0)
    _assert_close(redact.strength, 10.0)

    # 12. Sticker
    surface_sentinel = object()
    sticker = Sticker(x=100.0, y=200.0, size=64.0, char="🎉", platform="noto", surface=surface_sentinel)
    sticker.scaled(2.0)
    assert sticker.x == 200.0
    assert sticker.y == 400.0
    assert sticker.size == 128.0
    assert sticker.char == "🎉"
    assert sticker.platform == "noto"
    assert sticker.surface is surface_sentinel
    sticker.scaled(0.5)
    _assert_close(sticker.x, 100.0)
    _assert_close(sticker.y, 200.0)
    _assert_close(sticker.size, 64.0)
    assert sticker.surface is surface_sentinel


def test_doc_scale_all():
    doc = Doc(800, 600)
    surface_sentinel = object()
    doc.checkpoint()
    doc.add(Badge(x=10, y=20, radius=10))
    doc.add(Sticker(x=50, y=50, size=40, surface=surface_sentinel))
    doc.checkpoint()
    assert doc.can_undo

    doc.scale_all(2.0, 1600, 1200)

    assert doc.width == 1600
    assert doc.height == 1200
    assert doc.items[0].x == 20
    assert doc.items[0].y == 40
    assert doc.items[0].radius == 20
    assert doc.items[1].x == 100
    assert doc.items[1].y == 100
    assert doc.items[1].size == 80
    assert doc.items[1].surface is surface_sentinel
    assert not doc.can_undo
    assert not doc.can_redo
