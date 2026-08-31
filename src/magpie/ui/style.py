"""How the window looks.

The colours are not magpie's. Noctalia regenerates the desktop's palette from
the wallpaper, and this reads it (`palette.py`) and derives everything from it:
the three panels are the wallpaper's own surface colour stepped up and down,
the caret and the selected mode are its primary, and the text is white tinted
towards the same. When the wallpaper changes the window changes with it,
without being restarted — there is a monitor on the file.

Two colours are fixed, because they mean something rather than match something:
the star is yellow, and the delete button is the theme's error colour.

Two typefaces, each for a reason. **FiraCode Nerd Font Mono** carries the
content, because the content is paths, URLs and command lines — and because
this clipboard is full of shell prompts with private-use glyphs in them
(`󰣇 ~ ❯ rsync …`), which any other family renders as a row of tofu.
**IBM Plex Sans** carries the chrome: the labels, the dates, the buttons. It is
engineered rather than neutral, which suits a window whose whole subject is a
machine's memory.

Everything is rounded. A clipboard is a stack of things you picked up, and
things you pick up have corners worn off them.
"""

from __future__ import annotations

from gi.repository import Gdk, Gio, Gtk

from ..palette import WHERE, Palette, mix, read

__all__ = ["apply", "css", "watch"]

MONO = "FiraCode Nerd Font Mono, FiraCode Nerd Font, monospace"
SANS = "IBM Plex Sans, Fira Sans, sans-serif"


def css(p: Palette) -> str:
    return f"""
window.magpie {{
  background: {p.ink};
  color: {p.bone};
  font-family: {SANS};
  border: 1px solid {p.edge};
  border-radius: 18px;
}}

/* ── the rail ─────────────────────────────────────────────────────────── */

.rail {{
  background: {p.rail};
  border-right: 1px solid {p.quill};
  padding: 10px 0;
}}
.rail button {{
  font-family: {MONO};
  font-size: 15px;
  background: transparent;
  border: none;
  border-radius: 13px;
  margin: 3px 8px;
  padding: 9px;
  color: {p.faint};
  box-shadow: none;
}}
.rail button:hover {{ background: {p.slate}; color: {p.bone}; }}
/* The mode you are in is the one lit thing on the rail — a squared-off strip
   would fight the rounding everywhere else, so it is the glyph itself that
   changes colour. */
.rail button.on {{ background: {p.accent_dim}; color: {p.accent}; }}

/* ── the date bar and the tally ───────────────────────────────────────── */

.datebar {{
  padding: 0 10px 6px 10px;
  border-bottom: 1px solid {p.quill};
}}
.chips {{ padding: 3px 0; }}
.chips > flowboxchild {{ padding: 0; background: transparent; }}
.chip {{
  background: transparent;
  border: 1px solid transparent;
  border-radius: 10px;
  padding: 4px 9px;
  box-shadow: none;
}}
.chip:hover {{ background: {p.slate}; }}
.chip.on {{ background: {p.quill}; border-color: {p.edge}; }}
.chip-name {{
  font-family: {SANS};
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: {p.ash};
}}
.chip.on .chip-name {{ color: {p.bone}; }}
.chip-count {{
  font-family: {MONO};
  font-size: 9px;
  color: {p.faint};
}}
.chip.on .chip-count {{ color: {p.accent}; }}
.chip.month .chip-name {{ font-size: 10px; }}

.count {{
  font-family: {SANS};
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.11em;
  color: {p.faint};
  padding: 7px 12px 5px 12px;
}}

/* ── the filter box ───────────────────────────────────────────────────── */

.filter {{
  background: {p.slate};
  color: {p.bone};
  font-family: {MONO};
  font-size: 12px;
  border: 1px solid {p.quill};
  border-radius: 12px;
  padding: 9px 12px;
  margin: 10px 10px 8px 10px;
  caret-color: {p.accent};
}}
.filter:focus {{ border-color: {p.accent}; outline: none; }}

/* ── the list ─────────────────────────────────────────────────────────── */

.list {{ background: {p.ink}; padding: 0 6px; }}
.gallery {{ background: {p.ink}; padding: 8px; }}
/* A pill, not a ruled line. Rows are things, and things have edges. */
.list > row {{
  background: transparent;
  padding: 0;
  margin: 1px 0;
  border-radius: 12px;
}}
.list > row:hover {{ background: {p.slate}; }}
.list > row:selected {{ background: {p.quill}; }}

.row-body {{ padding: 8px 12px; }}
.row-text {{
  font-family: {MONO};
  font-size: 12px;
  color: {p.bone};
}}
.row-meta {{
  font-family: {SANS};
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.09em;
  color: {p.ash};
  margin-top: 3px;
}}

.stamp {{
  border-radius: 8px;
  background: {p.quill};
  margin-left: 11px;
}}

/* The star on a row. It is always here, holding its place; what changes is
   whether you can see it. */
.row-star {{
  font-family: {MONO};
  font-size: 12px;
  color: {p.faint};
  padding: 0 4px 0 12px;
}}
.row-star.on {{ color: {p.gold}; }}
.row-star:hover {{ color: {p.gold}; }}

.approx {{ color: {p.ash}; font-style: italic; }}

/* ── the preview ──────────────────────────────────────────────────────── */

.preview {{ background: {p.pane}; border-left: 1px solid {p.quill}; }}
.preview-text {{
  font-family: {MONO};
  font-size: 12.5px;
  color: {p.bone};
  padding: 18px;
}}
.preview-text text {{ background: transparent; color: {p.bone}; }}
.preview-image {{ padding: 18px; }}
.preview scrolledwindow {{ background: transparent; }}

/* The facts and the buttons are one footer under the picture, not two boxes
   stacked on it: one hairline above the whole thing, nothing between them. */
.footer {{ border-top: 1px solid {p.quill}; }}
.facts {{ padding: 12px 18px 4px 18px; }}
.fact-lead {{
  font-family: {MONO};
  font-size: 11px;
  color: {p.bone};
}}
.fact {{
  font-family: {MONO};
  font-size: 11px;
  color: {p.ash};
}}

.actions {{
  background: transparent;
  padding: 8px 14px 12px 14px;
}}
.actions button {{
  background: {p.slate};
  border: 1px solid {p.quill};
  border-radius: 11px;
  color: {p.bone};
  font-family: {SANS};
  font-size: 11px;
  font-weight: 500;
  padding: 7px 13px;
  box-shadow: none;
}}
.actions button:hover {{ background: {p.quill}; }}
.actions button.primary {{
  background: {p.accent_dim};
  border-color: {p.accent};
  color: {p.accent};
}}
.actions button.primary:hover {{ background: {mix(p.surface, p.primary, 0.34)}; }}
.actions button.danger:hover {{
  background: {mix(p.surface, p.error, 0.30)};
  border-color: {p.danger};
  color: {p.danger};
}}

/* ── the gallery ──────────────────────────────────────────────────────── */

.gallery > child {{
  border-radius: 16px;
  background: transparent;
  padding: 0;
}}
.gallery > child:hover .tile {{ border-color: {p.edge}; }}
.gallery > child:selected {{ background: {p.quill}; }}
.gallery > child:selected .tile {{ border-color: {p.accent}; }}
.tile {{
  border-radius: 13px;
  background: {p.slate};
  border: 1px solid {p.quill};
}}
.tile-box {{ padding: 5px; }}
/* Text tiles carry the words themselves, so the grid shows the whole history
   rather than only the part of it that happens to be pictures. */
.tile-text {{
  font-family: {MONO};
  font-size: 10.5px;
  color: {p.bone};
  padding: 11px 13px;
}}
.tile-missing {{
  font-family: {MONO};
  font-size: 22px;
  color: {p.quill};
  background: {p.slate};
  border-radius: 13px;
}}
.tile-label {{
  font-family: {SANS};
  font-size: 9px;
  letter-spacing: 0.06em;
  color: {p.ash};
  margin-top: 5px;
}}

/* ── the empty state and the toast ────────────────────────────────────── */

.empty {{
  font-family: {SANS};
  font-size: 13px;
  color: {p.ash};
}}
.empty-hint {{
  font-family: {MONO};
  font-size: 11px;
  color: {p.faint};
}}

.toast {{
  background: {p.quill};
  border: 1px solid {p.edge};
  border-radius: 14px;
  padding: 9px 12px;
  margin: 12px;
  font-family: {SANS};
  font-size: 11px;
}}
.toast button {{
  background: transparent;
  border: none;
  color: {p.accent};
  font-weight: 600;
  padding: 2px 8px;
  box-shadow: none;
}}

/* ── the pop-out ──────────────────────────────────────────────────────── */

window.popout {{ background: {p.ink}; border-radius: 14px; }}
"""


_provider: Gtk.CssProvider | None = None
_monitors: list = []


def apply(palette: Palette | None = None) -> None:
    """Load the stylesheet, or reload it in place when the wallpaper changes."""
    global _provider
    sheet = css(palette or read())
    if _provider is None:
        _provider = Gtk.CssProvider()
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(), _provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    # Loading into the provider that is already installed restyles every open
    # window; adding another one would only stack.
    _provider.load_from_string(sheet)


def watch() -> None:
    """Follow the wallpaper. Noctalia rewrites these files on every change."""
    for name in ("noctalia.lua", "noctalia.conf"):
        try:
            monitor = Gio.File.new_for_path(str(WHERE / name)).monitor_file(
                Gio.FileMonitorFlags.NONE, None)
        except Exception:  # pragma: no cover - depends on the machine
            continue
        monitor.connect("changed", lambda *_: apply())
        _monitors.append(monitor)
