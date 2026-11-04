import math
import pytest
from magpie.shot.viewport import Viewport


def test_round_trip():
    vp = Viewport(800, 600, 400.0, 300.0)
    vp.zoom_to(1.5, 200.0, 150.0)
    points = [(0.0, 0.0), (200.0, 150.0), (12.3, 45.6), (-50.0, 400.0)]
    for sx, sy in points:
        ix, iy = vp.to_image(sx, sy)
        rx, ry = vp.to_screen(ix, iy)
        assert math.isclose(rx, sx, abs_tol=1e-9)
        assert math.isclose(ry, sy, abs_tol=1e-9)


def test_zoom_at_anchor_and_max_zoom():
    # 1000x1000 image in 500x500 view
    vp = Viewport(1000, 1000, 500.0, 500.0, max_zoom=32.0)
    # Start at scale 2.0 centred: ox = -750, oy = -750
    vp.reset(2.0)

    # Centred anchor: (250, 250)
    for factor in (0.5, 1.15, 3.0):
        vp.reset(2.0)
        sx, sy = 250.0, 250.0
        before_ix, before_iy = vp.to_image(sx, sy)
        changed = vp.zoom_at(sx, sy, factor)
        assert changed is True
        after_ix, after_iy = vp.to_image(sx, sy)
        assert math.isclose(before_ix, after_ix, abs_tol=1e-9)
        assert math.isclose(before_iy, after_iy, abs_tol=1e-9)

    # Different anchor point
    vp.reset(2.0)
    sx, sy = 200.0, 300.0
    before_ix, before_iy = vp.to_image(sx, sy)
    vp.zoom_at(sx, sy, 1.15)
    after_ix, after_iy = vp.to_image(sx, sy)
    assert math.isclose(before_ix, after_ix, abs_tol=1e-9)
    assert math.isclose(before_iy, after_iy, abs_tol=1e-9)

    # Factor 100 -> clamped at max_zoom
    vp.reset(2.0)
    changed = vp.zoom_at(250.0, 250.0, 100.0)
    assert changed is True
    assert vp.scale == 32.0
    # Zooming in further returns False since already at max_zoom
    assert vp.zoom_at(250.0, 250.0, 2.0) is False


def test_min_scale_clamp():
    # fit = min(400/800, 300/600) = 0.5.
    # min_scale = max(0.02, min(1.0, 0.5 / 2)) = 0.25.
    vp = Viewport(800, 600, 400.0, 300.0)
    assert vp.fit == 0.5
    assert vp.min_scale == 0.25

    # Zoom out far below min_scale
    changed = vp.zoom_at(200.0, 150.0, 0.001)
    assert changed is True
    assert vp.scale == 0.25
    assert vp.zoom_at(200.0, 150.0, 0.5) is False

    # Check bounds on min_scale: never above 1.0 and never below 0.02
    huge = Viewport(10, 10, 1000.0, 1000.0)  # fit = 100.0 -> fit/2 = 50.0 -> clamped to 1.0
    assert huge.min_scale == 1.0

    tiny = Viewport(10000, 10000, 100.0, 100.0)  # fit = 0.01 -> fit/2 = 0.005 -> clamped to 0.02
    assert tiny.min_scale == 0.02


def test_clamp_small_and_big():
    # Small image (fits in view): centred along both axes
    vp = Viewport(200, 100, 500.0, 400.0)
    # fit = min(500/200, 400/100) = 2.5
    # Set scale to 1.0: sw=200, sh=100 in 500x400 view
    vp.reset(1.0)
    assert vp.ox == (500.0 - 200.0) / 2.0  # 150.0
    assert vp.oy == (400.0 - 100.0) / 2.0  # 150.0

    # Big image (exceeds view): bounds ensure view is completely covered
    vp = Viewport(1000, 1000, 500.0, 500.0)
    vp.reset(2.0)  # sw = 2000, sh = 2000
    # valid range: [500 - 2000, 0] = [-1500, 0]
    vp.ox = 100.0
    vp.oy = -2000.0
    vp.clamp()
    assert vp.ox == 0.0
    assert vp.oy == -1500.0


def test_pan_and_return_value():
    vp = Viewport(1000, 1000, 500.0, 500.0)
    vp.reset(2.0)  # centred at ox=-750, oy=-750, range [-1500, 0]
    assert vp.pan(50.0, -50.0) is True
    assert vp.ox == -700.0
    assert vp.oy == -800.0

    # Pan all the way past positive boundary
    assert vp.pan(2000.0, 0.0) is True
    assert vp.ox == 0.0
    # Trying to pan further right returns False
    assert vp.pan(10.0, 0.0) is False

    # Pan all the way past negative boundary
    assert vp.pan(-3000.0, 0.0) is True
    assert vp.ox == -1500.0
    # Trying to pan further left returns False
    assert vp.pan(-10.0, 0.0) is False

    # For a small image that fits, pan always returns False because clamp centres it
    small = Viewport(100, 100, 500.0, 500.0)
    small.reset(1.0)
    assert small.pan(20.0, 30.0) is False
    assert small.ox == 200.0
    assert small.oy == 200.0


def test_reset():
    vp = Viewport(800, 600, 400.0, 300.0)
    vp.zoom_at(100.0, 100.0, 3.0)
    vp.pan(50.0, 50.0)
    assert vp.scale != vp.fit

    vp.reset()
    assert vp.scale == vp.fit
    assert vp.ox == (400.0 - 800.0 * vp.fit) / 2.0
    assert vp.oy == (300.0 - 600.0 * vp.fit) / 2.0


def test_percent():
    # With device_ratio = 1.25, scale = 0.8 is 100%
    vp = Viewport(1000, 1000, 500.0, 500.0, device_ratio=1.25)
    vp.reset(0.8)
    assert vp.percent == 100

    # With device_ratio = 1.0, scale = 1.0 is 100%
    vp_one = Viewport(1000, 1000, 500.0, 500.0, device_ratio=1.0)
    vp_one.reset(1.0)
    assert vp_one.percent == 100

    vp_one.reset(2.0)
    assert vp_one.percent == 200


def test_resize():
    vp = Viewport(1000, 1000, 500.0, 500.0)
    vp.reset(2.0)  # sw = 2000, sh = 2000, ox = -750, oy = -750
    # Centre of image in screen px is ox + sw/2 = -750 + 1000 = 250 (centre of view)
    vp.resize(600.0, 600.0)
    assert vp.view_w == 600.0
    assert vp.view_h == 600.0
    # Range is [600 - 2000, 0] = [-1400, 0].
    # ox was -750, which is still in [-1400, 0], so ox and oy are unchanged
    assert vp.ox == -750.0
    assert vp.oy == -750.0

    # Resize smaller than image coverage: view 100x100
    vp.resize(100.0, 100.0)
    # Range is [100 - 2000, 0] = [-1900, 0]. -750 still in range
    assert vp.ox == -750.0

    # Resize larger than image: view 2500x2500 -> fits! So it re-centres
    vp.resize(2500.0, 2500.0)
    assert vp.ox == (2500.0 - 2000.0) / 2.0  # 250.0
    assert vp.oy == (2500.0 - 2000.0) / 2.0  # 250.0


def test_edge_cases_1x1_and_0x0():
    # 1x1 image and 0x0 view must not raise NaN or Inf
    vp = Viewport(1, 1, 0.0, 0.0)
    assert not math.isnan(vp.fit) and not math.isinf(vp.fit)
    assert not math.isnan(vp.min_scale) and not math.isinf(vp.min_scale)
    assert not math.isnan(vp.scale) and not math.isinf(vp.scale)
    assert not math.isnan(vp.ox) and not math.isinf(vp.ox)
    assert not math.isnan(vp.oy) and not math.isinf(vp.oy)

    # Calling methods
    vp.resize(0.0, 0.0)
    vp.clamp()
    vp.reset()
    vp.zoom_at(0.0, 0.0, 2.0)
    vp.pan(1.0, 1.0)
    ix, iy = vp.to_image(0.0, 0.0)
    assert not math.isnan(ix) and not math.isnan(iy)
    sx, sy = vp.to_screen(ix, iy)
    assert not math.isnan(sx) and not math.isnan(sy)
