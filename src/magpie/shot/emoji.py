"""Emoji catalogue and platform-specific sticker rendering.

Provides parsed emoji data, search ranking, font capability detection,
multi-platform sticker rendering via Pillow CBDT fonts, and MRU recents tracking.
"""

from __future__ import annotations

import functools
import json
import os
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

__all__ = [
    "FONT_DIR",
    "DATA",
    "PLATFORMS",
    "Platform",
    "Emoji",
    "available_platforms",
    "catalogue",
    "groups",
    "search",
    "supports",
    "sticker",
    "Recents",
]

FONT_DIR = Path.home() / ".local/share/magpie-fonts"
DATA = Path(__file__).resolve().parent / "data" / "emoji.tsv"


@dataclass(frozen=True)
class Platform:
    id: str
    label: str
    path: Path
    strike: int


@dataclass(frozen=True)
class Emoji:
    char: str
    group: str
    subgroup: str
    name: str
    keywords: tuple[str, ...]


PLATFORMS: tuple[Platform, ...] = (
    Platform("apple", "Apple", FONT_DIR / "apple-color-emoji.ttf", 96),
    Platform("whatsapp", "WhatsApp", FONT_DIR / "whatsapp-emoji.ttf", 136),
    Platform("google", "Google / Android", Path("/usr/share/fonts/noto/NotoColorEmoji.ttf"), 109),
    Platform("microsoft", "Microsoft (Fluent)", FONT_DIR / "fluent-emoji-color.ttf", 109),
    Platform("openmoji", "OpenMoji", FONT_DIR / "openmoji.ttf", 99),
    Platform("joypixels", "JoyPixels", FONT_DIR / "joypixels.ttf", 109),
)


@functools.lru_cache(maxsize=16)
def _load_font(path_str: str, strike: int) -> ImageFont.FreeTypeFont:
    """Load and cache FreeType fonts by path and strike size."""
    if not os.path.exists(path_str):
        raise FileNotFoundError(f"Font file not found: {path_str}")
    return ImageFont.truetype(path_str, strike)


def available_platforms(font_dir: Path = FONT_DIR) -> list[Platform]:
    """Return platforms whose font file exists."""
    result: list[Platform] = []
    for p in PLATFORMS:
        if font_dir != FONT_DIR and (font_dir / p.path.name).exists():
            result.append(Platform(p.id, p.label, font_dir / p.path.name, p.strike))
        elif p.path.exists():
            if font_dir == FONT_DIR or p.path.is_absolute():
                result.append(p)
    return result


@functools.cache
def catalogue(path: Path = DATA) -> list[Emoji]:
    """Parse and return the full emoji catalogue from TSV data."""
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    items: list[Emoji] = []
    for line in lines:
        parts = line.rstrip("\r\n").split("\t")
        if len(parts) != 5:
            continue
        char, group, subgroup, name, kw_raw = parts
        keywords = tuple(kw.strip() for kw in kw_raw.split(" | ") if kw.strip())
        items.append(Emoji(
            char=char,
            group=group,
            subgroup=subgroup,
            name=name,
            keywords=keywords,
        ))
    return items


def groups(items: list[Emoji] | None = None) -> list[str]:
    """Return unique group names in file order, excluding Component."""
    if items is None:
        items = catalogue()
    seen: set[str] = set()
    result: list[str] = []
    for e in items:
        if e.group == "Component":
            continue
        if e.group not in seen:
            seen.add(e.group)
            result.append(e.group)
    return result


def search(query: str, items: list[Emoji] | None = None, limit: int = 120) -> list[Emoji]:
    """Search emojis case-insensitively, ranking name matches above keyword matches."""
    if items is None:
        items = catalogue()

    q_clean = query.strip()
    if not q_clean:
        return [e for e in items if e.group != "Component"][:limit]

    q_lower = q_clean.lower()
    terms = q_lower.split()

    def get_rank(e: Emoji) -> int | None:
        if e.char == q_clean:
            return 0

        name_lower = e.name.lower()
        kws_lower = [kw.lower() for kw in e.keywords]

        for t in terms:
            if t in name_lower:
                continue
            if any(t in kw for kw in kws_lower):
                continue
            if t in e.char:
                continue
            return None

        if name_lower == q_lower:
            return 1
        elif name_lower.startswith(q_lower):
            return 2
        elif q_lower in name_lower:
            return 3
        else:
            return 4

    matches: list[tuple[int, Emoji]] = []
    for e in items:
        rank = get_rank(e)
        if rank is not None:
            matches.append((rank, e))

    matches.sort(key=lambda pair: pair[0])
    return [e for _, e in matches][:limit]


_supports_cache: dict[tuple[str, str], bool] = {}


def supports(platform: Platform, char: str) -> bool:
    """Check if platform font renders char without falling back to missing glyph."""
    key = (platform.id, char)
    if key in _supports_cache:
        return _supports_cache[key]

    if not platform.path.exists():
        _supports_cache[key] = False
        return False

    try:
        font = _load_font(str(platform.path), platform.strike)
    except Exception:
        _supports_cache[key] = False
        return False

    w, h = platform.strike * 4, platform.strike * 2

    def _render(t: str) -> Image.Image:
        im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(im).text((10, 10), t, font=font, embedded_color=True)
        return im

    miss = _render("\U0010FFFF")
    miss_bytes = miss.tobytes()

    c_im = _render(char)
    if c_im.tobytes() == miss_bytes:
        _supports_cache[key] = False
        return False

    c_bbox = c_im.getbbox()
    if not c_bbox:
        _supports_cache[key] = False
        return False

    clean = char.replace("\ufe0f", "").replace("\ufe0e", "")
    if len(clean) == 1:
        _supports_cache[key] = True
        return True

    ref = _render("😀")
    ref_bbox = ref.getbbox()
    if not ref_bbox:
        _supports_cache[key] = False
        return False

    ref_w = ref_bbox[2] - ref_bbox[0]
    char_w = c_bbox[2] - c_bbox[0]
    supported = (char_w < 1.5 * ref_w)
    _supports_cache[key] = supported
    return supported


def sticker(platform: Platform, char: str, size: int = 256) -> Image.Image:
    """Render a centred, scaled RGBA sticker for the given platform and emoji."""
    if not platform.path.exists():
        raise FileNotFoundError(f"Font file not found: {platform.path}")

    font = _load_font(str(platform.path), platform.strike)
    canvas_dim = platform.strike * 2
    canvas = Image.new("RGBA", (canvas_dim, canvas_dim), (0, 0, 0, 0))
    offset = (platform.strike // 2, platform.strike // 2)
    ImageDraw.Draw(canvas).text(offset, char, font=font, embedded_color=True)

    alpha = canvas.getchannel("A")
    bbox = alpha.getbbox()
    if not bbox:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))

    crop = canvas.crop(bbox)
    cw, ch = crop.size
    if cw >= ch:
        nw = size
        nh = max(1, round(ch * size / cw))
    else:
        nh = size
        nw = max(1, round(cw * size / ch))

    scaled = crop.resize((nw, nh), Image.LANCZOS)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(scaled, ((size - nw) // 2, (size - nh) // 2))
    return out


class Recents:
    """Tiny persistent MRU of emoji characters."""

    def __init__(self, path: Path, limit: int = 24) -> None:
        self.path = Path(path)
        self.limit = limit

    def items(self) -> list[str]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return [str(x) for x in data if isinstance(x, str)]
            return []
        except Exception:
            return []

    def add(self, char: str) -> None:
        current = self.items()
        if char in current:
            current.remove(char)
        current.insert(0, char)
        current = current[: self.limit]

        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp_file = self.path.parent / f".{self.path.name}.tmp"
        try:
            tmp_file.write_text(json.dumps(current, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp_file, self.path)
        except BaseException:
            tmp_file.unlink(missing_ok=True)
            raise
