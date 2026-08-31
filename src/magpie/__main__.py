import sys

from .preload import ensure_preloaded, wanted

# Before anything imports Gtk: gtk4-layer-shell has to beat libwayland-client
# into the process or its interposed symbols never take effect. Only for the
# window, though — LD_PRELOAD is inherited, and the reading job spawns
# thousands of children that would each load it for nothing.
if wanted(sys.argv[1:]):
    ensure_preloaded()

from .cli import main  # noqa: E402

sys.exit(main())
