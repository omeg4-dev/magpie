import sys

from .preload import ensure_preloaded

# Before anything imports Gtk: gtk4-layer-shell has to beat libwayland-client
# into the process or its interposed symbols never take effect.
ensure_preloaded()

from .cli import main  # noqa: E402

sys.exit(main())
