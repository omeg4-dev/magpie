"""The command line.

Mostly plumbing for things that are not the viewer: the two wl-paste watchers
call `magpie store`, a systemd timer (or the viewer itself) calls `magpie sync`,
and the rest is there so the store can be looked at without a compositor.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .capture import capture
from .config import Config, load
from .importers import (import_cliphist, import_noctalia, import_screenshots,
                        read_cliphist)
from .store import Store

__all__ = ["main"]

USAGE = """\
magpie — the clipboard, remembered

  magpie view [--mode M]  open the window (Super+V); M is clipboard|grid|screenshots
  magpie store            take stdin as a clipboard entry (for wl-paste --watch)
  magpie sync             import Noctalia's history and index new screenshots
  magpie recover          one-off: recover the cliphist run that came before
  magpie recent [n]       what is at the top of the clipboard
  magpie search <query>   find clipboard entries by their words
  magpie shots [query]    the screenshot browser, which is not the clipboard
  magpie stats            what the store holds
  magpie purge            really drop what was deleted long ago

The watchers, which is how anything gets in here at all:

  wl-paste --type text  --watch magpie store
  wl-paste --type image --watch magpie store
"""


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    command = argv.pop(0) if argv else "help"
    if command in ("help", "-h", "--help"):
        print(USAGE, end="")
        return 0

    config = load()
    handler = COMMANDS.get(command)
    if handler is None:
        print(f"magpie: no such command: {command}\n\n{USAGE}", end="", file=sys.stderr)
        return 2
    return handler(config, argv)


def _store(config: Config) -> Store:
    return Store(config.store)


def cmd_view(config: Config, argv: list[str]) -> int:
    """Open the window, or bring up the one already running."""
    from .ui.app import run

    return run(["magpie"] + argv)


def cmd_store(config: Config, argv: list[str]) -> int:
    """Called once per clipboard change, with the content on stdin."""
    import os

    data = sys.stdin.buffer.read()
    entry = capture(_store(config), data, os.environ.get("CLIPBOARD_STATE", "data"))
    return 0 if entry is not None else 1


def cmd_sync(config: Config, argv: list[str]) -> int:
    store = _store(config)
    from_noctalia = import_noctalia(store)
    shots = import_screenshots(store, config.screenshots)
    missing = store.forget_missing_files()
    purged = store.purge(after_ms=config.purge_days * 86_400_000)
    print(f"{from_noctalia} from noctalia, {shots} screenshots, "
          f"{missing} gone from disk, {purged} purged")
    return 0


def cmd_recover(config: Config, argv: list[str]) -> int:
    """The one-off: 750 entries that predate Noctalia, and no clock in sight.

    Slow — it decodes every entry through cliphist — and worth running once.
    Running it again is harmless; it just finds nothing new.
    """
    store = _store(config)
    entries, first_ms, last_ms = read_cliphist()
    if not entries:
        print("no cliphist database to recover from")
        return 1
    added = import_cliphist(store, entries, first_ms=first_ms, last_ms=last_ms)
    print(f"{added} recovered from cliphist ({len(entries)} read)")
    return 0


def cmd_recent(config: Config, argv: list[str]) -> int:
    limit = int(argv[0]) if argv else 20
    for entry in _store(config).recent(limit, source="clipboard"):
        _line(entry)
    return 0


def cmd_search(config: Config, argv: list[str]) -> int:
    results = _store(config).search(" ".join(argv), source="clipboard")
    for entry in results:
        _line(entry)
    return 0 if results else 1


def cmd_shots(config: Config, argv: list[str]) -> int:
    """The screenshot browser. Deliberately a different list.

    The folder holds thousands of files and the clipboard holds what you
    actually copied; pouring one into the other would bury the other.
    """
    results = _store(config).search(" ".join(argv), source="screenshot")
    for entry in results[:200]:
        _line(entry)
    return 0 if results else 1


def cmd_stats(config: Config, argv: list[str]) -> int:
    store = _store(config)
    print(f"store       {config.store}")
    print(f"entries     {store.count()}")
    for source in ("clipboard", "screenshot"):
        print(f"  {source:<10}{store.count(source=source)}")
    for kind in ("text", "image", "files", "binary"):
        print(f"  {kind:<10}{len(store.recent(limit=10**9, kind=kind))}")
    blobs = list((Path(config.store) / 'blobs').rglob("*.bin"))
    print(f"payloads    {len(blobs)}, {sum(b.stat().st_size for b in blobs) >> 20} MiB")
    return 0


def cmd_purge(config: Config, argv: list[str]) -> int:
    print(f"{_store(config).purge(after_ms=config.purge_days * 86_400_000)} purged")
    return 0


def _line(entry) -> None:
    from datetime import datetime

    mark = "*" if entry.pinned else " "
    # A reconstructed time is shown with a ~, because it was worked out from
    # the entries around it rather than measured.
    when = datetime.fromtimestamp(entry.last_seen_ms / 1000).strftime("%d %b %H:%M")
    when = ("~" if entry.time_approx else " ") + when
    print(f"{entry.id:>7}{mark} {when} {entry.kind:<7} {entry.preview[:70]}")


COMMANDS = {
    "view": cmd_view,
    "store": cmd_store,
    "sync": cmd_sync,
    "recover": cmd_recover,
    "recent": cmd_recent,
    "search": cmd_search,
    "shots": cmd_shots,
    "stats": cmd_stats,
    "purge": cmd_purge,
}
