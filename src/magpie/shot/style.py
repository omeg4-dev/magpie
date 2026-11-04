"""How the screenshot tool looks — the same palette as the clipboard.

Kept apart from `ui/style.py` on purpose: that file belongs to the clipboard
window, this one to two other surfaces (the region overlay and the editor),
and a change to either should not be able to restyle the other. They share only
the palette, which is read from the same Noctalia file and followed live.
"""

from __future__ import annotations

from gi.repository import Gdk, Gio, Gtk

from ..palette import WHERE, Palette, mix, read
from ..ui.style import MONO, SANS
from .model import PALETTE

__all__ = ["apply", "watch", "css", "OPENING"]

#: The class that plays the opening animation, and how long each part takes (ms).
OPENING = "opening"
DIM_MS, CARD_MS, HINT_MS = 130, 160, 110


def css(p: Palette) -> str:
    swatches = "\n".join(f".sw{i} {{ background: {colour}; }}" for i, colour in enumerate(PALETTE))
    return swatches + f"""
/* ── region overlay ───────────────────────────────────────────────────── */

window.shot-overlay {{ background: transparent; }}

.shot-hint {{
  background: alpha({p.ink}, 0.92);
  color: {p.bone};
  border: 1px solid {p.edge};
  border-radius: 999px;
  padding: 7px 16px;
  font-family: {SANS};
  font-size: 12px;
  font-weight: 500;
}}
.shot-hint .key {{
  font-family: {MONO};
  font-size: 11px;
  background: {p.quill};
  border-radius: 6px;
  padding: 1px 7px;
  margin: 0 3px 0 10px;
  color: {p.bone};
}}
.shot-hint .key:first-child {{ margin-left: 0; }}

/* ── editor ───────────────────────────────────────────────────────────── */

window.shot-editor {{
  background-color: alpha(#000000, 0.58);
  font-family: {SANS};
  color: {p.bone};
}}

.card {{
  background: {p.ink};
  border: 1px solid {p.edge};
  border-radius: 20px;
  box-shadow: 0 30px 90px alpha(#000000, 0.55), 0 2px 0 alpha(#ffffff, 0.04) inset;
}}

.toolbar {{
  background: {p.pane};
  border-bottom: 1px solid {p.quill};
  border-radius: 20px 20px 0 0;
  padding: 9px 12px;
}}
.toolbar .sep {{
  background: {p.quill};
  min-width: 1px;
  margin: 4px 8px;
}}

.tool, .action {{
  background: transparent;
  border: none;
  box-shadow: none;
  border-radius: 11px;
  min-width: 34px;
  min-height: 34px;
  padding: 0;
  color: {p.ash};
}}
.tool:hover, .action:hover {{ background: {p.slate}; color: {p.bone}; }}
.tool:checked {{ background: {p.accent_dim}; color: {p.accent}; }}
.action:disabled {{ color: {p.faint}; opacity: 0.45; background: transparent; }}

.swatch {{
  min-width: 22px;
  min-height: 22px;
  border-radius: 999px;
  padding: 0;
  margin: 0 2px;
  border: 2px solid transparent;
  box-shadow: inset 0 0 0 1px alpha(#000000, 0.35);
}}
.swatch:hover {{ border-color: {p.edge}; }}
.swatch:checked {{ border-color: {p.bone}; }}

.size {{
  background: transparent;
  border: none;
  box-shadow: none;
  border-radius: 9px;
  min-width: 26px;
  min-height: 34px;
  padding: 0;
  color: {p.faint};
}}
.size:hover {{ background: {p.slate}; }}
.size:checked {{ color: {p.accent}; }}

.canvas-wrap {{ background: {p.rail}; }}
.canvas-frame {{
  box-shadow: 0 0 0 1px alpha(#ffffff, 0.08), 0 8px 30px alpha(#000000, 0.45);
}}

.footer {{
  background: {p.pane};
  border-top: 1px solid {p.quill};
  border-radius: 0 0 20px 20px;
  padding: 10px 14px;
}}
.footer .info {{
  font-family: {MONO};
  font-size: 11px;
  color: {p.ash};
}}
.footer .hint {{
  font-size: 11px;
  color: {p.faint};
}}

button.cta, button.ghost {{
  border-radius: 12px;
  padding: 7px 16px;
  font-weight: 600;
  font-size: 13px;
  box-shadow: none;
  border: 1px solid transparent;
}}
button.cta {{ background: {p.accent}; color: {p.on_accent}; }}
button.cta:hover {{ background: {mix(p.accent, "#ffffff", 0.14)}; }}
button.ghost {{ background: {p.quill}; color: {p.bone}; }}
button.ghost:hover {{ background: {p.edge}; }}
button.cta .key, button.ghost .key {{
  font-family: {MONO};
  font-size: 10px;
  font-weight: 500;
  border-radius: 6px;
  padding: 1px 6px;
  margin-left: 8px;
}}
button.cta .key {{ background: alpha({p.on_accent}, 0.16); }}
button.ghost .key {{ background: alpha({p.bone}, 0.12); }}

.toast {{
  background: alpha({p.surface_lowest}, 0.94);
  color: {p.bone};
  border: 1px solid {p.edge};
  border-radius: 999px;
  padding: 7px 16px;
  font-size: 12px;
}}

/* ── text being typed onto the picture ────────────────────────────────── */

textview.annotation, textview.annotation text {{
  background: transparent;
  caret-color: {p.accent};
  font-family: {SANS};
  font-weight: 600;
  padding: 0;
  margin: 0;
}}
.annotation-box {{
  border: 1.5px dashed alpha({p.accent}, 0.9);
  border-radius: 4px;
  background: alpha(#000000, 0.12);
}}

/* ── the emoji picker ─────────────────────────────────────────────────── */

popover.emoji > contents {{
  background: {p.ink};
  border: 1px solid {p.edge};
  border-radius: 16px;
  padding: 10px;
  box-shadow: 0 18px 60px alpha(#000000, 0.5);
}}
.platforms button {{
  background: transparent;
  border: 1px solid transparent;
  box-shadow: none;
  border-radius: 9px;
  padding: 3px 9px;
  font-size: 11px;
  font-weight: 600;
  color: {p.ash};
  min-height: 0;
}}
.platforms button:hover {{ background: {p.slate}; }}
.platforms button:checked {{ background: {p.accent_dim}; color: {p.accent}; }}
popover.emoji entry {{
  background: {p.pane};
  border: 1px solid {p.quill};
  border-radius: 10px;
  box-shadow: none;
  color: {p.bone};
  padding: 6px 10px;
  min-height: 0;
}}
popover.emoji entry:focus-within {{ border-color: {p.accent}; }}
.groups button {{
  background: transparent;
  border: none;
  box-shadow: none;
  border-radius: 8px;
  padding: 2px 6px;
  min-height: 0;
  font-size: 11px;
  color: {p.faint};
}}
.groups button:checked, .groups button:hover {{ background: {p.slate}; color: {p.bone}; }}
gridview.emoji > child {{ padding: 0; border-radius: 9px; }}
gridview.emoji > child:hover {{ background: {p.slate}; }}
gridview.emoji > child:selected, gridview.emoji > child:focus {{ background: {p.accent_dim}; }}
.empty {{ color: {p.faint}; font-size: 12px; }}

/* ── opening ──────────────────────────────────────────────────────────────
   Short on purpose: the card rises a few pixels and fades in while the dim
   comes up behind it. Closing has no animation, so Enter is never a pause.
   The `opening` class is added when the window is mapped (see editor.py), which
   is what restarts the animation on every screenshot. */

@keyframes shot-card-in {{
  from {{ opacity: 0; transform: translateY(14px) scale(0.975); }}
  to   {{ opacity: 1; transform: translateY(0) scale(1); }}
}}
@keyframes shot-dim-in {{
  from {{ background-color: alpha(#000000, 0); }}
  to   {{ background-color: alpha(#000000, 0.58); }}
}}
@keyframes shot-fade-in {{
  from {{ opacity: 0; }}
  to   {{ opacity: 1; }}
}}
window.shot-editor.opening {{ animation: shot-dim-in {DIM_MS}ms ease-out; }}
window.shot-editor.opening .card {{ animation: shot-card-in {CARD_MS}ms cubic-bezier(0.2, 0.8, 0.2, 1); }}
.shot-hint.opening {{ animation: shot-fade-in {HINT_MS}ms ease-out; }}
"""


_provider: Gtk.CssProvider | None = None
_monitors: list = []


def apply(palette: Palette | None = None) -> None:
    global _provider
    sheet = css(palette or read())
    if _provider is None:
        _provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), _provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    _provider.load_from_string(sheet)


def watch() -> None:
    """Follow the wallpaper, like the clipboard does."""
    if _monitors:
        return
    for name in ("noctalia.lua", "noctalia.conf"):
        try:
            monitor = Gio.File.new_for_path(str(WHERE / name)).monitor_file(
                Gio.FileMonitorFlags.NONE, None)
        except Exception:  # pragma: no cover - depends on the machine
            continue
        monitor.connect("changed", lambda *_: apply())
        _monitors.append(monitor)
