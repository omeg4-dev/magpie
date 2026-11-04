from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from magpie.shot.emoji import (
    DATA,
    FONT_DIR,
    PLATFORMS,
    Emoji,
    Platform,
    Recents,
    available_platforms,
    catalogue,
    groups,
    search,
    sticker,
    supports,
)


def test_catalogue_parse():
    items = catalogue()
    assert len(items) > 1500
    first = items[0]
    assert first.char == "😀"
    assert first.name == "grinning face"
    assert first.group == "Smileys & Emotion"
    assert "grin" in first.keywords

    # search("") has no entry with group "Component"
    empty_results = search("")
    assert empty_results
    assert not any(e.group == "Component" for e in empty_results)


def test_groups():
    grp_list = groups()
    assert len(grp_list) > 0
    assert grp_list[0] == "Smileys & Emotion"
    assert "Component" not in grp_list


def test_search_queries():
    # search("grin") has 😀 within the top 5
    grin_results = [e.char for e in search("grin")[:5]]
    assert "😀" in grin_results

    # search("rocket") contains 🚀
    rocket_results = [e.char for e in search("rocket")]
    assert "🚀" in rocket_results

    # search("🚀") returns 🚀 first
    emoji_results = search("🚀")
    assert len(emoji_results) > 0
    assert emoji_results[0].char == "🚀"

    # nonsense query returns []
    assert search("xyz_nonexistent_query_12345") == []


def test_recents(tmp_path):
    recents_file = tmp_path / "recents.json"
    r = Recents(recents_file, limit=3)

    # Missing file returns []
    assert r.items() == []

    # Add items
    r.add("😀")
    r.add("🚀")
    assert r.items() == ["🚀", "😀"]

    # Dedupe and move to front
    r.add("😀")
    assert r.items() == ["😀", "🚀"]

    # Limit truncation
    r.add("🔥")
    r.add("🎉")
    assert r.items() == ["🎉", "🔥", "😀"]
    assert len(r.items()) == 3

    # Corrupt file reads as empty
    recents_file.write_text("invalid json content {{{")
    assert r.items() == []


@pytest.mark.parametrize("platform", PLATFORMS, ids=lambda p: p.id)
def test_supports_and_missing_char(platform: Platform):
    if not platform.path.exists():
        pytest.skip(f"Font for platform {platform.id} not installed at {platform.path}")

    assert supports(platform, "😀") is True
    assert supports(platform, "\U0010FFFF") is False


@pytest.mark.parametrize("platform", PLATFORMS, ids=lambda p: p.id)
def test_sticker_rendering(platform: Platform):
    if not platform.path.exists():
        pytest.skip(f"Font for platform {platform.id} not installed at {platform.path}")

    size = 128
    img = sticker(platform, "🚀", size)

    assert img.size == (size, size)
    assert img.mode == "RGBA"

    # Transparent corner pixel (alpha 0)
    assert img.getpixel((0, 0))[3] == 0

    # At least 15% non-transparent pixels with more than 3 distinct hues (RGB)
    raw_bytes = img.tobytes()
    # Each pixel is 4 bytes (R, G, B, A)
    total_pixels = size * size
    non_transparent = []
    for i in range(0, len(raw_bytes), 4):
        r, g, b, a = raw_bytes[i : i + 4]
        if a > 0:
            non_transparent.append((r, g, b))

    assert len(non_transparent) / total_pixels >= 0.15
    distinct_colors = set(non_transparent)
    assert len(distinct_colors) > 3


def test_apple_vs_whatsapp_distinct_pixels():
    apple = next(p for p in PLATFORMS if p.id == "apple")
    whatsapp = next(p for p in PLATFORMS if p.id == "whatsapp")

    if not apple.path.exists():
        pytest.skip("Apple font not available")
    if not whatsapp.path.exists():
        pytest.skip("WhatsApp font not available")

    img_apple = sticker(apple, "🚀", 128)
    img_whatsapp = sticker(whatsapp, "🚀", 128)

    assert img_apple.tobytes() != img_whatsapp.tobytes()
