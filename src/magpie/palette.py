"""The colours, which are not magpie's to choose.

Noctalia regenerates the desktop's palette from the wallpaper and writes it to
`~/.config/hypr/noctalia.lua` on every change. The clipboard belongs to this
desktop rather than to itself, so it reads that file and derives everything
from it: the greys are the wallpaper's own surface colour stepped up and down,
and the one accent is the wallpaper's primary.

Two things are *not* taken from the wallpaper. The star is yellow because a
star is yellow, and the danger colour is the theme's own error colour, because
both of those mean something rather than matching something.

Nothing in here needs a screen, so all of it is tested. A missing file, half a
file or a file full of nonsense all mean the same thing: the defaults, because
a clipboard that will not open over a theme file is worse than a beige one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from pathlib import Path

__all__ = ["Palette", "read", "mix", "lighten", "darken", "DEFAULTS", "WHERE"]

#: Where Noctalia writes it. The `.lua` is the live one on this machine; the
#: `.conf` beside it is the same thing for the pre-Lua configuration and is
#: read only when there is no Lua.
WHERE = Path.home() / ".config" / "hypr"
FILES = ("noctalia.lua", "noctalia.conf")

ROLES = ("primary", "surface", "secondary", "error", "tertiary", "surface_lowest")

#: `local primary = "rgb(ffb2ba)"` and `$primary = rgb(c2c6d6)`, in one pass.
_COLOUR = re.compile(
    r"^\s*(?:local\s+|\$)(?P<name>\w+)\s*=\s*\"?rgb\(\s*(?P<hex>[0-9a-fA-F]{6})\s*\)",
    re.MULTILINE)

#: A star is yellow. This one is not the wallpaper's business.
GOLD = "#e8c15a"


def _clamp(value: float) -> int:
    return max(0, min(255, round(value)))


def _rgb(colour: str) -> tuple[int, int, int]:
    colour = colour.lstrip("#")
    return tuple(int(colour[at:at + 2], 16) for at in (0, 2, 4))  # type: ignore[return-value]


def mix(colour: str, into: str, amount: float) -> str:
    """`amount` of the way from one colour to the other."""
    return "#" + "".join(
        f"{_clamp(a + (b - a) * amount):02x}"
        for a, b in zip(_rgb(colour), _rgb(into)))


def lighten(colour: str, amount: float) -> str:
    return mix(colour, "#ffffff", amount)


def darken(colour: str, amount: float) -> str:
    return mix(colour, "#000000", amount)


def luminance(colour: str) -> float:
    red, green, blue = _rgb(colour)
    return (0.2126 * red + 0.7152 * green + 0.0722 * blue) / 255


@dataclass(frozen=True)
class Palette:
    """What Noctalia says, and what the window makes of it.

    The named roles are what the stylesheet asks for. They are derived rather
    than listed so that any wallpaper works — including a light one, where the
    whole thing turns over.
    """

    primary: str
    surface: str
    secondary: str
    error: str
    tertiary: str
    surface_lowest: str

    @property
    def dark(self) -> bool:
        return luminance(self.surface) < 0.5

    def _step(self, amount: float) -> str:
        """Away from the surface, in whichever direction is away from it."""
        return (lighten(self.surface, amount) if self.dark
                else darken(self.surface, amount))

    def _toward_edge(self, amount: float) -> str:
        """Towards the surface, the other way — under it on a dark theme."""
        return (darken(self.surface, amount) if self.dark
                else lighten(self.surface, amount))

    # -- the three panels, a step apart --------------------------------------

    @property
    def rail(self) -> str:
        return self._toward_edge(0.45)

    @property
    def ink(self) -> str:
        return self.surface

    @property
    def pane(self) -> str:
        return self._step(0.05)

    @property
    def slate(self) -> str:
        """A row under the pointer."""
        return self._step(0.08)

    @property
    def quill(self) -> str:
        """A selected row, and every border in the window."""
        return self._step(0.14)

    @property
    def edge(self) -> str:
        """The window's own outline, since a layer surface has no border."""
        return self._step(0.19)

    # -- the text ------------------------------------------------------------

    @property
    def bone(self) -> str:
        """What you read. Tinted by the wallpaper rather than plain white."""
        far = "#ffffff" if self.dark else "#0b0b0d"
        return mix(far, self.primary, 0.14)

    @property
    def ash(self) -> str:
        """The second line of a row: there, but not competing."""
        return mix(self.bone, self.surface, 0.42)

    @property
    def faint(self) -> str:
        return mix(self.bone, self.surface, 0.62)

    # -- the things that mean something --------------------------------------

    @property
    def accent(self) -> str:
        return self.primary

    @property
    def accent_dim(self) -> str:
        return mix(self.surface, self.primary, 0.22)

    @property
    def on_accent(self) -> str:
        """Text on top of the accent, whichever way round that has to be."""
        return "#12121a" if luminance(self.primary) > 0.5 else "#ffffff"

    @property
    def danger(self) -> str:
        return self.error

    @property
    def gold(self) -> str:
        return GOLD


DEFAULTS = Palette(primary="#98ccf9", surface="#101417", secondary="#b8c8d9",
                   error="#ffb4ab", tertiary="#d0bfe7", surface_lowest="#0b0f12")


def read(where: Path | str = WHERE) -> Palette:
    """The palette Noctalia last wrote, or the defaults."""
    for name in FILES:
        try:
            text = (Path(where) / name).read_text(errors="replace")
        except OSError:
            continue
        found = {match["name"]: "#" + match["hex"].lower()
                 for match in _COLOUR.finditer(text)
                 if match["name"] in ROLES}
        if found:
            return replace(DEFAULTS, **found)
    return DEFAULTS
