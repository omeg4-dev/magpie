"""What the window is looking at.

Every decision the viewer makes that is not drawing lives here: which entries a
mode shows, what the filter box does to them, and where the selection goes when
the list changes underneath it. None of it needs a screen, so all of it is
tested — "the selection jumped when a copy arrived" is the kind of bug that is
miserable to reproduce by hand and trivial to catch here.

The three modes are the three buttons on the rail. Only four keys do anything
in the window — open, close, copy, and up/down through the list — so everything
else this class exposes is driven by something you can click.
"""

from __future__ import annotations

from .store import Entry, Month, Store

__all__ = ["Browse"]

#: What each mode asks the store for. `None` means "do not narrow on this".
MODE_FILTERS = {
    "clipboard": {"source": "clipboard", "kind": None},
    # The grid is the same history seen denser — text as well as pictures, so
    # you can take in far more of it at a glance. Not an image gallery: a grid
    # of only the images hides most of what you ever copied.
    "grid": {"source": "clipboard", "kind": None},
    "screenshots": {"source": "screenshot", "kind": None},
}

#: Modes that open on their newest month rather than on everything. The
#: screenshot folder is thousands of files and grows daily; the clipboard is
#: hundreds of one-line rows, and one you have to navigate by date is not a
#: clipboard.
BY_MONTH = ("screenshots",)


class Browse:
    MODES = ("clipboard", "grid", "screenshots")

    def __init__(self, store: Store, limit: int = 2000) -> None:
        self._store = store
        self._limit = limit
        self.mode = "clipboard"
        self.query = ""
        self.month: tuple[int, int] | None = None
        self._entries: list[Entry] = []
        self._at = 0
        self._undo: int | None = None
        self.reload(keep_selection=False)

    # -- what is on screen -------------------------------------------------

    def entries(self) -> list[Entry]:
        return self._entries

    @property
    def position(self) -> int | None:
        """Where the selection is in `entries()`, or None when there is none.

        The window needs this on every keypress to move the view, and looking
        it up by scanning the list is the difference between arrowing through a
        month of screenshots and watching it think.
        """
        if not self._entries:
            return None
        return min(self._at, len(self._entries) - 1)

    @property
    def selected(self) -> Entry | None:
        at = self.position
        return None if at is None else self._entries[at]

    def reload(self, keep_selection: bool = True) -> None:
        """Ask the store again, without losing the reader's place.

        A copy landing while you are reading something must not move what you
        are reading out from under you, so the selection follows the entry it
        was on rather than the row number it was at.
        """
        was = self.selected.id if keep_selection and self.selected else None
        self._entries = self._store.search(
            self.query, limit=self._limit, month=self.month,
            **MODE_FILTERS[self.mode])
        self._at = next((i for i, e in enumerate(self._entries) if e.id == was), 0)

    def months(self) -> list[Month]:
        """The months there are to choose from, in this mode. Newest first."""
        return self._store.months(source=MODE_FILTERS[self.mode]["source"])

    # -- the rail and the filter box ---------------------------------------

    def set_mode(self, mode: str) -> None:
        if mode not in MODE_FILTERS:
            raise ValueError(f"no such mode: {mode}")
        self.mode = mode
        months = self.months() if mode in BY_MONTH else []
        self.month = months[0].key if months else None
        self.reload(keep_selection=False)

    def set_month(self, month: tuple[int, int] | None) -> None:
        self.month = month
        self.reload(keep_selection=False)

    def set_query(self, query: str) -> None:
        self.query = query
        # Typing is a question about everything, so it leaves the chosen month
        # behind. Being silently answered out of one month of a folder is how
        # you conclude a screenshot no longer exists.
        if query.strip():
            self.month = None
        elif self.mode in BY_MONTH and self.month is None:
            months = self.months()
            self.month = months[0].key if months else None
        # Typing means looking for something, so the best match is where you
        # want to be — not wherever the selection happened to be left.
        self.reload(keep_selection=False)

    # -- moving through it -------------------------------------------------

    def move(self, by: int) -> None:
        """Up or down. Nothing wraps: a list that jumps to the far end when you
        overshoot is one you have to keep looking at to use."""
        if self._entries:
            self._at = max(0, min(len(self._entries) - 1, self._at + by))

    def select(self, entry_id: int) -> None:
        self._at = next((i for i, e in enumerate(self._entries) if e.id == entry_id),
                        self._at)

    # -- the buttons in the preview pane -----------------------------------

    def pin_selected(self) -> None:
        entry = self.selected
        if entry is None:
            return
        self._store.pin(entry.id, not entry.pinned)
        self.reload()

    def delete_selected(self) -> None:
        """Hide it and remember it, so the toast's Undo has something to do."""
        entry = self.selected
        if entry is None:
            return
        at = self._at
        self._store.delete(entry.id)
        self._undo = entry.id
        self.reload(keep_selection=False)
        self._at = max(0, min(at, len(self._entries) - 1))

    def undo(self) -> None:
        if self._undo is None:
            return
        self._store.restore(self._undo)
        restored, self._undo = self._undo, None
        self.reload(keep_selection=False)
        self.select(restored)
