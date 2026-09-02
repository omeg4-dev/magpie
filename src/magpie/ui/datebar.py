"""Choosing which month you are looking at.

The screenshot folder goes back to 2022 and holds thousands of files. Scrolling
that is not browsing, and loading it is what made the browser fall over — so it
is navigated instead: a row of years, a row of months under the chosen one, and
only that month is ever read.

Each chip carries its count, because "how many did I take in June" is half the
question you are asking when you go looking.
"""

from __future__ import annotations

from gi.repository import Gtk

from ..months import by_year, label

__all__ = ["DateBar"]


class DateBar(Gtk.Box):
    """Two rows of chips: years, then the months of the chosen year."""

    def __init__(self, on_pick) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.add_css_class("datebar")
        self._on_pick = on_pick
        self._year: int | None = None
        self._grouped: list = []
        #: What is currently drawn, so a keystroke in the screenshot browser
        #: does not rebuild seventeen buttons that have not changed.
        self._drawn: tuple | None = None

        self._years = _strip()
        self._months = _strip()
        self.append(self._years)
        self.append(self._months)

    def show_months(self, months: list, chosen: tuple[int, int] | None) -> None:
        self._grouped = by_year(months)
        if not self._grouped:
            self.set_visible(False)
            return
        self.set_visible(True)
        self._year = chosen[0] if chosen else self._grouped[0][0]
        if self._year not in dict(self._grouped):
            self._year = self._grouped[0][0]
        state = (tuple((y, tuple(m.key + (m.count,) for m in ms))
                       for y, ms in self._grouped), self._year, chosen)
        if state == self._drawn:
            return
        self._drawn = state
        self._draw_years()
        self._draw_months(chosen)

    def _draw_years(self) -> None:
        _empty(self._years)
        for year, months in self._grouped:
            total = sum(m.count for m in months)
            chip = _chip(str(year), total, year == self._year)
            chip.connect("clicked", lambda _b, y=year: self._pick_year(y))
            self._years.append(chip)

    def _draw_months(self, chosen: tuple[int, int] | None) -> None:
        _empty(self._months)
        for month in dict(self._grouped)[self._year]:
            chip = _chip(label(month), month.count, month.key == chosen)
            chip.add_css_class("month")
            chip.connect("clicked", lambda _b, m=month.key: self._on_pick(m))
            self._months.append(chip)

    def _pick_year(self, year: int) -> None:
        """Picking a year lands on its first month — one click, not two."""
        self._year = year
        self._on_pick(dict(self._grouped)[year][0].key)


def _strip() -> Gtk.FlowBox:
    """A row of chips that wraps rather than pushing the window wider.

    A box would ask for the width of all twelve months at once, and a layer
    surface is whatever width it asks for — one glance at the screenshot
    browser and the whole window had grown.
    """
    row = Gtk.FlowBox(selection_mode=Gtk.SelectionMode.NONE)
    row.add_css_class("chips")
    row.set_max_children_per_line(12)
    row.set_column_spacing(6)
    row.set_row_spacing(4)
    return row


def _chip(text: str, count: int, on: bool) -> Gtk.Button:
    button = Gtk.Button()
    button.add_css_class("chip")
    if on:
        button.add_css_class("on")

    box = Gtk.Box(spacing=6)
    name = Gtk.Label(label=text)
    name.add_css_class("chip-name")
    tally = Gtk.Label(label=str(count))
    tally.add_css_class("chip-count")
    box.append(name)
    box.append(tally)
    button.set_child(box)
    return button


def _empty(box: Gtk.FlowBox) -> None:
    child = box.get_first_child()
    while child is not None:
        box.remove(child)
        child = box.get_first_child()
