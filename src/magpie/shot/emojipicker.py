"""Picking an emoji, and which company's drawing of it you get.

An emoji is a character, and every platform draws it differently — the same 🔥
is a different picture on an iPhone, in WhatsApp, on Android and in Windows.
Screenshots mostly end up in a chat, so the platform is a real choice: pick the
one your friends see. The picker previews every emoji in the chosen platform's
own font, and what is placed on the screenshot is exactly that picture.
"""

from __future__ import annotations

import json
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, GObject, Gtk  # noqa: E402

from . import emoji  # noqa: E402
from .render import from_pil  # noqa: E402

__all__ = ["EmojiPicker"]

STATE = Path(GLib.get_user_state_dir()) / "magpie"
THUMB = 64

#: What is handed to the editor. Fonts only carry ~100-160 px bitmaps, so anything
#: bigger than that is an upscale; doing it once here, with a good filter, keeps big
#: stickers smooth instead of leaving cairo to stretch a small raster.
PLACED = 512
CELL = 42

#: One representative per group, for the strip under the search box.
GROUP_ICONS = {
    "Smileys & Emotion": "😀", "People & Body": "👋", "Animals & Nature": "🐻",
    "Food & Drink": "🍔", "Travel & Places": "🚗", "Activities": "⚽",
    "Objects": "💡", "Symbols": "❤️", "Flags": "🏁",
}


class EmojiPicker(Gtk.Popover):
    __gsignals__ = {"picked": (GObject.SignalFlags.RUN_FIRST, None, (object, str, str))}

    def __init__(self, recents_path: Path | None = None) -> None:
        super().__init__()
        self.add_css_class("emoji")
        self.set_has_arrow(False)
        self.set_position(Gtk.PositionType.RIGHT)
        self.set_autohide(True)

        self.platforms = emoji.available_platforms()
        self.recents = emoji.Recents(recents_path or STATE / "emoji-recents.json")
        self._thumbs: dict[tuple[str, str], Gdk.Texture] = {}
        self.group: str | None = None
        self.platform = self._load_platform()

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.set_size_request(500, 440)
        self.set_child(box)

        chips = Gtk.Box(spacing=1, homogeneous=True)
        chips.add_css_class("platforms")
        self._chips: dict[str, Gtk.ToggleButton] = {}
        first = None
        for p in self.platforms:
            chip = Gtk.ToggleButton(label=p.label.split(' ')[0])
            chip.set_focusable(False)
            if first is None:
                first = chip
            else:
                chip.set_group(first)
            chip.connect("toggled", self._platform_toggled, p.id)
            self._chips[p.id] = chip
            chips.append(chip)
        box.append(chips)

        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Search emoji")
        self.search.connect("search-changed", lambda *_: self._refill())
        self.search.connect("activate", self._first)
        box.append(self.search)

        groups = Gtk.Box(spacing=2)
        groups.add_css_class("groups")
        self._groups: dict[str | None, Gtk.ToggleButton] = {}
        first = None
        for name, label in (("recent", "🕘"), *GROUP_ICONS.items()):
            button = Gtk.ToggleButton(label=label)
            button.set_focusable(False)
            button.set_tooltip_text("Recent" if name == "recent" else name)
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.connect("toggled", self._group_toggled, name)
            self._groups[name] = button
            groups.append(button)
        box.append(groups)

        self.model = Gtk.StringList()
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", self._setup)
        factory.connect("bind", self._bind)
        self.grid = Gtk.GridView(model=Gtk.NoSelection(model=self.model), factory=factory)
        self.grid.add_css_class("emoji")
        self.grid.set_min_columns(10)
        self.grid.set_max_columns(10)
        self.grid.set_single_click_activate(True)
        self.grid.connect("activate", self._activated)
        scroller = Gtk.ScrolledWindow()
        scroller.set_vexpand(True)
        scroller.set_child(self.grid)
        self.empty = Gtk.Label(label="Nothing matches")
        self.empty.add_css_class("empty")
        self.empty.set_visible(False)
        box.append(scroller)
        box.append(self.empty)

        self.connect("map", self._mapped)
        self._chips[self.platform.id].set_active(True)

    # -- platform and state -------------------------------------------------

    def _load_platform(self) -> emoji.Platform:
        wanted = None
        try:
            wanted = json.loads((STATE / "shot.json").read_text()).get("platform")
        except (OSError, ValueError, AttributeError):
            pass
        for p in self.platforms:
            if p.id == wanted:
                return p
        return self.platforms[0]

    def _save_platform(self) -> None:
        try:
            STATE.mkdir(parents=True, exist_ok=True)
            (STATE / "shot.json").write_text(json.dumps({"platform": self.platform.id}))
        except OSError:
            pass

    def _platform_toggled(self, button: Gtk.ToggleButton, platform_id: str) -> None:
        if not button.get_active():
            return
        self.platform = next(p for p in self.platforms if p.id == platform_id)
        self._save_platform()
        self._refill()

    def _group_toggled(self, button: Gtk.ToggleButton, name: str) -> None:
        if button.get_active():
            self.group = name
            self.search.set_text("")
            self._refill()

    def _mapped(self, *_args) -> None:
        self.search.set_text("")
        recent = bool(self.recents.items())
        self._groups["recent" if recent else "Smileys & Emotion"].set_active(True)
        self._refill()
        self.search.grab_focus()

    # -- the grid -----------------------------------------------------------

    def _refill(self) -> None:
        query = self.search.get_text().strip()
        if query:
            chars = [e.char for e in emoji.search(query, limit=180)]
        elif self.group == "recent":
            chars = self.recents.items()
        else:
            chars = [e.char for e in emoji.catalogue() if e.group == self.group]
        self.model.splice(0, self.model.get_n_items(), chars)
        self.empty.set_visible(not chars)

    def _setup(self, _factory, item: Gtk.ListItem) -> None:
        picture = Gtk.Picture()
        picture.set_size_request(CELL, CELL)
        picture.set_content_fit(Gtk.ContentFit.CONTAIN)
        picture.set_margin_top(3)
        picture.set_margin_bottom(3)
        picture.set_margin_start(3)
        picture.set_margin_end(3)
        item.set_child(picture)

    def _bind(self, _factory, item: Gtk.ListItem) -> None:
        char = item.get_item().get_string()
        picture = item.get_child()
        picture.set_paintable(self._thumb(char))
        picture.set_tooltip_text(emoji.name_of(char))

    def _thumb(self, char: str) -> Gdk.Texture | None:
        key = (self.platform.id, char)
        texture = self._thumbs.get(key)
        if texture is None:
            try:
                image = emoji.sticker(self.platform, char, THUMB)
            except OSError:
                return None
            texture = Gdk.MemoryTexture.new(
                THUMB, THUMB, Gdk.MemoryFormat.R8G8B8A8,
                GLib.Bytes.new(image.tobytes()), THUMB * 4)
            self._thumbs[key] = texture
        return texture

    # -- choosing -----------------------------------------------------------

    def _activated(self, _grid, position: int) -> None:
        self._choose(self.model.get_string(position))

    def _first(self, *_args) -> None:
        if self.model.get_n_items():
            self._choose(self.model.get_string(0))

    def _choose(self, char: str) -> None:
        self.recents.add(char)
        surface = from_pil(emoji.sticker(self.platform, char, PLACED))
        self.emit("picked", surface, char, self.platform.id)
