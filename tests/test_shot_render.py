import io

import cairo
import pytest
from PIL import Image

from magpie.shot.model import (Arrow, Badge, Blur, Ellipse, Highlighter, Pen, Pixelate,
                               Rect, Redact, Sticker, Text, rgba)
from magpie.shot.render import Renderer, from_pil, measure_text, to_pil


def noise(w=120, h=80):
    """A picture where every pixel differs from its neighbours, so a blur or a
    redaction is unmistakable."""
    img = Image.new("RGB", (w, h))
    img.putdata([((x * 37) % 256, (y * 91) % 256, ((x + y) * 53) % 256)
                 for y in range(h) for x in range(w)])
    return img


@pytest.fixture
def base():
    return from_pil(noise())


def decode(png: bytes) -> Image.Image:
    return Image.open(io.BytesIO(png)).convert("RGB")


def test_pil_cairo_round_trip():
    img = noise()
    back = to_pil(from_pil(img)).convert("RGB")
    assert list(back.getdata()) == list(img.getdata())


def test_export_with_nothing_is_the_original(base):
    out = decode(Renderer(base).export_png([]))
    assert out.size == (120, 80)
    assert list(out.getdata()) == list(noise().getdata())


def test_redact_removes_the_pixels_underneath(base):
    r = Redact(p0=(10, 10), p1=(60, 50))
    out = decode(Renderer(base).export_png([r]))
    region = out.crop((10, 10, 60, 50))
    assert set(region.getdata()) == {(0, 0, 0)}            # a solid bar, nothing of the original
    # ...and nothing outside it changed.
    assert out.getpixel((5, 5)) == noise().getpixel((5, 5))
    assert out.getpixel((70, 60)) == noise().getpixel((70, 60))


def test_blur_changes_the_region_only_and_loses_detail(base):
    b = Blur(p0=(20, 20), p1=(90, 60), strength=6)
    out = decode(Renderer(base).export_png([b]))
    orig = noise()
    assert out.getpixel((5, 5)) == orig.getpixel((5, 5))
    assert out.getpixel((100, 70)) == orig.getpixel((100, 70))

    def roughness(img):
        px = img.crop((20, 20, 90, 60)).convert("L")
        data = list(px.getdata())
        return sum(abs(a - c) for a, c in zip(data, data[1:])) / len(data)

    assert roughness(out) < roughness(orig) / 3


def test_pixelate_makes_blocks(base):
    p = Pixelate(p0=(0, 0), p1=(40, 40), strength=10)
    out = decode(Renderer(base).export_png([p]))
    # Every 10x10 block is one colour.
    for bx in range(0, 40, 10):
        for by in range(0, 40, 10):
            block = {out.getpixel((x, y)) for x in range(bx, bx + 10) for y in range(by, by + 10)}
            assert len(block) == 1, (bx, by)


def test_effects_read_the_original_not_other_annotations(base):
    # A red bar under a blur must not bleed into the blurred pixels.
    bar = Redact(p0=(0, 0), p1=(120, 80), color=(1, 0, 0, 1))
    blur = Blur(p0=(20, 20), p1=(60, 60), strength=4)
    both = decode(Renderer(base).export_png([bar, blur]))
    only = decode(Renderer(base).export_png([blur]))
    assert both.getpixel((40, 40)) == only.getpixel((40, 40))


def test_region_outside_or_empty_is_safe(base):
    items = [Blur(p0=(500, 500), p1=(600, 600)), Pixelate(p0=(5, 5), p1=(5, 5)),
             Blur(p0=(-30, -30), p1=(10, 10))]
    assert decode(Renderer(base).export_png(items)).size == (120, 80)


def test_every_shape_draws_something(base):
    red = rgba("#ff0000")
    shapes = [
        Arrow(p0=(10, 10), p1=(100, 60), color=red, width=5),
        Rect(p0=(10, 10), p1=(100, 60), color=red, width=5),
        Rect(p0=(10, 10), p1=(100, 60), color=red, fill=True),
        Ellipse(p0=(10, 10), p1=(100, 60), color=red, width=5),
        Pen(points=[(10, 10), (40, 50), (90, 20), (100, 70)], color=red, width=5),
        Highlighter(points=[(10, 40), (110, 40)], color=rgba("#ffd60a"), width=5),
        Badge(x=60, y=40, n=7, color=red, radius=16),
    ]
    t = Text(x=10, y=10, text="Hi", color=red, size=30)
    measure_text(t)
    shapes.append(t)
    orig = list(noise().getdata())
    for shape in shapes:
        out = list(decode(Renderer(base).export_png([shape])).getdata())
        assert out != orig, shape.kind


def test_highlighter_is_translucent(base):
    h = Highlighter(points=[(10, 40), (110, 40)], color=(1, 1, 0, 1), width=4)
    out = decode(Renderer(base).export_png([h]))
    before, after = noise().getpixel((60, 40)), out.getpixel((60, 40))
    assert after != before
    # Translucent: the picture still shows through (blue channel is not zeroed).
    assert after[2] > 0.4 * before[2] * (1 - 0.5)


def test_text_measure_grows_with_text_and_size():
    a, b = Text(text="Hi", size=20), Text(text="Hello world", size=20)
    c = Text(text="Hi", size=40)
    measure_text(a); measure_text(b); measure_text(c)
    assert b.w > a.w and c.h > a.h
    assert a.hit(a.x + 1, a.y + 1)


def test_sticker_draws_its_surface(base):
    s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 16, 16)
    ctx = cairo.Context(s); ctx.set_source_rgb(0, 1, 0); ctx.paint()
    out = decode(Renderer(base).export_png([Sticker(x=60, y=40, size=32, surface=s)]))
    assert out.getpixel((60, 40)) == (0, 255, 0)
    assert out.getpixel((5, 5)) == noise().getpixel((5, 5))
    # A sticker without pixels is skipped, not a crash.
    Renderer(base).export_png([Sticker(x=60, y=40, size=32, surface=None)])


def test_hidden_item_is_not_painted(base):
    r = Redact(p0=(0, 0), p1=(120, 80))
    r.id = 7
    out = decode(Renderer(base).export_surface([r]) and Renderer(base).export_png([r]))
    assert out.getpixel((5, 5)) == (0, 0, 0)
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 120, 80)
    Renderer(base).paint(cairo.Context(surface), [r], 1.0, hide=7)
    assert to_pil(surface).convert("RGB").getpixel((5, 5)) == noise().getpixel((5, 5))


def test_scaled_paint_is_the_right_size(base):
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, 60, 40)
    Renderer(base).paint(cairo.Context(surface), [Redact(p0=(0, 0), p1=(120, 80))], 0.5)
    assert to_pil(surface).convert("RGB").getpixel((30, 20)) == (0, 0, 0)
