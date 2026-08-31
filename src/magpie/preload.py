"""Get gtk4-layer-shell ahead of libwayland-client in the link order.

The library has to be loaded before libwayland-client or its interposed
symbols never take effect, and a Python process has already loaded plenty by
the time it imports Gtk. The upstream answer is LD_PRELOAD, so the daemon
re-executes itself once with it set.

Kept apart from `app` because it must run before anything imports Gtk.
"""

from __future__ import annotations

import os
import sys

__all__ = ["ensure_preloaded", "find_library", "preload_env"]

#: The library itself, first. gtk4-layer-shell also ships a
#: liblayer-shell-preload.so, but preloading that one alone still leaves the
#: surface uninitialised here — verified on this machine — so it is only a
#: fallback.
CANDIDATES = (
    "/usr/lib/libgtk4-layer-shell.so",
    "/usr/lib64/libgtk4-layer-shell.so",
    "/usr/lib/liblayer-shell-preload.so",
    "/usr/lib64/liblayer-shell-preload.so",
)

#: Set on the re-executed process so a library that fails to help cannot send
#: us round the loop for ever.
MARKER = "MAGPIE_PRELOADED"


def find_library(candidates: tuple[str, ...] = CANDIDATES) -> str | None:
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def preload_env(env: dict[str, str], library: str | None) -> dict[str, str] | None:
    """The environment to re-exec with, or None if no re-exec is needed."""
    if env.get(MARKER):
        return None
    if library is None:
        return None
    current = env.get("LD_PRELOAD", "")
    if library in current.split(":"):
        return None
    updated = dict(env)
    updated["LD_PRELOAD"] = f"{library}:{current}" if current else library
    updated[MARKER] = "1"
    return updated


def ensure_preloaded() -> None:
    """Re-exec this process with LD_PRELOAD set, if that is needed and possible."""
    env = preload_env(dict(os.environ), find_library())
    if env is None:
        return
    try:
        os.execve(sys.executable, [sys.executable, "-m", "magpie", *sys.argv[1:]], env)
    except OSError:
        # Better a floating window than no window; GTK will warn and carry on.
        return
