"""Months, grouped for the date bar.

The screenshot folder goes back to 2022 and holds thousands of files, so it is
navigated rather than scrolled: pick a year, pick a month, and only that month
is ever loaded.
"""

from __future__ import annotations

from .store import Month

__all__ = ["by_year", "label", "MONTH_NAMES"]

MONTH_NAMES = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
               "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def by_year(months: list[Month]) -> list[tuple[int, list[Month]]]:
    """Group months under their year, newest year and month first."""
    years: dict[int, list[Month]] = {}
    for month in months:
        years.setdefault(month.year, []).append(month)
    return [(year, sorted(years[year], key=lambda m: m.month, reverse=True))
            for year in sorted(years, reverse=True)]


def label(month: Month) -> str:
    return MONTH_NAMES[month.month - 1]
