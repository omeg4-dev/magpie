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
from .thumbs import Thumbs  # noqa: E402

__all__ = ["EmojiPicker"]

STATE = Path(GLib.get_user_state_dir()) / "magpie"
THUMB = 56

#: How many of each group are drawn ahead of time, so the first screen of any group is instant.
PREFETCH = 150

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
        self._thumbs: dict[str, Thumbs] = {}        # platform id -> its drawing queue
        self._bound: dict[Gtk.ListItem, str] = {}   # the cells on screen -> their character
        self._asked: list[tuple[int, str]] = []     # cells waiting to be drawn this frame
        self._holding = False                       # several changes under way: refill once
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
        factory.connect("unbind", self._unbind)
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
        GLib.timeout_add(1200, self.prefetch)       # after the windows are up, off the critical path

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
        self._queue_for(self.platform).forget_queue()
        self.platform = next(p for p in self.platforms if p.id == platform_id)
        self._save_platform()
        self._refill()
        self.prefetch()

    def _group_toggled(self, button: Gtk.ToggleButton, name: str) -> None:
        if button.get_active():
            self.group = name
            self._holding = True
            self.search.set_text("")
            self._holding = False
            self._refill()

    def _mapped(self, *_args) -> None:
        self._holding = True            # three changes below, one refill after them
        self.search.set_text("")
        recent = bool(self.recents.items())
        self._groups["recent" if recent else "Smileys & Emotion"].set_active(True)
        self._holding = False
        self._refill()
        self.search.grab_focus()

    # -- the grid -----------------------------------------------------------

    def _refill(self) -> None:
        if self._holding:
            return
        query = self.search.get_text().strip()
        if query:
            chars = [e.char for e in emoji.search(query, limit=180)]
        elif self.group == "recent":
            chars = self.recents.items()
        else:
            chars = emoji.chars_in(self.group)
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
        self._bound[item] = char
        texture = self._queue_for(self.platform).get(char)
        picture.set_paintable(texture)
        picture.set_tooltip_text(emoji.name_of(char))
        if texture is None:
            # Never drawn on this thread: ask, and the picture arrives a frame or two later.
            if not self._asked:
                GLib.idle_add(self._flush_asked)
            self._asked.append((item.get_position(), char))

    def _unbind(self, _factory, item: Gtk.ListItem) -> None:
        self._bound.pop(item, None)

    # -- thumbnails, drawn on a worker ----------------------------------------

    def _queue_for(self, platform: emoji.Platform) -> Thumbs:
        queue = self._thumbs.get(platform.id)
        if queue is None:
            def draw(char: str, platform=platform):
                try:
                    image = emoji.sticker(platform, char, THUMB)
                except OSError:
                    return None
                return Gdk.MemoryTexture.new(
                    THUMB, THUMB, Gdk.MemoryFormat.R8G8B8A8,
                    GLib.Bytes.new(image.tobytes()), THUMB * 4)

            def deliver(chars: list[str], platform_id=platform.id) -> None:
                GLib.idle_add(self._arrived, platform_id, chars)

            queue = self._thumbs[platform.id] = Thumbs(draw, deliver)
        return queue

    def _flush_asked(self) -> bool:
        asked, self._asked = sorted(self._asked), []
        self._queue_for(self.platform).want(char for _pos, char in asked)
        return GLib.SOURCE_REMOVE

    def _arrived(self, platform_id: str, chars: list[str]) -> bool:
        """Drawn pictures are in: fill the cells that were waiting for them."""
        if platform_id == self.platform.id:
            queue = self._queue_for(self.platform)
            fresh = set(chars)
            for item, char in list(self._bound.items()):
                if char in fresh:
                    picture = item.get_child()
                    if picture is not None:
                        picture.set_paintable(queue.get(char))
        return GLib.SOURCE_REMOVE

    def prefetch(self) -> bool:
        """Draw the first screen of every group, and the recents, while nothing else is going on."""
        queue = self._queue_for(self.platform)
        wanted = list(self.recents.items())
        for group in GROUP_ICONS:
            wanted.extend(emoji.chars_in(group)[:PREFETCH])
        queue.prefetch(wanted)
        return GLib.SOURCE_REMOVE

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
