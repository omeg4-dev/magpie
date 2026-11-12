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
    "Window",
    "windows",
    "window_at",
    "pixel_hex",
    "nudge_step",
    "native_rect",
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
    workspace: int = 0   # the workspace showing on it (0 = unknown)


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
            workspace=int((item.get("activeWorkspace") or {}).get("id", 0) or 0),
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


# -- windows, for "click a window to select it" -------------------------------


@dataclass(frozen=True)
class Window:
    x: int             # logical, in the compositor layout
    y: int
    width: int
    height: int
    floating: bool
    focus_rank: int    # 0 = the one you used last; lower is higher up
    title: str = ""


def windows(mons: list[Monitor], run=subprocess.run) -> list[Window]:
    """The windows you can see right now, on the workspaces showing on a monitor.

    Failure is not an error: window snapping is a convenience, and a screenshot
    must never wait on, or fail because of, a second `hyprctl` call.
    """
    try:
        res = run(["hyprctl", "-j", "clients"], capture_output=True, text=True)
        if res.returncode != 0:
            return []
        data = json.loads(res.stdout)
    except (subprocess.CalledProcessError, OSError, ValueError, TypeError):
        return []
    showing = {m.workspace for m in mons if m.workspace}
    out: list[Window] = []
    for item in data:
        try:
            if not item.get("mapped", True) or item.get("hidden", False):
                continue
            if showing and int(item["workspace"]["id"]) not in showing:
                continue
            (x, y), (w, h) = item["at"], item["size"]
            if w <= 0 or h <= 0:
                continue
            out.append(Window(int(x), int(y), int(w), int(h), bool(item.get("floating")),
                              int(item.get("focusHistoryID", 99)), str(item.get("title", ""))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def window_at(wins: list[Window], x: float, y: float) -> Window | None:
    """The window on top at this point: floating ones first, then the most recently used."""
    hit = [w for w in wins if w.x <= x < w.x + w.width and w.y <= y < w.y + w.height]
    if not hit:
        return None
    return min(hit, key=lambda w: (not w.floating, w.focus_rank))


def pixel_hex(data, stride: int, width: int, height: int, x: int, y: int) -> str:
    """`#rrggbb` of one pixel of a cairo ARGB32 buffer (little endian: B, G, R, A)."""
    x = max(0, min(width - 1, int(x)))
    y = max(0, min(height - 1, int(y)))
    at = y * stride + x * 4
    return "#{:02x}{:02x}{:02x}".format(data[at + 2], data[at + 1], data[at])


#: (dx, dy) per arrow key, in native pixels. `keyval` names, so this module
#: does not need Gdk.
_ARROWS = {"Left": (-1, 0), "Right": (1, 0), "Up": (0, -1), "Down": (0, 1)}


def nudge_step(name: str, shift: bool) -> tuple[int, int] | None:
    """How far an arrow key moves the corner being dragged: 1 pixel, 10 with Shift."""
    step = _ARROWS.get(name)
    if step is None:
        return None
    k = 10 if shift else 1
    return step[0] * k, step[1] * k


def native_rect(a, b, k: float, size: tuple[int, int], nudge: tuple[int, int] = (0, 0),
                square: bool = False) -> tuple[int, int, int, int]:
    """The rectangle between two logical points as whole NATIVE pixels: x, y, w, h.

    `k` is native pixels per logical pixel (1.25 on a 1.25x output), `size` the
    monitor's native size. The rectangle is rounded once, in native pixels, so
    its edges are on real pixels rather than on 1.25-pixel steps. `nudge` moves
    the second corner by native pixels (the arrow keys); `square` is Shift.
    """
    import math

    nw, nh = size

    def clamp(v: float, hi: int) -> float:
        return max(0.0, min(float(hi), v))

    ax, ay = clamp(a[0] * k, nw), clamp(a[1] * k, nh)
    bx, by = clamp(b[0] * k + nudge[0], nw), clamp(b[1] * k + nudge[1], nh)
    if square:
        side = max(abs(bx - ax), abs(by - ay))
        bx = clamp(ax + math.copysign(side, bx - ax or 1), nw)
        by = clamp(ay + math.copysign(side, by - ay or 1), nh)
    x0, x1 = sorted((round(ax), round(bx)))
    y0, y1 = sorted((round(ay), round(by)))
    return (x0, y0, x1 - x0, y1 - y0)
