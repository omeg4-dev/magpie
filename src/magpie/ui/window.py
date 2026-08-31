"""The window: a rail, a list, and what you have selected.

It is a layer-shell surface rather than a floating toplevel, so it behaves like
a part of the desktop and not like an application someone launched: no border,
no titlebar, and it takes the keyboard the moment it appears.

Master/detail, because that is what a clipboard is for — you are looking for one
thing among many and you need to see enough of it to know it is the right one.

The filter box always has the caret. Typing goes into it whatever else you are
doing, including while you are arrowing through the list, because the two are
the same motion: you narrow, you look, you narrow again. Only a few keys are
taken — Escape closes, Enter copies and closes, the arrows move — and everything
else in here is a button, on purpose.

**Nothing is drawn that is not on screen.** The list and the grid are both
virtualised views over one model and one selection: switching between them
swaps a child, and neither builds a widget for the two thousandth row you never
scrolled to. Every expensive thing — decoding a picture, laying out a preview —
happens on the way past, once, and is remembered.

All the decisions about *what* is on screen live in `browse.Browse`, which has
no GTK in it and is tested. This file is the drawing.
"""

from __future__ import annotations

import subprocess
from datetime import datetime
from pathlib import Path

from gi.repository import Gdk, Gio, GLib, GObject, Gtk, Pango

from .. import sounds
from ..browse import Browse
from ..paste import to_clipboard
from ..shape import to_tile
from ..store import Entry
from ..update import plan
from .datebar import DateBar
from .popout import popout
from .thumbs import Thumbs

__all__ = ["Window"]

#: The rail. Nerd Font glyphs, because this desktop is full of them already.
MODE_ICONS = {
    "clipboard": ("\uf0ea", "Clipboard"),       # nf-fa-clipboard
    "grid": ("\uf009", "Grid"),                 # nf-fa-th_large
    "screenshots": ("\uf030", "Screenshots"),   # nf-fa-camera
}
CLOSE_ICON = "\uf00d"   # nf-fa-times
PIN_ICON = "\uf08d"     # nf-fa-thumb_tack

#: The little picture on a list row, cropped to exactly this so every row in
#: the column is the same shape.
STAMP_W, STAMP_H = 48, 34

#: A grid tile. Text tiles are the same box as picture tiles, so the grid stays
#: a grid whatever you happened to copy.
TILE_W, TILE_H = 150, 104

#: What fits in a text tile, measured rather than guessed: FiraCode Nerd Font
#: Mono at 10.5px is 6px per character and 14px per line, and the card has
#: 26px of padding across and 22px down. Cut to this before GTK sees it — an
#: overlaid label draws at its natural height and would otherwise run off the
#: bottom of the card and over the tiles below.
TILE_LINES, TILE_CHARS = 5, 20

LIST_WIDTH = 372
#: Wide enough for four tiles across: the grid earns its place by showing more
#: of the history at once than the list does — and still leaves the preview
#: enough room to be worth reading.
GRID_WIDTH = 680

#: The whole window. Smaller than it was: it is a thing you glance at and
#: dismiss, and one that covers the window you are pasting into is in the way.
WIDTH, HEIGHT = 1040, 690

#: The opening. A hundred milliseconds of fade and eight pixels of rise —
#: enough that the window arrives rather than blinks, short enough that it is
#: over before you could have read anything in it.
APPEAR_MS = 105
RISE = 8

#: How long the filter box waits before it asks. Typing six characters used to
#: mean six searches and six rebuilds; at this delay a normal burst of typing
#: costs one, and a single character still feels like it answered immediately.
FILTER_DELAY_MS = 40

#: How long the preview waits before it draws. Holding Down through a month of
#: screenshots would otherwise decode every one you passed; at this delay you
#: only ever decode the one you stopped on, and stopping still feels immediate.
PREVIEW_DELAY_MS = 45


class Window(Gtk.Window):
    def __init__(self, app, store, **kwargs):
        super().__init__(application=app, title="Magpie", **kwargs)
        self.add_css_class("magpie")
        self.set_default_size(WIDTH, HEIGHT)

        self.store = store
        self.browse = Browse(store)
        self.thumbs = Thumbs(store)
        self._toast_timeout = 0
        self._preview_timeout = 0
        self._filter_timeout = 0
        self._syncing = False
        self._quiet = False
        self._pending: Entry | None = None
        self._totals: dict[str, int] = {}
        #: The ids the views are currently holding, so a refresh can work out
        #: how little it has to change.
        self._shown: list[int] = []
        self._anim = 0
        # Looked up once. `shutil.which` on the way through a copy is a
        # filesystem walk nobody asked for.
        self._player = sounds.find_player()

        self.body = self._build()
        self.set_child(self.body)
        self._keys()
        self.refresh(reselect=False)

    # -- putting it together -----------------------------------------------

    def _build(self) -> Gtk.Widget:
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        row.append(self._build_rail())
        row.append(self._build_left())
        row.append(self._build_preview())
        return row

    def _build_rail(self) -> Gtk.Widget:
        rail = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        rail.add_css_class("rail")

        self._mode_buttons = {}
        for mode in Browse.MODES:
            glyph, tip = MODE_ICONS[mode]
            button = Gtk.Button(label=glyph)
            button.set_tooltip_text(tip)
            button.set_can_focus(False)  # the caret stays in the filter box
            button.connect("clicked", lambda _b, m=mode: self.set_mode(m))
            rail.append(button)
            self._mode_buttons[mode] = button
        self._mode_buttons["clipboard"].add_css_class("on")

        rail.append(Gtk.Box(vexpand=True))
        close = Gtk.Button(label=CLOSE_ICON)
        close.set_tooltip_text("Close")
        close.set_can_focus(False)
        close.connect("clicked", lambda _b: self.close())
        rail.append(close)
        return rail

    def _build_left(self) -> Gtk.Widget:
        column = self.left = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        column.set_size_request(LIST_WIDTH, -1)

        self.filter = Gtk.Entry(placeholder_text="Type to search")
        self.filter.add_css_class("filter")
        self.filter.connect("changed", self._on_filter)
        column.append(self.filter)

        self.datebar = DateBar(self._on_month)
        self.datebar.set_visible(False)
        column.append(self.datebar)

        self.count = Gtk.Label(xalign=0)
        self.count.add_css_class("count")
        column.append(self.count)

        column.append(self._build_views())

        self.toast = self._build_toast()
        column.append(self.toast)
        return column

    def _build_views(self) -> Gtk.Widget:
        """One model, one selection, two ways of looking at it.

        Both views are virtual — GTK builds a widget per visible row and rebinds
        it as you scroll — and both read the same selection, so switching
        between them is a swapped child rather than a rebuild.
        """
        self.items = Gio.ListStore.new(EntryItem)
        self.selection = Gtk.SingleSelection(model=self.items)
        self.selection.set_autoselect(False)
        self.selection.set_can_unselect(True)
        self.selection.connect("selection-changed", self._on_selected)

        self.list = Gtk.ListView(model=self.selection,
                                 factory=self._factory(Row))
        self.list.add_css_class("list")
        self.list.connect("activate", lambda *_: self.copy_and_close())

        self.grid = Gtk.GridView(model=self.selection,
                                 factory=self._factory(Tile))
        self.grid.add_css_class("gallery")
        self.grid.set_min_columns(2)
        self.grid.set_max_columns(8)
        self.grid.connect("activate", lambda *_: self.copy_and_close())

        self.scroller = Gtk.ScrolledWindow(vexpand=True)
        self.scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.scroller.set_child(self.list)
        return self.scroller

    def _factory(self, make) -> Gtk.ListItemFactory:
        factory = Gtk.SignalListItemFactory()
        factory.connect("setup", lambda _f, item: item.set_child(make()))
        factory.connect("bind", self._bind)
        return factory

    def _bind(self, _factory, item: Gtk.ListItem) -> None:
        item.get_child().show_entry(item.get_item().entry, self.thumbs)

    def _build_toast(self) -> Gtk.Widget:
        toast = Gtk.Box(spacing=6)
        toast.add_css_class("toast")
        self.toast_label = Gtk.Label(label="Deleted", xalign=0, hexpand=True)
        undo = Gtk.Button(label="Undo")
        undo.set_can_focus(False)
        undo.connect("clicked", lambda _b: self._undo())
        toast.append(self.toast_label)
        toast.append(undo)
        toast.set_visible(False)
        return toast

    def _build_preview(self) -> Gtk.Widget:
        pane = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        pane.add_css_class("preview")

        self.preview_slot = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, vexpand=True)
        pane.append(self.preview_slot)

        self.facts = Gtk.Label(xalign=0)
        self.facts.add_css_class("facts")
        # END, not MIDDLE: a middle ellipsis ate the mime type and the size,
        # which are the short facts worth reading. The long one is the path.
        self.facts.set_ellipsize(Pango.EllipsizeMode.END)
        # An ellipsised label still asks for the width of its whole string, and
        # a screenshot's path is a long string: without this the window grows
        # to fit the file name of whatever you happen to have selected.
        self.facts.set_max_width_chars(1)
        pane.append(self.facts)

        pane.append(self._build_actions())
        return pane

    def _build_actions(self) -> Gtk.Widget:
        # A flow, not a row. Six buttons in a line ask for four hundred and
        # fifty pixels, and a layer surface is as wide as it asks for — the
        # window grew every time a screenshot was selected. This wraps instead.
        bar = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE)
        bar.add_css_class("actions")
        bar.set_max_children_per_line(6)
        bar.set_column_spacing(8)
        bar.set_row_spacing(8)

        self.copy_button = _button("Copy", self.copy_and_close, "primary")
        self.pin_button = _button("Pin", self._pin)
        self.popout_button = _button("Pop out", self._popout)
        self.open_button = _button("Open", self._open)
        self.reveal_button = _button("Show in files", self._reveal)
        delete = _button("Delete", self._delete, "danger")

        for widget in (self.copy_button, self.pin_button, self.popout_button,
                       self.open_button, self.reveal_button, delete):
            bar.append(widget)
        return bar

    # -- opening ------------------------------------------------------------

    def open_at(self, mode: str) -> None:
        """Super+V. One query, one draw, then it is on screen.

        Everything here is counted, because this is the path a keypress takes.
        The window already exists; what it must not do is ask the store the
        same question three times on the way to showing it.
        """
        self._quiet = True
        self.filter.set_text("")
        self._quiet = False

        if mode != self.browse.mode:
            self._apply_mode(mode)
        elif self.browse.query:
            self.browse.set_query("")
        else:
            # Nothing about the view changed, but something has almost
            # certainly been copied since it was last looked at.
            self.browse.reload(keep_selection=False)

        self._totals.clear()
        self.refresh(reselect=False)
        self.present()
        # Straight into typing: the box has the caret before you have let go
        # of the shortcut.
        self.filter.grab_focus()
        self.appear()
        sounds.play("open", self._player)

    def appear(self) -> None:
        """Fade and rise, once, from a clock rather than a frame count."""
        if self._anim:
            self.remove_tick_callback(self._anim)
        self._appeared_at = GLib.get_monotonic_time()
        self.set_opacity(0.0)
        self.body.set_margin_top(RISE)
        self._anim = self.add_tick_callback(self._appearing)

    def _appearing(self, _widget, _clock) -> bool:
        along = (GLib.get_monotonic_time() - self._appeared_at) / (APPEAR_MS * 1000)
        if along >= 1.0:
            self.set_opacity(1.0)
            self.body.set_margin_top(0)
            self._anim = 0
            return GLib.SOURCE_REMOVE
        # Ease out: most of the movement happens in the first few frames, so
        # it reads as arriving rather than as sliding.
        eased = 1 - (1 - along) ** 3
        self.set_opacity(eased)
        self.body.set_margin_top(round(RISE * (1 - eased)))
        return GLib.SOURCE_CONTINUE

    # -- the keys -----------------------------------------------------------

    def _keys(self) -> None:
        keys = Gtk.EventControllerKey()
        # Capture, so the arrows move the list even though the caret lives in
        # the filter box. Typing and choosing are one motion here.
        keys.set_propagation_phase(Gtk.PropagationPhase.CAPTURE)
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)

    def _on_key(self, _controller, keyval, _code, _state) -> bool:
        step = self.grid_step() if self._pictures else 1
        if keyval == Gdk.KEY_Escape:
            self.close()
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self.copy_and_close()
        elif keyval == Gdk.KEY_Up:
            self._move(-step)
        elif keyval == Gdk.KEY_Down:
            self._move(step)
        elif keyval == Gdk.KEY_Page_Up:
            self._move(-10 * step)
        elif keyval == Gdk.KEY_Page_Down:
            self._move(10 * step)
        elif self._pictures and keyval == Gdk.KEY_Left:
            self._move(-1)
        elif self._pictures and keyval == Gdk.KEY_Right:
            self._move(1)
        else:
            return False
        return True

    def grid_step(self) -> int:
        """How many tiles fit across, so Up and Down move by a whole row."""
        width = self.left.get_width() or GRID_WIDTH
        return max(1, min(8, width // (TILE_W + 10)))

    def _move(self, by: int) -> None:
        self.browse.move(by)
        self._sync_selection()

    # -- what is on screen --------------------------------------------------

    @property
    def _pictures(self) -> bool:
        """Whether the left side is the grid rather than the list."""
        return self.browse.mode != "clipboard"

    @property
    def _view(self) -> Gtk.Widget:
        return self.grid if self._pictures else self.list

    def set_mode(self, mode: str) -> None:
        self._apply_mode(mode)
        self.refresh(reselect=False)
        self.filter.grab_focus()

    def _apply_mode(self, mode: str) -> None:
        self.browse.set_mode(mode)
        for name, button in self._mode_buttons.items():
            button.set_css_classes(["on"] if name == mode else [])
        self.scroller.set_child(self._view)
        self.left.set_size_request(GRID_WIDTH if self._pictures else LIST_WIDTH, -1)

    def _on_filter(self, _entry: Gtk.Entry) -> None:
        if self._quiet:
            return
        if self._filter_timeout:
            return
        self._filter_timeout = GLib.timeout_add(FILTER_DELAY_MS, self._search)

    def _search(self) -> bool:
        self._filter_timeout = 0
        self.browse.set_query(self.filter.get_text())
        self.refresh(reselect=False)
        return GLib.SOURCE_REMOVE

    def _on_month(self, month) -> None:
        self.browse.set_month(month)
        self.refresh(reselect=False)
        self.filter.grab_focus_without_selecting()

    def refresh(self, reselect: bool = True) -> None:
        if reselect:
            self.browse.reload()
        entries = self.browse.entries()

        # The date bar is only for the folder: a clipboard you have to
        # navigate by date is not a clipboard.
        if self.browse.mode == "screenshots":
            self.datebar.show_months(self.browse.months(), self.browse.month)
        else:
            self.datebar.set_visible(False)

        self._syncing = True
        try:
            self._apply(entries)
        finally:
            self._syncing = False
        self._say_how_many(entries)
        self._sync_selection()

    def _apply(self, entries: list[Entry]) -> None:
        """Put these entries in the model, changing as little as possible.

        No decoding and no widgets here either: the model holds entries, and a
        row is only built once it scrolls into view.
        """
        ids = [e.id for e in entries]
        what, at, count = plan(self._shown, ids)
        if what == "insert":
            self.items.splice(at, 0, [EntryItem(e) for e in entries[at:at + count]])
        elif what == "remove":
            self.items.splice(at, count, [])
        elif what == "replace":
            self._replace(entries)
            # These are different entries, so where you had scrolled to in the
            # old ones means nothing. Start at the top, where the newest is.
            self.scroller.get_vadjustment().set_value(0)
        elif self._changed(entries):
            # The same entries in the same order, but one of them is not what
            # it was — pinning changes a row without moving it. Handing the
            # model a new object for the changed row is not enough on its own;
            # the view keeps showing what it bound. So the contents are
            # replaced, and the reader is put back where they were looking.
            where = self.scroller.get_vadjustment().get_value()
            self._replace(entries)
            self.scroller.get_vadjustment().set_value(where)
        self._shown = ids

    def _replace(self, entries: list[Entry]) -> None:
        self.items.splice(0, self.items.get_n_items(),
                          [EntryItem(e) for e in entries])

    def _changed(self, entries: list[Entry]) -> bool:
        """Whether any of these is different from the one the model holds."""
        return any(item is None or item.entry != entry
                   for item, entry in ((self.items.get_item(at), e)
                                       for at, e in enumerate(entries)))

    def _say_how_many(self, entries: list[Entry]) -> None:
        source = "screenshot" if self.browse.mode == "screenshots" else "clipboard"
        # Counted once per opening rather than once per keystroke.
        if source not in self._totals:
            self._totals[source] = self.store.count(source=source)
        total = self._totals[source]
        if self.browse.query:
            self.count.set_text(f"{len(entries)} of {total}")
        elif self.browse.month:
            year, month = self.browse.month
            self.count.set_text(
                f"{len(entries)} in {month:02d}/{year}   ·   {total} in all")
        else:
            self.count.set_text(f"{total}")

    # -- the selection ------------------------------------------------------

    def _sync_selection(self) -> None:
        at = self.browse.position
        if at is None:
            self._show_preview(_empty_state(self.browse))
            self.facts.set_text("")
            self._enable_actions(None)
            return

        self._syncing = True
        try:
            if self.selection.get_selected() != at:
                self.selection.set_selected(at)
            # NONE, not FOCUS: the caret must stay in the filter box, so the
            # view is scrolled without being given the keyboard.
            self._view.scroll_to(at, Gtk.ListScrollFlags.NONE, None)
        finally:
            self._syncing = False
        self._show_entry(self.browse.selected)

    def _on_selected(self, selection, _at, _count) -> None:
        if self._syncing:
            return
        item = selection.get_selected_item()
        if item is not None and item.entry.id != _id_of(self.browse.selected):
            self.browse.select(item.entry.id)
            self._show_entry(item.entry)
        # A click must never take the caret out of the filter box: typing has
        # to keep working straight after you have pointed at something.
        self.filter.grab_focus_without_selecting()

    # -- the preview --------------------------------------------------------

    def _show_entry(self, entry: Entry) -> None:
        # The cheap half is immediate; only the picture waits.
        self.facts.set_text(_facts(entry))
        self._enable_actions(entry)
        self.pin_button.set_label("Unpin" if entry.pinned else "Pin")
        self._preview_soon(entry)

    def _preview_soon(self, entry: Entry) -> None:
        """Draw the preview when the selection stops moving.

        Held arrow keys walk past dozens of entries a second, and building a
        preview for each one you passed is most of what made this feel slow.
        """
        self._pending = entry
        if self._preview_timeout:
            return
        self._preview_timeout = GLib.timeout_add(PREVIEW_DELAY_MS, self._draw_preview)

    def _draw_preview(self) -> bool:
        self._preview_timeout = 0
        entry = self._pending
        if entry is not None:
            self._show_preview(self._preview_widget(entry))
        return GLib.SOURCE_REMOVE

    def _preview_widget(self, entry: Entry) -> Gtk.Widget:
        if entry.is_image:
            texture = self.thumbs.preview(entry)
            if texture is not None:
                picture = Gtk.Picture.new_for_paintable(texture)
                picture.add_css_class("preview-image")
                picture.set_can_shrink(True)
                picture.set_content_fit(Gtk.ContentFit.CONTAIN)
                # In a scroller, which reports a small natural width however
                # big the picture is. Without it a wide screenshot makes the
                # whole window wider than it is supposed to be, because a
                # layer surface is whatever size it asks for.
                return _loose(picture)
            return _message("This image cannot be shown", "The file may have moved.")

        view = Gtk.TextView(editable=False, cursor_visible=False)
        view.add_css_class("preview-text")
        view.set_wrap_mode(Gtk.WrapMode.WORD_CHAR)
        view.set_can_focus(False)
        view.get_buffer().set_text(entry.text or entry.preview)
        return _loose(view)

    def _show_preview(self, widget: Gtk.Widget) -> None:
        child = self.preview_slot.get_first_child()
        while child is not None:
            self.preview_slot.remove(child)
            child = self.preview_slot.get_first_child()
        self.preview_slot.append(widget)

    def _enable_actions(self, entry: Entry | None) -> None:
        has = entry is not None
        self.copy_button.set_sensitive(has)
        self.pin_button.set_sensitive(has)
        # Pop out is for looking at a picture properly; there is nothing in a
        # line of text the preview is not already showing.
        self.popout_button.set_visible(has and entry.is_image)
        on_disk = has and entry.path is not None
        self.open_button.set_visible(on_disk)
        self.reveal_button.set_visible(on_disk)

    # -- the buttons --------------------------------------------------------

    def copy_and_close(self) -> None:
        entry = self.browse.selected
        if entry is not None and to_clipboard(self.store, entry):
            sounds.play("copy", self._player)
            self.close()

    def _pin(self) -> None:
        self.browse.pin_selected()
        self.refresh(reselect=False)
        self.filter.grab_focus_without_selecting()

    def _delete(self) -> None:
        if self.browse.selected is None:
            return
        self.browse.delete_selected()
        self._totals.clear()
        self.refresh(reselect=False)
        self._show_toast("Deleted")
        self.filter.grab_focus_without_selecting()

    def _undo(self) -> None:
        self.browse.undo()
        self._totals.clear()
        self.refresh(reselect=False)
        self._hide_toast()
        self.filter.grab_focus_without_selecting()

    def _popout(self) -> None:
        entry = self.browse.selected
        if entry is None:
            return
        texture = self.thumbs.full(entry)
        if texture is not None:
            popout(entry, texture, self)
            # And get out of the way. The list surface holds the keyboard
            # exclusively, so while it is up the picture cannot even be closed
            # with Escape — and looking at the picture is the whole point.
            self.close()

    def _open(self) -> None:
        entry = self.browse.selected
        if entry is not None and entry.path:
            subprocess.Popen(["xdg-open", entry.path])

    def _reveal(self) -> None:
        entry = self.browse.selected
        if entry is not None and entry.path:
            subprocess.Popen(["xdg-open", str(Path(entry.path).parent)])

    # -- the toast ----------------------------------------------------------

    def _show_toast(self, text: str) -> None:
        self.toast_label.set_text(text)
        self.toast.set_visible(True)
        if self._toast_timeout:
            GLib.source_remove(self._toast_timeout)
        self._toast_timeout = GLib.timeout_add_seconds(6, self._hide_toast)

    def _hide_toast(self) -> bool:
        self.toast.set_visible(False)
        self._toast_timeout = 0
        return GLib.SOURCE_REMOVE


# -- what the views hold ------------------------------------------------------


class EntryItem(GObject.Object):
    """One entry, wrapped so a Gio.ListStore will hold it."""

    __gtype_name__ = "MagpieEntryItem"

    def __init__(self, entry: Entry) -> None:
        super().__init__()
        self.entry = entry


class Card(Gtk.Box):
    """What the list and the grid have in common: a picture that can wait.

    Binding is on the path to the next frame, so nothing here decodes an image
    while the view is trying to draw. A card asks for what has already been
    decoded, shows that, and asks for the rest once the window is idle — which
    is the difference between the screenshot browser appearing and the
    screenshot browser appearing in a second and a half.
    """

    def __init__(self, orientation) -> None:
        super().__init__(orientation=orientation)
        self._generation = 0

    def _picture(self, entry: Entry, thumbs: Thumbs, size, apply) -> None:
        # Every bind invalidates the last one: a card is recycled as you
        # scroll, and a picture that arrives late must not land on whatever
        # entry the card is showing by then.
        self._generation += 1
        if not entry.is_image:
            apply(None)
            return
        width, height = size
        ready = thumbs.cached(entry, width, height)
        apply(ready)
        if ready is not None:
            return
        generation = self._generation

        def later() -> bool:
            if generation == self._generation:
                apply(thumbs.stamp(entry, width, height))
            return GLib.SOURCE_REMOVE

        GLib.idle_add(later, priority=GLib.PRIORITY_LOW)


class Row(Card):
    """A line in the list. Built once and refilled as the list scrolls.

    Kept deliberately thin. A list view holds a couple of hundred of these
    ready around wherever you are looking, so every widget in here is paid for
    two hundred times on every rebuild — which is why the picture and the pin
    are only built for the rows that actually have one, and why the whole
    second line is a single label rather than a box of three.
    """

    __gtype_name__ = "MagpieRow"

    def __init__(self) -> None:
        super().__init__(Gtk.Orientation.HORIZONTAL)
        self.add_css_class("row-body")
        self.stamp: Gtk.Picture | None = None

        body = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.text = Gtk.Label(xalign=0)
        self.text.add_css_class("row-text")
        self.text.set_ellipsize(Pango.EllipsizeMode.END)
        self.text.set_single_line_mode(True)
        self.text.set_max_width_chars(1)
        body.append(self.text)

        self.meta = Gtk.Label(xalign=0)
        self.meta.add_css_class("row-meta")
        self.meta.set_ellipsize(Pango.EllipsizeMode.END)
        self.meta.set_max_width_chars(1)
        body.append(self.meta)

        self.append(body)

    def show_entry(self, entry: Entry, thumbs: Thumbs) -> None:
        # An image row shows the image. "PNG image · 75.4 kB" is the size of
        # something you still cannot see, which is no help at all in choosing.
        self._picture(entry, thumbs, (STAMP_W, STAMP_H), self._show_stamp)

        self.text.set_text(entry.preview)
        self.meta.set_text(_meta(entry))
        _approximate(self.meta, entry.time_approx)

    def _show_stamp(self, texture) -> None:
        if texture is None and self.stamp is None:
            return  # a text row: never build the picture at all
        if self.stamp is None:
            self.stamp = Gtk.Picture()
            self.stamp.add_css_class("stamp")
            self.stamp.set_size_request(STAMP_W, STAMP_H)
            self.stamp.set_valign(Gtk.Align.CENTER)
            self.prepend(self.stamp)
        self.stamp.set_paintable(texture)
        self.stamp.set_visible(texture is not None)


class Tile(Card):
    """A card in the grid: the picture, or the words when there is no picture.

    Text gets a card of its own rather than being left out, because the grid is
    for taking in more of the history at once — and most of a clipboard is
    text. Both are the same box, so the grid stays a grid.

    Built empty and refilled as the grid scrolls; a GridView keeps only as many
    of these as fit on screen.
    """

    __gtype_name__ = "MagpieTile"

    def __init__(self) -> None:
        super().__init__(Gtk.Orientation.VERTICAL)
        self.add_css_class("tile-box")

        self.card = Gtk.Overlay()
        self.card.add_css_class("tile")
        self.card.set_size_request(TILE_W, TILE_H)
        # An overlay lets its children draw outside it, and a long copy is a
        # lot of lines: without this the text runs off the card and over the
        # ones below it.
        self.card.set_overflow(Gtk.Overflow.HIDDEN)

        self.picture = Gtk.Picture()
        self.picture.set_content_fit(Gtk.ContentFit.COVER)
        self.card.set_child(self.picture)

        self.words = Gtk.Label(xalign=0, yalign=0)
        self.words.add_css_class("tile-text")
        # No wrapping: `to_tile` has already decided both how many lines there
        # are and how long each one is. Letting the label wrap as well turned
        # seven lines into twelve and ran them off the bottom of the card.
        self.words.set_wrap(False)
        self.words.set_ellipsize(Pango.EllipsizeMode.END)
        self.words.set_valign(Gtk.Align.START)
        self.words.set_size_request(TILE_W, TILE_H)
        self.card.add_overlay(self.words)

        self.caption = Gtk.Label(xalign=0.5)
        self.caption.add_css_class("tile-label")
        self.caption.set_ellipsize(Pango.EllipsizeMode.END)
        self.caption.set_max_width_chars(1)

        self.append(self.card)
        self.append(self.caption)

    def show_entry(self, entry: Entry, thumbs: Thumbs) -> None:
        self._words = None if entry.is_image else to_tile(
            (entry.text if entry.kind == "text" else entry.preview)
            or entry.preview, TILE_LINES, TILE_CHARS)
        self._picture(entry, thumbs, (TILE_W, TILE_H), self._show_picture)
        self.caption.set_text(_when(entry))
        _approximate(self.caption, entry.time_approx)

    def _show_picture(self, texture) -> None:
        self.picture.set_paintable(texture)
        self.picture.set_visible(texture is not None)
        # A picture on its way still holds its card: showing the raw preview
        # text under it for a moment and then replacing it is a flicker.
        self.words.set_visible(self._words is not None)
        self.words.set_text(self._words or "")


# -- the empty screen -------------------------------------------------------


def _empty_state(browse: Browse) -> Gtk.Widget:
    if browse.query:
        return _message("Nothing matches that",
                        "Try fewer words, or another mode on the left.")
    if browse.mode == "screenshots":
        return _message("No screenshots in this month",
                        "Pick another month above, or run: magpie sync")
    return _message("Nothing here yet", "Copy something and it will appear.")


def _loose(widget: Gtk.Widget) -> Gtk.Widget:
    """Let this be as big as it likes without the window growing to suit it."""
    scroller = Gtk.ScrolledWindow(vexpand=True)
    scroller.set_child(widget)
    return scroller


def _message(title: str, hint: str) -> Gtk.Widget:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6,
                  vexpand=True, valign=Gtk.Align.CENTER, halign=Gtk.Align.CENTER)
    heading = Gtk.Label(label=title)
    heading.add_css_class("empty")
    detail = Gtk.Label(label=hint)
    detail.add_css_class("empty-hint")
    box.append(heading)
    box.append(detail)
    return box


# -- words ------------------------------------------------------------------


def _meta(entry: Entry) -> str:
    """The second line of a row: when, how often, and whether it is kept."""
    bits = [_when(entry)]
    if entry.times_seen > 1:
        bits.append(f"\u00d7{entry.times_seen}")
    if entry.pinned:
        bits.append(PIN_ICON)
    return "   ".join(bits)


def _approximate(label: Gtk.Label, approx: bool) -> None:
    """Say, quietly, that this time was worked out rather than recorded."""
    if approx:
        label.add_css_class("approx")
        label.set_tooltip_text(
            "Worked out from the entries around it — cliphist kept no clock")
    else:
        label.remove_css_class("approx")
        label.set_tooltip_text(None)


def _when(entry: Entry) -> str:
    when = datetime.fromtimestamp(entry.last_seen_ms / 1000)
    now = datetime.now()
    delta = (now - when).total_seconds()
    if delta < 60:
        text = "JUST NOW"
    elif delta < 3600:
        text = f"{int(delta // 60)} MIN AGO"
    elif when.date() == now.date():
        text = when.strftime("%H:%M")
    elif delta < 6 * 86400:
        text = when.strftime("%a %H:%M").upper()
    else:
        text = when.strftime("%d %b %Y").upper()
    return ("~" + text) if entry.time_approx else text


def _facts(entry: Entry) -> str:
    when = datetime.fromtimestamp(entry.first_seen_ms / 1000)
    bits = [when.strftime("%d %B %Y, %H:%M"), entry.mime, _size(entry.bytes)]
    if entry.time_approx:
        bits[0] += " (reconstructed)"
    if entry.times_seen > 1:
        bits.append(f"copied {entry.times_seen} times")
    if entry.path:
        bits.append(entry.path)
    return "   ·   ".join(bits)


def _size(size: int) -> str:
    for unit in ("B", "kB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size} B"


def _button(label: str, on_click, *classes: str) -> Gtk.Button:
    button = Gtk.Button(label=label)
    for name in classes:
        button.add_css_class(name)
    button.set_can_focus(False)
    button.connect("clicked", lambda _b: on_click())
    return button


def _id_of(entry: Entry | None) -> int | None:
    return entry.id if entry is not None else None
