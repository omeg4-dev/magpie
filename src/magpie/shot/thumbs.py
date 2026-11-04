"""Emoji thumbnails, drawn off the UI thread.

The picker's grid binds a few hundred cells the moment a group opens, and drawing
one emoji from a colour font costs about 0.7 ms — so doing it inside `bind` meant
a 200 ms stall per group and dropped frames while scrolling. Here a cell asks for
its picture and gets either the finished one or nothing yet; the drawing happens
on a worker thread, newest request first (what is on screen now matters more than
what was asked for a moment ago), and the caller is told when pictures arrive.

No toolkit in this file: the caller turns the RGBA bytes into a texture.
"""

from __future__ import annotations

import threading
from collections import OrderedDict, deque
from typing import Callable, Iterable

__all__ = ["Thumbs"]


class Thumbs:
    """Finished pictures by character, plus a worker that makes the missing ones.

    `render(char) -> object | None` runs on the worker thread and returns whatever
    the caller wants to keep (RGBA bytes, a PIL image...); `None` means "cannot be
    drawn", remembered so it is not retried. `deliver(chars)` is called on the
    worker thread with each finished batch; hop to the UI thread inside it.
    """

    def __init__(self, render: Callable[[str], object | None],
                 deliver: Callable[[list[str]], None], *, limit: int = 2500,
                 batch: int = 24) -> None:
        self._render, self._deliver = render, deliver
        self._limit, self._batch = limit, batch
        self._done: OrderedDict[str, object | None] = OrderedDict()
        self._queue: deque[str] = deque()
        self._queued: set[str] = set()
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        self._closed = False
        self._running = False       # a worker exists; read and written under the lock

    # -- asking ---------------------------------------------------------------

    def get(self, char: str) -> object | None:
        """The finished picture, or None if it is not ready (or cannot be drawn)."""
        with self._lock:
            value = self._done.get(char)
            if char in self._done:
                self._done.move_to_end(char)
            return value

    def want(self, chars: Iterable[str]) -> None:
        """These are on screen now: draw the missing ones first, in the order given."""
        with self._wake:
            fresh = [c for c in chars if c not in self._done and c not in self._queued]
            # extendleft reverses, so reverse first to keep the caller's order.
            self._queue.extendleft(reversed(fresh))
            self._queued.update(fresh)
            self._start()
            self._wake.notify()

    def prefetch(self, chars: Iterable[str]) -> None:
        """Draw these when nothing more urgent is waiting."""
        with self._wake:
            fresh = [c for c in chars if c not in self._done and c not in self._queued]
            self._queue.extend(fresh)
            self._queued.update(fresh)
            self._start()
            self._wake.notify()

    def forget_queue(self) -> None:
        """Stop drawing what was waiting (the user moved elsewhere); keep what is done."""
        with self._lock:
            self._queue.clear()
            self._queued.clear()

    def close(self) -> None:
        with self._wake:
            self._closed = True
            self._wake.notify_all()

    @property
    def pending(self) -> int:
        with self._lock:
            return len(self._queue)

    def __len__(self) -> int:
        with self._lock:
            return len(self._done)

    # -- the worker -----------------------------------------------------------

    def _start(self) -> None:
        if not self._running:
            self._running = True
            threading.Thread(target=self._work, name="emoji-thumbs", daemon=True).start()

    def _work(self) -> None:
        while True:
            with self._wake:
                while not self._queue and not self._closed:
                    self._wake.wait(timeout=30)
                    if not self._queue:
                        self._running = False   # idle for a while: the next want() starts a new one
                        return
                if self._closed:
                    self._running = False
                    return
                chars = []
                while self._queue and len(chars) < self._batch:
                    chars.append(self._queue.popleft())

            finished: list[str] = []
            for char in chars:
                try:
                    value = self._render(char)
                except Exception:       # a broken glyph must not stop the rest
                    value = None
                with self._lock:
                    self._queued.discard(char)
                    self._done[char] = value
                    self._done.move_to_end(char)
                    while len(self._done) > self._limit:
                        self._done.popitem(last=False)
                finished.append(char)
            try:
                self._deliver(finished)
            except Exception:
                pass
