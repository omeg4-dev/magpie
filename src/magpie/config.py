"""Where magpie keeps things, and for how long.

A missing or broken config file is never fatal: this is the clipboard, and a
viewer that refuses to open because of a typo in a TOML file is worse than one
that opens on the defaults.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

__all__ = ["Config", "load", "CONFIG_PATH"]

#: MAGPIE_CONFIG points the whole program at a different config, and so at a
#: different store. Without it there is no way to run magpie against
#: anything but the real clipboard -- which makes it impossible to
#: demonstrate, screenshot or try out without putting real clipboard history
#: on screen.
CONFIG_PATH = Path(os.environ.get(
    "MAGPIE_CONFIG", Path.home() / ".config/magpie/config.toml"))


@dataclass(frozen=True)
class Config:
    #: The store. On /mnt/xv rather than under $HOME because it holds every
    #: image ever copied and $HOME is on the btrfs root that snapper snapshots.
    store: Path = Path("/mnt/xv/magpie")

    #: The screenshot folder, indexed in place and never written to.
    screenshots: Path = Path("/mnt/xv/Random/Screenshots")

    #: How long a deleted entry stays recoverable.
    purge_days: int = 30


def load(path: Path | str = CONFIG_PATH) -> Config:
    try:
        data = tomllib.loads(Path(path).read_text())
    except (OSError, ValueError):
        return Config()

    known = {field.name: field.type for field in fields(Config)}
    settings = {}
    for key, value in data.items():
        if key not in known:
            continue  # a stale key is not worth failing over
        settings[key] = Path(value).expanduser() if known[key] == "Path" else value
    return replace(Config(), **settings)
