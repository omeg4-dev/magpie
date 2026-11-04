"""Taking screenshots via Hyprland and grim.

Provides monitor discovery and raw screen capture into Pillow images and
cairo surfaces. I/O boundaries accept fake runners for deterministic testing.
"""

from __future__ import annotations

import io
import json
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING

import cairo
from PIL import Image

if TYPE_CHECKING:
    pass

__all__ = [
    "Monitor",
    "GrabError",
    "monitors",
    "focused_monitor",
    "grab_monitor",
    "grab_all",
    "to_surface",
]


class GrabError(RuntimeError):
    """Raised when screen capture or monitor discovery fails."""


@dataclass(frozen=True)
class Monitor:
    name: str          # "DP-1"
    x: int             # logical position in the compositor layout
    y: int
    width: int         # LOGICAL size (pixels / scale, rounded)
    height: int
    pixel_width: int   # native size as reported by hyprctl ("width"/"height" fields)
    pixel_height: int
    scale: float
    focused: bool


def monitors(run=subprocess.run) -> list[Monitor]:
    """Query compositor for active monitors, skipping disabled outputs."""
    try:
        res = run(["hyprctl", "-j", "monitors"], capture_output=True, text=True)
    except (subprocess.CalledProcessError, OSError) as e:
        raise GrabError(f"hyprctl monitors failed: {e}") from e

    if res.returncode != 0:
        err = res.stderr if isinstance(res.stderr, str) else (res.stderr.decode() if res.stderr else "")
        raise GrabError(f"hyprctl monitors failed ({res.returncode}): {err.strip()}")

    out = res.stdout if isinstance(res.stdout, str) else res.stdout.decode()
    try:
        data = json.loads(out)
    except json.JSONDecodeError as e:
        raise GrabError(f"Failed to parse hyprctl JSON: {e}") from e

    result: list[Monitor] = []
    for item in data:
        if item.get("disabled", False):
            continue
        pixel_width = int(item["width"])
        pixel_height = int(item["height"])
        scale = float(item["scale"])
        result.append(Monitor(
            name=str(item["name"]),
            x=int(item["x"]),
            y=int(item["y"]),
            width=round(pixel_width / scale),
            height=round(pixel_height / scale),
            pixel_width=pixel_width,
            pixel_height=pixel_height,
            scale=scale,
            focused=bool(item.get("focused", False)),
        ))
    return result


def focused_monitor(mons: list[Monitor] | None = None) -> Monitor:
    """Return the focused monitor, or the first monitor if none is focused."""
    if mons is None:
        mons = monitors()
    if not mons:
        raise GrabError("No monitors found")
    for mon in mons:
        if mon.focused:
            return mon
    return mons[0]


def _grab(cmd: list[str], run) -> Image.Image:
    try:
        res = run(cmd, capture_output=True)
    except (subprocess.CalledProcessError, OSError) as e:
        raise GrabError(f"grim failed: {e}") from e

    if res.returncode != 0 or not res.stdout:
        stderr = res.stderr.decode(errors="replace") if isinstance(res.stderr, bytes) else (res.stderr or "")
        raise GrabError(f"grim failed ({res.returncode}): {stderr.strip()}")

    try:
        img = Image.open(io.BytesIO(res.stdout))
        return img.convert("RGB")
    except Exception as e:
        raise GrabError(f"Failed to decode grim output: {e}") from e


def grab_monitor(mon: Monitor, run=subprocess.run) -> Image.Image:
    """Grab the contents of a specific monitor using grim."""
    return _grab(["grim", "-t", "ppm", "-o", mon.name, "-"], run=run)


def grab_all(run=subprocess.run) -> Image.Image:
    """Grab the entire compositor layout using grim."""
    return _grab(["grim", "-t", "ppm", "-"], run=run)


def to_surface(img: Image.Image) -> cairo.ImageSurface:
    """Convert a Pillow image into an opaque ARGB32 cairo ImageSurface."""
    w, h = img.size
    surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
    surface.flush()
    raw = img.convert("RGB").convert("RGBA").tobytes("raw", "BGRA")
    stride = surface.get_stride()
    buf = surface.get_data()
    if stride == w * 4:
        buf[:] = raw
    else:
        row_len = w * 4
        for y in range(h):
            buf[y * stride : y * stride + row_len] = raw[y * row_len : (y + 1) * row_len]
    surface.mark_dirty()
    return surface
