"""What an edited screenshot *is*: a list of objects, in pixels of the picture.

Nothing here knows about GTK or cairo. A screenshot is annotated with shapes
that stay editable until the moment it is saved — you can grab an arrow you
drew a minute ago and move it — so they are objects rather than paint, and the
objects are what gets undone. That also makes the whole editor testable
without a display: the renderer draws these, the window moves them, and the
rules about what a click hits live here.

All coordinates are in **image pixels**, never screen pixels. The window
scales between the two; a 4-pixel arrow is 4 pixels in the saved file however
small the editor shows it.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field
from enum import Enum
from typing import ClassVar, Iterator

__all__ = [
    "Tool", "Item", "Arrow", "Line", "Rect", "Ellipse", "Pen", "Highlighter",
    "Text", "Badge", "Blur", "Pixelate", "Redact", "Sticker", "Doc",
    "PALETTE", "rgba", "contrast",
]

Color = tuple[float, float, float, float]
Rect4 = tuple[float, float, float, float]  # x, y, w, h

#: Annotation colours have to read against *any* screenshot, so this is a fixed
#: high-contrast set and deliberately not the wallpaper palette.
PALETTE: tuple[str, ...] = (
    "#ff3b30", "#ff9500", "#ffd60a", "#34c759", "#32ade6",
    "#0a84ff", "#bf5af2", "#ffffff", "#000000",
)


def rgba(value: str, alpha: float = 1.0) -> Color:
    value = value.lstrip("#")
    return (int(value[0:2], 16) / 255, int(value[2:4], 16) / 255,
            int(value[4:6], 16) / 255, alpha)


def contrast(color: Color) -> Color:
    """Black or white, whichever reads on top of `color`."""
    r, g, b, _ = color
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return (0.0, 0.0, 0.0, 1.0) if luminance > 0.6 else (1.0, 1.0, 1.0, 1.0)


class Tool(str, Enum):
    SELECT = "select"
    ARROW = "arrow"
    LINE = "line"
    RECT = "rect"
    ELLIPSE = "ellipse"
    PEN = "pen"
    HIGHLIGHTER = "highlighter"
    TEXT = "text"
    BADGE = "badge"
    BLUR = "blur"
    PIXELATE = "pixelate"
    REDACT = "redact"
    STICKER = "sticker"


# -- geometry ---------------------------------------------------------------

def _segment_distance(px: float, py: float, ax: float, ay: float,
                      bx: float, by: float) -> float:
    dx, dy = bx - ax, by - ay
    length2 = dx * dx + dy * dy
    if length2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length2))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def _normal(a: float, b: float) -> tuple[float, float]:
    return (a, b) if a <= b else (b, a)


@dataclass(eq=False)
class Item:
    """Base of everything on the picture. `id` is assigned by the Doc."""

    kind: ClassVar[str] = "item"
    #: Whether Esc/Enter in the text box and the like apply; only Text is editable.
    editable: ClassVar[bool] = False

    id: int = field(default=0, kw_only=True)

    def bounds(self) -> Rect4:  # pragma: no cover - overridden
        raise NotImplementedError

    def hit(self, x: float, y: float, tol: float = 6.0) -> bool:
        bx, by, bw, bh = self.bounds()
        return bx - tol <= x <= bx + bw + tol and by - tol <= y <= by + bh + tol

    def translate(self, dx: float, dy: float) -> None:  # pragma: no cover
        raise NotImplementedError

    def handles(self) -> dict[str, tuple[float, float]]:
        return {}

    def drag_handle(self, name: str, x: float, y: float, *, keep_ratio: bool = False) -> None:
        pass


@dataclass(eq=False)
class _TwoPoint(Item):
    """Shapes defined by where the drag started and where it is now."""

    p0: tuple[float, float] = (0.0, 0.0)
    p1: tuple[float, float] = (0.0, 0.0)
    color: Color = (1.0, 0.23, 0.19, 1.0)
    width: float = 4.0

    def bounds(self) -> Rect4:
        x0, x1 = _normal(self.p0[0], self.p1[0])
        y0, y1 = _normal(self.p0[1], self.p1[1])
        return (x0, y0, x1 - x0, y1 - y0)

    def translate(self, dx: float, dy: float) -> None:
        self.p0 = (self.p0[0] + dx, self.p0[1] + dy)
        self.p1 = (self.p1[0] + dx, self.p1[1] + dy)

    def length(self) -> float:
        return math.hypot(self.p1[0] - self.p0[0], self.p1[1] - self.p0[1])


@dataclass(eq=False)
class _Linear(_TwoPoint):
    """A line from one point to another: arrow and plain line."""

    def hit(self, x: float, y: float, tol: float = 6.0) -> bool:
        return _segment_distance(x, y, *self.p0, *self.p1) <= tol + self.width / 2

    def handles(self) -> dict[str, tuple[float, float]]:
        return {"p0": self.p0, "p1": self.p1}

    def drag_handle(self, name: str, x: float, y: float, *, keep_ratio: bool = False) -> None:
        if name == "p0":
            self.p0 = (x, y)
        elif name == "p1":
            self.p1 = _snap(self.p0, (x, y)) if keep_ratio else (x, y)


def _snap(origin: tuple[float, float], point: tuple[float, float]) -> tuple[float, float]:
    """Nearest of the eight compass directions: what Shift does to a line."""
    dx, dy = point[0] - origin[0], point[1] - origin[1]
    length = math.hypot(dx, dy)
    if length == 0:
        return point
    angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    return (origin[0] + length * math.cos(angle), origin[1] + length * math.sin(angle))


@dataclass(eq=False)
class Arrow(_Linear):
    kind: ClassVar[str] = "arrow"


@dataclass(eq=False)
class Line(_Linear):
    kind: ClassVar[str] = "line"


@dataclass(eq=False)
class _Box(_TwoPoint):
    """A rectangle's worth of shape: four corner handles, drag to resize."""

    fill: bool = False

    def handles(self) -> dict[str, tuple[float, float]]:
        x, y, w, h = self.bounds()
        return {"nw": (x, y), "ne": (x + w, y), "sw": (x, y + h), "se": (x + w, y + h)}

    def drag_handle(self, name: str, x: float, y: float, *, keep_ratio: bool = False) -> None:
        bx, by, bw, bh = self.bounds()
        # The corner opposite the one being dragged stays where it is.
        fixed = {"nw": (bx + bw, by + bh), "ne": (bx, by + bh),
                 "sw": (bx + bw, by), "se": (bx, by)}.get(name)
        if fixed is None:
            return
        if keep_ratio:
            side = max(abs(x - fixed[0]), abs(y - fixed[1]))
            x = fixed[0] + math.copysign(side, x - fixed[0] or 1)
            y = fixed[1] + math.copysign(side, y - fixed[1] or 1)
        self.p0, self.p1 = fixed, (x, y)


@dataclass(eq=False)
class Rect(_Box):
    kind: ClassVar[str] = "rect"

    def hit(self, x: float, y: float, tol: float = 6.0) -> bool:
        bx, by, bw, bh = self.bounds()
        reach = tol + self.width / 2
        inside = bx - reach <= x <= bx + bw + reach and by - reach <= y <= by + bh + reach
        if not inside or self.fill:
            return inside
        # An outline: only near the border, so the picture under a frame
        # stays clickable.
        return not (bx + reach < x < bx + bw - reach and by + reach < y < by + bh - reach)


@dataclass(eq=False)
class Ellipse(_Box):
    kind: ClassVar[str] = "ellipse"

    def hit(self, x: float, y: float, tol: float = 6.0) -> bool:
        bx, by, bw, bh = self.bounds()
        rx, ry = bw / 2 + tol + self.width / 2, bh / 2 + tol + self.width / 2
        if rx <= 0 or ry <= 0:
            return False
        nx, ny = (x - (bx + bw / 2)) / rx, (y - (by + bh / 2)) / ry
        distance = nx * nx + ny * ny
        if distance > 1:
            return False
        if self.fill:
            return True
        irx, iry = bw / 2 - tol - self.width / 2, bh / 2 - tol - self.width / 2
        if irx <= 0 or iry <= 0:
            return True
        inner = ((x - (bx + bw / 2)) / irx) ** 2 + ((y - (by + bh / 2)) / iry) ** 2
        return inner >= 1


@dataclass(eq=False)
class _Stroke(Item):
    """Freehand: a list of points the pointer went through."""

    points: list[tuple[float, float]] = field(default_factory=list)
    color: Color = (1.0, 0.23, 0.19, 1.0)
    width: float = 4.0

    def bounds(self) -> Rect4:
        if not self.points:
            return (0.0, 0.0, 0.0, 0.0)
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        pad = self.reach()
        return (min(xs) - pad, min(ys) - pad, max(xs) - min(xs) + 2 * pad,
                max(ys) - min(ys) + 2 * pad)

    def reach(self) -> float:
        return self.width / 2

    def hit(self, x: float, y: float, tol: float = 6.0) -> bool:
        reach = tol + self.reach()
        if len(self.points) == 1:
            return math.hypot(x - self.points[0][0], y - self.points[0][1]) <= reach
        return any(_segment_distance(x, y, *a, *b) <= reach
                   for a, b in zip(self.points, self.points[1:]))

    def translate(self, dx: float, dy: float) -> None:
        self.points = [(px + dx, py + dy) for px, py in self.points]


@dataclass(eq=False)
class Pen(_Stroke):
    kind: ClassVar[str] = "pen"


@dataclass(eq=False)
class Highlighter(_Stroke):
    """A wide, see-through marker. The renderer makes it that way; `width` is
    the pen width and the marker is a few times fatter."""

    kind: ClassVar[str] = "highlighter"
    SCALE: ClassVar[float] = 4.0

    def reach(self) -> float:
        return self.width * self.SCALE / 2


@dataclass(eq=False)
class Text(Item):
    kind: ClassVar[str] = "text"
    editable: ClassVar[bool] = True

    x: float = 0.0
    y: float = 0.0
    text: str = ""
    color: Color = (1.0, 0.23, 0.19, 1.0)
    size: float = 28.0
    #: Measured by the renderer (it owns the fonts) whenever text or size
    #: changes, so hits and handles do not need a font of their own.
    w: float = 0.0
    h: float = 0.0

    def bounds(self) -> Rect4:
        return (self.x, self.y, self.w, self.h)

    def translate(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy


@dataclass(eq=False)
class Badge(Item):
    """A numbered circle: step 1, step 2, in the order they were placed."""

    kind: ClassVar[str] = "badge"

    x: float = 0.0  # centre
    y: float = 0.0
    n: int = 1
    color: Color = (1.0, 0.23, 0.19, 1.0)
    radius: float = 16.0

    def bounds(self) -> Rect4:
        return (self.x - self.radius, self.y - self.radius, 2 * self.radius, 2 * self.radius)

    def hit(self, x: float, y: float, tol: float = 6.0) -> bool:
        return math.hypot(x - self.x, y - self.y) <= self.radius + tol

    def translate(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy


@dataclass(eq=False)
class _Region(_TwoPoint):
    """Something done to the pixels under a rectangle. Reads the original
    picture, never the other annotations, so a blur never smears an arrow."""

    strength: float = 12.0

    def handles(self) -> dict[str, tuple[float, float]]:
        return _Box.handles(self)  # type: ignore[arg-type]

    def drag_handle(self, name: str, x: float, y: float, *, keep_ratio: bool = False) -> None:
        _Box.drag_handle(self, name, x, y, keep_ratio=keep_ratio)  # type: ignore[arg-type]


@dataclass(eq=False)
class Blur(_Region):
    kind: ClassVar[str] = "blur"
    strength: float = 14.0  # gaussian radius, in image pixels


@dataclass(eq=False)
class Pixelate(_Region):
    kind: ClassVar[str] = "pixelate"
    strength: float = 14.0  # block edge, in image pixels


@dataclass(eq=False)
class Redact(_Region):
    """A solid bar. Unlike a blur nothing of what was underneath survives."""

    kind: ClassVar[str] = "redact"
    color: Color = (0.0, 0.0, 0.0, 1.0)


@dataclass(eq=False)
class Sticker(Item):
    """An emoji, already rendered to a picture by the platform's own font.

    `surface` is the pixels (a cairo surface, set by the editor); the model
    only needs to know the char and platform so it can be described and
    searched, and how big it sits on the page.
    """

    kind: ClassVar[str] = "sticker"

    x: float = 0.0  # centre
    y: float = 0.0
    size: float = 96.0
    char: str = ""
    platform: str = ""
    surface: object | None = None

    def __deepcopy__(self, memo):
        clone = copy.copy(self)  # the pixels are shared, never copied
        memo[id(self)] = clone
        return clone

    def bounds(self) -> Rect4:
        return (self.x - self.size / 2, self.y - self.size / 2, self.size, self.size)

    def translate(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy

    def handles(self) -> dict[str, tuple[float, float]]:
        x, y, w, h = self.bounds()
        return {"nw": (x, y), "ne": (x + w, y), "sw": (x, y + h), "se": (x + w, y + h)}

    def drag_handle(self, name: str, x: float, y: float, *, keep_ratio: bool = True) -> None:
        bx, by, bw, bh = self.bounds()
        fixed = {"nw": (bx + bw, by + bh), "ne": (bx, by + bh),
                 "sw": (bx + bw, by), "se": (bx, by)}.get(name)
        if fixed is None:
            return
        side = max(8.0, max(abs(x - fixed[0]), abs(y - fixed[1])))
        sx = 1 if x >= fixed[0] else -1
        sy = 1 if y >= fixed[1] else -1
        self.size = side
        self.x = fixed[0] + sx * side / 2
        self.y = fixed[1] + sy * side / 2


# -- the document -----------------------------------------------------------

class Doc:
    """The picture's size, its objects in paint order, and the undo history.

    Undo is by snapshot: `checkpoint()` before a change copies the object
    list, and `undo()` swaps it back. Objects are small and a session is a
    few dozen of them, so this is far simpler than inverting every kind of edit
    and cannot get out of step with them.
    """

    LIMIT = 100

    def __init__(self, width: int, height: int) -> None:
        self.width = width
        self.height = height
        self.items: list[Item] = []
        self._undo: list[list[Item]] = []
        self._redo: list[list[Item]] = []
        self._next_id = 1

    # -- sizes that depend on the picture -----------------------------------

    def default_width(self) -> float:
        """A stroke width that looks the same on a 1080p grab and a 4K one."""
        return max(3.0, round(max(self.width, self.height) / 450 * 1.5, 1))

    def default_text_size(self) -> float:
        return max(20.0, round(max(self.width, self.height) / 60))

    def badge_radius(self) -> float:
        return max(13.0, round(max(self.width, self.height) / 130))

    # -- contents -----------------------------------------------------------

    def __iter__(self) -> Iterator[Item]:
        return iter(self.items)

    def __len__(self) -> int:
        return len(self.items)

    def add(self, item: Item) -> Item:
        item.id = self._next_id
        self._next_id += 1
        self.items.append(item)
        return item

    def get(self, item_id: int | None) -> Item | None:
        return next((i for i in self.items if i.id == item_id), None)

    def remove(self, item_id: int) -> bool:
        item = self.get(item_id)
        if item is None:
            return False
        self.items.remove(item)
        return True

    def raise_to_top(self, item_id: int) -> None:
        item = self.get(item_id)
        if item is not None and self.items[-1] is not item:
            self.items.remove(item)
            self.items.append(item)

    def next_badge(self) -> int:
        """The number the next badge takes: one more than the highest here."""
        return max((i.n for i in self.items if isinstance(i, Badge)), default=0) + 1

    def pick(self, x: float, y: float, tol: float = 6.0) -> Item | None:
        """The topmost object under a point."""
        for item in reversed(self.items):
            if item.hit(x, y, tol):
                return item
        return None

    def clear(self) -> None:
        self.checkpoint()
        self.items.clear()

    # -- undo ---------------------------------------------------------------

    def checkpoint(self) -> None:
        """Remember the state as it is now; call before changing anything."""
        self._undo.append(self._snapshot())
        del self._undo[:-self.LIMIT]
        self._redo.clear()

    def discard_checkpoint(self) -> None:
        """Forget the last checkpoint: the gesture it guarded changed nothing."""
        if self._undo:
            self._undo.pop()

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snapshot())
        self.items = self._undo.pop()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snapshot())
        self.items = self._redo.pop()
        return True

    def _snapshot(self) -> list[Item]:
        return copy.deepcopy(self.items)
