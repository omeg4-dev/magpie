"""How the window looks.

Ink and bone. There is no colour on an entry — a stripe per row turned the
list into a chart of nothing, since a hash is not information about the thing
it hashes. The one accent left is teal, and it only ever means *here*: the mode
you are in, the row you are on, the caret.

Everything is rounded. A clipboard is a stack of things you picked up, and
things you pick up have corners worn off them.

Two typefaces, each for a reason. **FiraCode Nerd Font Mono** carries the
content, because the content is paths, URLs and command lines — and because
this clipboard is full of shell prompts with private-use glyphs in them
(`󰣇 ~ ❯ rsync …`), which any other family renders as a row of tofu.
**IBM Plex Sans** carries the chrome: the labels, the dates, the buttons. It is
engineered rather than neutral, which suits a window whose whole subject is a
machine's memory.
"""

from __future__ import annotations

from gi.repository import Gdk, Gtk

__all__ = ["apply", "INK", "SLATE", "QUILL", "BONE", "ASH", "RAIL", "PANE"]

#: A magpie's back: near black, with enough blue in it that the greys above it
#: read as cool rather than as dirt.
INK = "#0F1016"
SLATE = "#171922"
QUILL = "#242737"

#: The window is three things side by side — what you can do, what there is,
#: and what you have got — and they should not read as one flat sheet. So the
#: rail sits below the list and the pane sits above it, a step either way.
RAIL = "#090A0E"
PANE = "#191C27"
#: The belly. Warm, so it does not glare against the ink at two in the morning.
BONE = "#E9E7E2"
ASH = "#878A9C"

MONO = "FiraCode Nerd Font Mono, FiraCode Nerd Font, monospace"
SANS = "IBM Plex Sans, Fira Sans, sans-serif"

CSS = f"""
window.magpie {{
  background: {INK};
  color: {BONE};
  font-family: {SANS};
  border: 1px solid #2B2F42;
  border-radius: 18px;
}}

/* ── the rail ─────────────────────────────────────────────────────────── */

.rail {{
  background: {RAIL};
  border-right: 1px solid #1F2231;
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
  color: {ASH};
  box-shadow: none;
}}
.rail button:hover {{ background: {SLATE}; color: {BONE}; }}
/* The mode you are in is the one lit thing on the rail — a squared-off strip
   would fight the rounding everywhere else, so it is the glyph itself that
   changes colour. */
.rail button.on {{ background: #1B3742; color: #7FD6CE; }}

/* ── the date bar and the tally ───────────────────────────────────────── */

.datebar {{
  padding: 0 10px 6px 10px;
  border-bottom: 1px solid {QUILL};
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
.chip:hover {{ background: {SLATE}; }}
.chip.on {{ background: {QUILL}; border-color: #3A4058; }}
.chip-name {{
  font-family: {SANS};
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.06em;
  color: {ASH};
}}
.chip.on .chip-name {{ color: {BONE}; }}
.chip-count {{
  font-family: {MONO};
  font-size: 9px;
  color: #5A5E72;
}}
.chip.on .chip-count {{ color: #6FC7C0; }}
.chip.month .chip-name {{ font-size: 10px; }}

.count {{
  font-family: {SANS};
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.11em;
  color: #5A5E72;
  padding: 7px 12px 5px 12px;
}}

/* ── the filter box ───────────────────────────────────────────────────── */

.filter {{
  background: {SLATE};
  color: {BONE};
  font-family: {MONO};
  font-size: 12px;
  border: 1px solid {QUILL};
  border-radius: 12px;
  padding: 9px 12px;
  margin: 10px 10px 8px 10px;
  caret-color: #6FC7C0;
}}
.filter:focus {{ border-color: #3C6E86; outline: none; }}

/* ── the list ─────────────────────────────────────────────────────────── */

.list {{ background: {INK}; padding: 0 6px; }}
.gallery {{ background: {INK}; }}
/* A pill, not a ruled line. Rows are things, and things have edges. */
.list > row {{
  background: transparent;
  padding: 0;
  margin: 1px 0;
  border-radius: 12px;
}}
.list > row:hover {{ background: {SLATE}; }}
.list > row:selected {{ background: {QUILL}; }}

.row-body {{ padding: 8px 12px; }}
.row-text {{
  font-family: {MONO};
  font-size: 12px;
  color: {BONE};
}}
.row-meta {{
  font-family: {SANS};
  font-size: 9px;
  font-weight: 500;
  letter-spacing: 0.09em;
  color: {ASH};
  margin-top: 3px;
}}
.stamp {{
  border-radius: 8px;
  background: {QUILL};
  margin-right: 11px;
}}

/* The star is the one warm thing in here, and it means exactly one thing:
   you said to keep this. */
.star {{ font-family: {MONO}; color: #D8B45C; font-size: 10px; }}
.approx {{ color: {ASH}; font-style: italic; }}

/* ── the preview ──────────────────────────────────────────────────────── */

.preview {{ background: {PANE}; border-left: 1px solid #262A3A; }}
.preview-text {{
  font-family: {MONO};
  font-size: 12.5px;
  color: {BONE};
  padding: 18px;
}}
.preview-text text {{ background: transparent; color: {BONE}; }}
.preview-image {{ padding: 18px; }}
.preview scrolledwindow {{ background: transparent; }}

.facts {{ padding: 4px 18px 12px 18px; }}
/* The lead line is the one you read at a glance — the size of the picture,
   what it is, how big the file is. The rest is there when you look for it. */
.fact-lead {{
  font-family: {SANS};
  font-size: 11.5px;
  font-weight: 600;
  letter-spacing: 0.04em;
  color: {BONE};
}}
.fact {{
  font-family: {MONO};
  font-size: 10px;
  color: {ASH};
}}

.actions {{
  background: #14161F;
  border-top: 1px solid #262A3A;
  padding: 10px 14px;
}}
.actions > flowboxchild {{ padding: 0; background: transparent; }}
.actions button {{
  background: {SLATE};
  border: 1px solid {QUILL};
  border-radius: 11px;
  color: {BONE};
  font-family: {SANS};
  font-size: 11px;
  font-weight: 500;
  padding: 7px 13px;
  box-shadow: none;
}}
.actions button:hover {{ background: {QUILL}; }}
.actions button.primary {{
  background: #1D4B5C;
  border-color: #2C6E86;
  color: #DFF6F4;
}}
.actions button.primary:hover {{ background: #26637A; }}
.actions button.danger:hover {{ background: #5A2530; border-color: #8A3A48; }}

/* ── the gallery ──────────────────────────────────────────────────────── */

.gallery {{ background: {INK}; padding: 8px; }}
.gallery > child {{
  border-radius: 16px;
  background: transparent;
  padding: 0;
}}
.gallery > child:hover .tile {{ border-color: #3A4058; }}
.gallery > child:selected {{ background: {QUILL}; }}
.gallery > child:selected .tile {{ border-color: #4E85A0; }}
.tile {{
  border-radius: 13px;
  background: {SLATE};
  border: 1px solid {QUILL};
}}
.tile-box {{ padding: 5px; }}
/* Text tiles carry the words themselves, so the grid shows the whole history
   rather than only the part of it that happens to be pictures. */
.tile-text {{
  font-family: {MONO};
  font-size: 10.5px;
  color: {BONE};
  padding: 11px 13px;
}}
.tile-missing {{
  font-family: {MONO};
  font-size: 22px;
  color: {QUILL};
  background: {SLATE};
  border-radius: 13px;
}}
.tile-label {{
  font-family: {SANS};
  font-size: 9px;
  letter-spacing: 0.06em;
  color: {ASH};
  margin-top: 5px;
}}

/* ── the empty state and the toast ────────────────────────────────────── */

.empty {{
  font-family: {SANS};
  font-size: 13px;
  color: {ASH};
}}
.empty-hint {{
  font-family: {MONO};
  font-size: 11px;
  color: #5A5E72;
}}

.toast {{
  background: {QUILL};
  border: 1px solid #3A3E54;
  border-radius: 14px;
  padding: 9px 12px;
  margin: 12px;
  font-family: {SANS};
  font-size: 11px;
}}
.toast button {{
  background: transparent;
  border: none;
  color: #6FC7C0;
  font-weight: 600;
  padding: 2px 8px;
  box-shadow: none;
}}

/* ── the pop-out ──────────────────────────────────────────────────────── */

window.popout {{ background: {INK}; border-radius: 14px; }}
"""


def apply() -> None:
    """Load the stylesheet once, for every window this process opens."""
    provider = Gtk.CssProvider()
    provider.load_from_string(CSS)
    Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
