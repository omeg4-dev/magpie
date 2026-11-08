"""The overlay cache must not outlive the monitor it was built for.

An output switched off and on comes back as a new Gdk.Monitor with the same
connector name. An overlay still bound to the old one lands on whichever
output the compositor picks (the first), so the second screen showed the
first one's selection.
"""
import sys
import types

import pytest

pytest.importorskip("gi")

from magpie.shot.session import Session  # noqa: E402


class FakeMonitor:
    def __init__(self, connector):
        self._connector = connector

    def get_connector(self):
        return self._connector


class FakeOverlay:
    def __init__(self, app, monitor, **_callbacks):
        self.gdk_monitor = monitor
        self.destroyed = False

    def destroy(self):
        self.destroyed = True


@pytest.fixture
def session(monkeypatch):
    monkeypatch.setitem(sys.modules, "magpie.shot.overlay",
                        types.SimpleNamespace(RegionOverlay=FakeOverlay))
    s = Session.__new__(Session)      # no display here: skip __init__
    s.app = None
    s.state = "idle"
    s.overlays = {}
    s.monitors = [FakeMonitor("DP-1"), FakeMonitor("DP-2")]
    monkeypatch.setattr(Session, "_gdk_monitors", staticmethod(lambda: list(s.monitors)))
    return s


def test_same_monitor_reuses_overlay(session):
    first = session._overlay(session.monitors[1])
    assert session._overlay(session.monitors[1]) is first
    assert not first.destroyed


def test_recreated_monitor_gets_a_new_overlay(session):
    old = session._overlay(session.monitors[1])
    session.monitors[1] = FakeMonitor("DP-2")          # switched off and on
    new = session._overlay(session.monitors[1])
    assert new is not old and old.destroyed
    assert new.gdk_monitor is session.monitors[1]
    assert session.overlays["DP-2"] is new


def test_prune_drops_overlays_of_vanished_or_replaced_monitors(session):
    kept = session._overlay(session.monitors[0])
    replaced = session._overlay(session.monitors[1])
    session.monitors[1] = FakeMonitor("DP-2")
    gone = session.overlays["DP-9"] = FakeOverlay(None, FakeMonitor("DP-9"))
    session._prune_overlays()
    assert session.overlays == {"DP-1": kept}
    assert replaced.destroyed and gone.destroyed and not kept.destroyed
