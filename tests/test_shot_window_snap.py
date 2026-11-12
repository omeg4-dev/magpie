"""Window snapping, the colour under the pointer, and arrow-key nudging."""

import json
from types import SimpleNamespace

from magpie.shot.grab import (Monitor, Window, native_rect, nudge_step, pixel_hex,
                              window_at, windows)


def _client(x, y, w, h, ws=1, floating=False, rank=0, mapped=True, hidden=False):
    return {"at": [x, y], "size": [w, h], "workspace": {"id": ws}, "floating": floating,
            "focusHistoryID": rank, "mapped": mapped, "hidden": hidden, "title": "t"}


def _run(clients):
    return lambda *_a, **_k: SimpleNamespace(returncode=0, stdout=json.dumps(clients), stderr="")


MONS = [Monitor("DP-1", 1920, 0, 2048, 1152, 2560, 1440, 1.25, True, workspace=2),
        Monitor("DP-2", 0, 0, 1920, 1080, 1920, 1080, 1.0, False, workspace=1)]


def test_only_visible_mapped_windows_are_listed():
    found = windows(MONS, run=_run([
        _client(0, 0, 100, 100, ws=1),
        _client(5, 5, 100, 100, ws=7),                  # on a workspace nobody is looking at
        _client(5, 5, 100, 100, ws=2, hidden=True),
        _client(5, 5, 100, 100, ws=2, mapped=False),
        _client(1920, 0, 300, 200, ws=2)]))
    assert [(w.x, w.y) for w in found] == [(0, 0), (1920, 0)]


def test_hyprctl_failure_means_no_windows_not_an_error():
    def boom(*_a, **_k):
        raise OSError("no hyprctl")
    assert windows(MONS, run=boom) == []
    assert windows(MONS, run=lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="")) == []
    assert windows(MONS, run=lambda *a, **k: SimpleNamespace(returncode=0, stdout="nope", stderr="")) == []


def test_window_at_prefers_floating_then_recent():
    tiled = Window(0, 0, 500, 500, False, 0)
    older = Window(0, 0, 500, 500, False, 3)
    popup = Window(100, 100, 50, 50, True, 5)
    assert window_at([older, tiled], 10, 10) is tiled
    assert window_at([tiled, popup], 120, 120) is popup
    assert window_at([tiled, popup], 10, 10) is tiled
    assert window_at([tiled], 500, 10) is None          # the right edge is outside


def test_pixel_hex_reads_bgra():
    data = bytes([0x11, 0x22, 0x33, 0xFF,  0xAA, 0xBB, 0xCC, 0xFF])   # two pixels, one row
    assert pixel_hex(data, 8, 2, 1, 0, 0) == "#332211"
    assert pixel_hex(data, 8, 2, 1, 1, 0) == "#ccbbaa"
    assert pixel_hex(data, 8, 2, 1, 99, 99) == "#ccbbaa"   # clamped, never out of range


def test_nudge_steps():
    assert nudge_step("Left", False) == (-1, 0)
    assert nudge_step("Down", True) == (0, 10)
    assert nudge_step("a", False) is None


def test_selection_is_whole_native_pixels_on_a_fractional_monitor():
    # 1.25x: logical (100.4, 200.2) -> (300.4, 400.0) is 125.5 -> 125/126 native, never a logical step
    x, y, w, h = native_rect((100.4, 200.2), (300.4, 400.0), 1.25, (2560, 1440))
    assert (x, y) == (round(100.4 * 1.25), round(200.2 * 1.25))
    assert (x + w, y + h) == (round(300.4 * 1.25), round(400.0 * 1.25))
    assert all(isinstance(v, int) for v in (x, y, w, h))


def test_selection_is_clamped_and_order_independent():
    assert native_rect((10, 10), (-50, 5000), 1.25, (2560, 1440)) == (0, 12, 12, 1428)
    assert native_rect((300, 300), (100, 100), 1.0, (1920, 1080)) == (100, 100, 200, 200)


def test_nudge_moves_the_second_corner_by_native_pixels():
    base = native_rect((100, 100), (200, 200), 1.25, (2560, 1440))
    moved = native_rect((100, 100), (200, 200), 1.25, (2560, 1440), nudge=(3, -2))
    assert (moved[2] - base[2], moved[3] - base[3]) == (3, -2)
    assert moved[:2] == base[:2]


def test_square_keeps_both_sides_equal():
    _x, _y, w, h = native_rect((0, 0), (100, 40), 1.0, (1920, 1080), square=True)
    assert w == h == 100
