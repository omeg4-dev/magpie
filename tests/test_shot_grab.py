from __future__ import annotations

import json
import subprocess
from unittest.mock import MagicMock

import pytest
from PIL import Image

from magpie.shot.grab import (
    GrabError,
    Monitor,
    focused_monitor,
    grab_all,
    grab_monitor,
    monitors,
    to_surface,
)

CANNED_HYPRCTL_JSON = json.dumps([
    {
        "id": 2,
        "name": "DP-2",
        "width": 1920,
        "height": 1080,
        "x": 0,
        "y": 0,
        "scale": 1.0,
        "focused": False,
        "disabled": False,
    },
    {
        "id": 0,
        "name": "DP-1",
        "width": 2560,
        "height": 1440,
        "x": 1920,
        "y": 0,
        "scale": 1.25,
        "focused": True,
        "disabled": False,
    },
    {
        "id": 1,
        "name": "HDMI-A-1",
        "width": 1920,
        "height": 1080,
        "x": 0,
        "y": 1080,
        "scale": 1.0,
        "focused": False,
        "disabled": True,
    },
])

# 4x2 PPM image with 8 pixels (24 bytes RGB):
# 4 red pixels (255, 0, 0), 4 blue pixels (0, 0, 255)
TINY_PPM = b"P6\n4 2\n255\n" + (b"\xff\x00\x00" * 4 + b"\x00\x00\xff" * 4)


def test_monitors_parse_and_disabled_skip():
    def fake_run(cmd, **kwargs):
        assert cmd == ["hyprctl", "-j", "monitors"]
        return subprocess.CompletedProcess(cmd, 0, stdout=CANNED_HYPRCTL_JSON, stderr="")

    mons = monitors(run=fake_run)
    assert len(mons) == 2

    # Check DP-2
    m0 = mons[0]
    assert m0.name == "DP-2"
    assert (m0.x, m0.y) == (0, 0)
    assert (m0.width, m0.height) == (1920, 1080)
    assert (m0.pixel_width, m0.pixel_height) == (1920, 1080)
    assert m0.scale == 1.0
    assert not m0.focused

    # Check DP-1
    m1 = mons[1]
    assert m1.name == "DP-1"
    assert (m1.x, m1.y) == (1920, 0)
    # Logical size: 2560 / 1.25 = 2048, 1440 / 1.25 = 1152
    assert (m1.width, m1.height) == (2048, 1152)
    assert (m1.pixel_width, m1.pixel_height) == (2560, 1440)
    assert m1.scale == 1.25
    assert m1.focused


def test_focused_monitor_selection():
    mons = [
        Monitor("DP-2", 0, 0, 1920, 1080, 1920, 1080, 1.0, False),
        Monitor("DP-1", 1920, 0, 2048, 1152, 2560, 1440, 1.25, True),
    ]
    assert focused_monitor(mons).name == "DP-1"

    # When none focused, first is chosen
    unfocused = [
        Monitor("DP-2", 0, 0, 1920, 1080, 1920, 1080, 1.0, False),
        Monitor("DP-1", 1920, 0, 2048, 1152, 2560, 1440, 1.25, False),
    ]
    assert focused_monitor(unfocused).name == "DP-2"

    with pytest.raises(GrabError):
        focused_monitor([])


def test_grab_monitor_calls_grim_argv():
    mon = Monitor("DP-1", 1920, 0, 2048, 1152, 4, 2, 1.0, True)
    recorded_cmd = []

    def fake_run(cmd, **kwargs):
        recorded_cmd.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=TINY_PPM, stderr=b"")

    img = grab_monitor(mon, run=fake_run)
    assert recorded_cmd == [["grim", "-t", "ppm", "-o", "DP-1", "-"]]
    assert img.size == (4, 2)
    assert img.mode == "RGB"
    assert img.getpixel((0, 0)) == (255, 0, 0)
    assert img.getpixel((0, 1)) == (0, 0, 255)


def test_grab_all_calls_grim_argv():
    recorded_cmd = []

    def fake_run(cmd, **kwargs):
        recorded_cmd.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=TINY_PPM, stderr=b"")

    img = grab_all(run=fake_run)
    assert recorded_cmd == [["grim", "-t", "ppm", "-"]]
    assert img.size == (4, 2)
    assert img.mode == "RGB"


def test_grab_monitor_error_handling():
    mon = Monitor("DP-1", 0, 0, 1920, 1080, 1920, 1080, 1.0, True)

    def fail_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 1, stdout=b"", stderr=b"grim: output not found")

    with pytest.raises(GrabError, match="grim: output not found"):
        grab_monitor(mon, run=fail_run)

    def empty_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout=b"", stderr=b"empty")

    with pytest.raises(GrabError):
        grab_monitor(mon, run=empty_run)


def test_to_surface_pixel_round_trip():
    # Width 4, height 2 -> stride == 4 * 4 == 16
    im = Image.new("RGB", (4, 2), (255, 0, 0))
    surface = to_surface(im)
    assert surface.get_width() == 4
    assert surface.get_height() == 2
    assert surface.get_stride() == 16

    # In little-endian ARGB32, (255, 0, 0) red is [B=00, G=00, R=FF, A=FF]
    data = bytes(surface.get_data())
    pixel_bytes = data[:4]
    assert pixel_bytes == b"\x00\x00\xff\xff"
