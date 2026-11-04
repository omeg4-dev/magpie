"""Viewport maths for panning and zooming a screenshot in a widget.

Coordinates:
- Image pixels (ix, iy): coordinates in the unscaled source image.
- Screen pixels (sx, sy): coordinates in the display widget.
- scale: screen px per image px.
- (ox, oy): screen position of the image origin (top-left, (0, 0)).

All coordinates and calculations are floats.
"""

from __future__ import annotations

import math

__all__ = ["Viewport"]


class Viewport:
    def __init__(
        self,
        image_w: int,
        image_h: int,
        view_w: float,
        view_h: float,
        max_zoom: float = 32.0,
        device_ratio: float = 1.0,
        margin: float = 0.0,
    ) -> None:
        self.image_w = int(image_w)
        self.image_h = int(image_h)
        self.view_w = max(1.0, float(view_w))
        self.view_h = max(1.0, float(view_h))
        self.max_zoom = float(max_zoom)
        self.device_ratio = float(device_ratio)
        self.margin = float(margin)
        self.scale = 1.0
        self.ox = 0.0
        self.oy = 0.0
        self.reset(None)

    @property
    def fit(self) -> float:
        """Scale that makes the whole image fit with margin."""
        vw = max(1.0, self.view_w)
        vh = max(1.0, self.view_h)
        iw = max(1.0, float(self.image_w))
        ih = max(1.0, float(self.image_h))
        if self.margin:
            vw = max(1.0, vw - 2.0 * self.margin)
            vh = max(1.0, vh - 2.0 * self.margin)
        return min(vw / iw, vh / ih)

    @property
    def min_scale(self) -> float:
        """fit / 2, but never above 1.0 and never below 0.02."""
        return max(0.02, min(1.0, self.fit / 2.0))

    @property
    def zoomed(self) -> bool:
        """True if zoomed in beyond fit."""
        return self.scale > self.fit * 1.001

    @property
    def percent(self) -> int:
        """Zoom percentage where scale == 1 / device_ratio is 100%."""
        return round(self.scale * 100.0 * self.device_ratio)

    def to_image(self, sx: float, sy: float) -> tuple[float, float]:
        """Convert screen coordinates to image coordinates."""
        return ((sx - self.ox) / self.scale, (sy - self.oy) / self.scale)

    def to_screen(self, ix: float, iy: float) -> tuple[float, float]:
        """Convert image coordinates to screen coordinates."""
        return (ix * self.scale + self.ox, iy * self.scale + self.oy)

    def clamp(self) -> None:
        """Clamp image position: centred if smaller than view, covering view if larger."""
        vw = max(1.0, self.view_w)
        vh = max(1.0, self.view_h)
        sw = self.image_w * self.scale
        sh = self.image_h * self.scale

        if sw <= vw:
            self.ox = (vw - sw) / 2.0
        else:
            self.ox = max(vw - sw, min(0.0, self.ox))

        if sh <= vh:
            self.oy = (vh - sh) / 2.0
        else:
            self.oy = max(vh - sh, min(0.0, self.oy))

    def reset(self, scale: float | None = None) -> None:
        """Reset scale (None => fit), centre the image, and clamp."""
        if scale is None:
            self.scale = self.fit
        else:
            self.scale = max(self.min_scale, min(self.max_zoom, float(scale)))
        vw = max(1.0, self.view_w)
        vh = max(1.0, self.view_h)
        self.ox = (vw - self.image_w * self.scale) / 2.0
        self.oy = (vh - self.image_h * self.scale) / 2.0
        self.clamp()

    def zoom_at(self, sx: float, sy: float, factor: float) -> bool:
        """Multiply scale by factor about screen point (sx, sy).

        Clamps scale to [min_scale, max_zoom] and clamps origin.
        Returns True if anything changed.
        """
        old_scale, old_ox, old_oy = self.scale, self.ox, self.oy
        target_scale = max(self.min_scale, min(self.max_zoom, self.scale * factor))

        ix, iy = self.to_image(sx, sy)
        self.scale = target_scale
        self.ox = sx - ix * self.scale
        self.oy = sy - iy * self.scale
        self.clamp()

        return not (
            math.isclose(self.scale, old_scale, abs_tol=1e-9)
            and math.isclose(self.ox, old_ox, abs_tol=1e-9)
            and math.isclose(self.oy, old_oy, abs_tol=1e-9)
        )

    def zoom_to(self, scale: float, sx: float | None = None, sy: float | None = None) -> bool:
        """Zoom to an absolute scale, anchored at view centre by default."""
        if sx is None:
            sx = max(1.0, self.view_w) / 2.0
        if sy is None:
            sy = max(1.0, self.view_h) / 2.0
        if self.scale <= 0.0:
            factor = 1.0
        else:
            factor = scale / self.scale
        return self.zoom_at(sx, sy, factor)

    def pan(self, dx: float, dy: float) -> bool:
        """Add (dx, dy) to image origin, then clamp. Return True if moved."""
        old_ox, old_oy = self.ox, self.oy
        self.ox += dx
        self.oy += dy
        self.clamp()
        return not (
            math.isclose(self.ox, old_ox, abs_tol=1e-9)
            and math.isclose(self.oy, old_oy, abs_tol=1e-9)
        )

    def resize(self, view_w: float, view_h: float) -> None:
        """Widget changed size: re-centre if it fits, keep centre where it was if zoomed."""
        self.view_w = max(1.0, float(view_w))
        self.view_h = max(1.0, float(view_h))
        self.clamp()
