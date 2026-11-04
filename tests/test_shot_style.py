from magpie.palette import DEFAULTS
from magpie.shot import icons, style
from magpie.shot.editor import TOOLS
from magpie.shot.model import PALETTE


def test_css_has_a_swatch_per_palette_colour():
    sheet = style.css(DEFAULTS)
    for i, colour in enumerate(PALETTE):
        assert f".sw{i} {{ background: {colour}; }}" in sheet


def test_every_tool_has_an_icon():
    for _tool, icon, _tip, _key in TOOLS:
        assert icon in icons.NAMES


def test_tool_keys_are_unique():
    keys = [key for *_rest, key in TOOLS]
    assert len(keys) == len(set(keys))
