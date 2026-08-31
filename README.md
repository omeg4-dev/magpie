# Magpie

A clipboard that keeps everything, and a browser for it — the copies, the
images, and the screenshot folder they mostly come from.

> The store and the capture side are done and running. The viewer is next.

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
magpie sync             import Noctalia's history and the screenshot folder
magpie recent [n]       what is at the top
magpie search <query>   find entries by their words
magpie stats            what the store holds
magpie purge            really drop what was deleted long ago
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
