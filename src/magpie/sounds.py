"""Two small noises, and the rules about making them.

A clipboard that answers is a clipboard you trust: the sound is how you know
the copy landed without having to go and look at the thing you pasted into.

Three rules keep it from becoming annoying. It is **quiet** — see
`tools/make_sounds.py`, which generates both files. It is **short**, well under
the time it takes to move your hand back to the keyboard. And it is
**detached**: the player is spawned and never waited for, because a window that
stalls for eighty milliseconds so a speaker can catch up is worse than silence.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

__all__ = ["play", "file", "find_player", "PLAYERS", "SOUNDS"]

SOUNDS = ("open", "copy")

#: In order of preference. `pw-play` talks to PipeWire directly, which is what
#: this desktop runs; the rest are for machines that do not.
PLAYERS = ("pw-play", "paplay", "aplay")

ASSETS = Path(__file__).resolve().parent / "assets"


def file(name: str) -> Path:
    return ASSETS / f"{name}.wav"


def find_player() -> str | None:
    return next((p for p in PLAYERS if shutil.which(p)), None)


#: The players still running. Nothing waits for them, so something has to
#: notice when they are done — an unwaited child stays in the process table as
#: a zombie, and this program makes a noise every time you open a window.
_children: list[subprocess.Popen] = []


def _reap() -> None:
    for child in list(_children):
        if child.poll() is not None:
            _children.remove(child)


def _spawn(command: list[str]) -> None:
    _reap()
    _children.append(subprocess.Popen(
        command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))


def play(name: str, player: str | None = None, run=_spawn) -> None:
    """Make the noise, if this machine can. Never raises, never blocks.

    A missing player, a missing file or a broken sound server all mean the same
    thing here: no sound. None of them is a reason to interrupt what someone was
    doing with the clipboard.
    """
    if name not in SOUNDS:
        return
    if player is None:
        return
    path = file(name)
    if not path.exists():
        return
    try:
        run([player, str(path)])
    except OSError:
        pass
