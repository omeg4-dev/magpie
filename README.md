# Magpie

A clipboard that keeps everything, and a browser for it — the copies, the
images, and the screenshot folder they mostly come from.

Super+V opens it. Escape closes it, Enter copies and closes, the arrows move,
and everything else in it is a button.

## What it recovered

815 clipboard entries going back to 30 May 2026, out of two dead stores and a
folder of screenshots.

## Why not just the shell's clipboard

Noctalia's clipboard is an `index.json` rewritten in full on every copy. That is
why it caps out: the setting says a hundred thousand entries and the file holds
a hundred and thirteen. Magpie is SQLite, so the hundred-thousandth copy costs
exactly what the tenth did, and nothing has to be thrown away to make room.

## How it is put together

**The store** (`store.py`) — SQLite with an FTS5 index, at `/mnt/xv/magpie`.
Two ideas hold it up:

*Content addressing.* A payload is written once under the sha256 of its bytes,
so copying the same screenshot back and forth all afternoon costs one file.

*A repeat is not a new entry.* Copying the same string again moves the entry it
already had to the top and counts it. Your Noctalia history is 113 entries and
60 distinct things — one of them copied 35 times — and a list that shows that
string 35 times is a list you cannot read.

Deleting is a tombstone, so undo is always available; a purge thirty days later
is what actually drops the bytes, and a pinned entry is never purged at all.

**Files stay where they are.** `/mnt/xv/Random/Screenshots` is a real folder
that a file manager and an editor also use, so magpie indexes it in place and
never writes to it. A screenshot and the same image on the clipboard are two
different things — one is a file you can reveal, the other is a moment in a
history — so they stay two entries even though the bytes are identical.

### The clipboard and the screenshot folder are two lists

They share a store and they are never the same list. The folder holds 2,700
files and the clipboard holds what you actually copied; pouring one into the
other buries the other. So the clipboard view is the clipboard, and the
screenshot browser is a button away.

A screenshot you take *now* still lands in both, because `screenshot.sh` puts
it on the clipboard when it saves it — one entry for the copy, one for the
file, and they are genuinely different things: one is a moment in a history,
the other is a file you can reveal in a file manager.

### Getting the old history back

Before Noctalia there was cliphist, and its database is still on disk: 750
entries, in order, with **no timestamps at all** — a monotonic counter and no
clock.

They are datable anyway. Some of those entries are screenshots that were also
*saved*, and a file on disk has a date. Hashing the payloads against the
screenshot folder matched 65 of them exactly, in strictly increasing counter
order, a median of 24 minutes apart. Everything else is interpolated over the
counter between two things that really happened.

The result: 135 entries carry a measured time, 680 carry a reconstructed one
and are marked as such — `magpie recent` prints those with a `~`, and the
viewer will say so too. An entry between two anchors is right to within the gap
between them, which is usually minutes; guessing is not the same as pretending
not to have guessed.

    magpie recover      # the one-off, ~2 seconds

## The viewer

A layer-shell surface, not a window. No border, no titlebar, no place in the
window stack to argue over: it appears where it is put, takes the keyboard, and
goes away again — the same kind of thing the bar is. It fades in over a tenth
of a second and makes a small noise, and that is the whole of the ceremony.

**It is already running when you press the key.** `magpie-view.service` builds
the window once at login and then waits, hidden. Opening it is one query and
one draw: about ten milliseconds, against half a second to start GTK and open
the store.

**The caret is always in the filter box.** Typing narrows the list whatever
else you were doing — including while you are arrowing through it, because
narrowing and looking are the same motion. Every other control has focus turned
off so that it cannot steal the keyboard.

**Nothing is drawn that is not on screen.** The list and the grid are two
virtualised views over one model, and a refresh works out the smallest change
that gets from what is shown to what is wanted (`update.py`) — usually "two new
ones at the top", which costs a millisecond instead of ninety. Thumbnails
decode when the window is idle, never while it is trying to paint.

Three modes, on the rail:

*Clipboard* — the list, newest first, with the picture on the row when the
entry is a picture. "PNG image · 75.4 kB" is the size of something you still
cannot see.

*Grid* — the same history seen denser: text on cards as well as images, because
most of a clipboard is text and a gallery of only the pictures hides it.

*Screenshots* — the folder, navigated rather than scrolled. A row of years, a
row of months under it, and only the chosen month is ever loaded. Loading all
2,700 at once is what used to bring the whole thing down.

An image can be popped out into a chromeless floating window that resizes like
any other and closes on Escape; the list gets out of the way when it does,
because a layer surface holds the keyboard exclusively.

### Keys

```
Super + V           the clipboard
Super + Shift + V   straight into the screenshot browser
Escape              close
Enter               copy and close
Up / Down           move; Left / Right too, in the grid
Page Up / Down      ten rows at a time
anything else       goes into the filter box
```

### The sounds

Two, generated by `tools/make_sounds.py` and committed as `assets/*.wav`: a
short rise when the window opens and one note when a copy lands. Quiet, under a
tenth of a second, and spawned detached — a window that waits eighty
milliseconds for a speaker is worse than a silent one. A machine with no
`pw-play`, `paplay` or `aplay` gets silence rather than an error.

**Capture** (`capture.py`) — driven by `wl-paste`, one watcher per type,
because wl-paste negotiates a single type per invocation and hands the content
over on stdin with no mime attached. The type is read back off the bytes.

The one thing it deliberately drops is a selection wl-paste marks *sensitive*.
Password managers set that flag precisely so a clipboard history does not keep
the password.

## Running it

```sh
cp systemd/* ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now magpie-watch@text magpie-watch@image magpie-sync.timer
systemctl --user enable --now magpie-view
```

`magpie-watch@text` and `@image` are the two watchers; the timer indexes new
screenshots and purges the bin, hourly. They are bound to `default.target`
rather than `graphical-session.target`, because Hyprland here starts outside
systemd and never activates it — but the user manager does have
`WAYLAND_DISPLAY`, which is all `wl-paste` needs.

Put `magpie` on `PATH`; it runs straight from the source tree:

```sh
cat > ~/.local/bin/magpie <<'SH'
#!/bin/sh
PROJECT="${MAGPIE_HOME:-$HOME/Projects/magpie}"
export PYTHONPATH="$PROJECT/src${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m magpie "$@"
SH
chmod +x ~/.local/bin/magpie
```

### From the command line

```
magpie sync             import Noctalia's history and index new screenshots
magpie recover          one-off: recover the cliphist run that came before
magpie recent [n]       what is at the top of the clipboard
magpie search <query>   find clipboard entries by their words
magpie shots [query]    the screenshot browser, which is not the clipboard
magpie stats            what the store holds
magpie purge            really drop what was deleted long ago
magpie view [--mode clipboard|grid|screenshots] [--hidden]
```

The filter box and the command line both go through the same query path, which
quotes whatever you typed as one FTS5 phrase — a clipboard is mostly URLs,
paths and command lines, and typing one in must not be read as query syntax.

### Configuring

`~/.config/magpie/config.toml`, all optional:

```toml
store = "/mnt/xv/magpie"
screenshots = "/mnt/xv/Random/Screenshots"
purge_days = 30
```

A missing or broken file is never fatal. This is the clipboard: a viewer that
refuses to open over a typo in a TOML file is worse than one that opens on the
defaults.

## Working on it

```sh
python3 -m pytest -q
```
