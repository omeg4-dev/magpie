import threading
import time

from magpie.shot.thumbs import Thumbs


def _wait(cond, timeout=3.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.005)
    return False


def test_renders_off_thread_and_delivers():
    seen, threads = [], set()

    def render(c):
        threads.add(threading.current_thread().name)
        return c.upper()

    t = Thumbs(render, lambda chars: seen.extend(chars))
    t.want(["a", "b", "c"])
    assert _wait(lambda: len(seen) == 3)
    assert t.get("b") == "B" and t.get("zzz") is None
    assert threads == {"emoji-thumbs"}
    t.close()


def test_latest_want_goes_first():
    gate = threading.Event()
    order = []

    def render(c):
        gate.wait(2)
        order.append(c)
        return c

    t = Thumbs(render, lambda chars: None, batch=1)
    t.prefetch(["p1", "p2", "p3"])
    assert _wait(lambda: t.pending < 3)       # worker took p1 and is blocked on the gate
    t.want(["w1", "w2"])
    gate.set()
    assert _wait(lambda: len(order) == 5)
    assert order[1:3] == ["w1", "w2"]          # visible cells jump the prefetch queue, in order
    t.close()


def test_failures_are_remembered_not_retried():
    calls = []

    def render(c):
        calls.append(c)
        raise OSError("no glyph")

    t = Thumbs(render, lambda chars: None)
    t.want(["x"])
    assert _wait(lambda: len(t) == 1)
    t.want(["x"])
    time.sleep(0.05)
    assert calls == ["x"] and t.get("x") is None


def test_limit_evicts_least_recent():
    t = Thumbs(lambda c: c, lambda chars: None, limit=3, batch=10)
    t.want(list("abcde"))
    assert _wait(lambda: t.pending == 0 and len(t) == 3)
    assert t.get("a") is None and t.get("e") == "e"
    t.close()


def test_forget_queue_and_restart_after_idle():
    gate = threading.Event()
    t = Thumbs(lambda c: (gate.wait(2), c)[1], lambda chars: None, batch=1)
    t.prefetch(list("abcdef"))
    assert _wait(lambda: t.pending <= 5)
    t.forget_queue()
    assert t.pending == 0
    gate.set()
    t.want(["z"])                              # the same worker (or a new one) still serves
    assert _wait(lambda: t.get("z") == "z")
    t.close()
