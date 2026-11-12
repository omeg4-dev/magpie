"""`magpie doctor`: restart the resident window when it has died."""

from types import SimpleNamespace

from magpie.cli import alive, cmd_doctor


def _runner(ping_ok: bool, restart_ok: bool = True):
    calls = []

    def run(cmd, **_kw):
        calls.append(cmd[0])
        if cmd[0] == "gdbus":
            return SimpleNamespace(returncode=0 if ping_ok else 1)
        if cmd[0] == "systemctl":
            return SimpleNamespace(returncode=0 if restart_ok else 1)
        return SimpleNamespace(returncode=0)

    return run, calls


def test_alive_daemon_is_left_alone():
    run, calls = _runner(ping_ok=True)
    assert cmd_doctor(None, [], run=run) == 0
    assert calls == ["gdbus"]


def test_dead_daemon_is_restarted_and_the_user_told():
    run, calls = _runner(ping_ok=False)
    assert cmd_doctor(None, [], run=run) == 0
    assert calls == ["gdbus", "systemctl", "notify-send"]


def test_failed_restart_is_a_failure():
    run, _ = _runner(ping_ok=False, restart_ok=False)
    assert cmd_doctor(None, [], run=run) == 1


def test_missing_gdbus_counts_as_dead():
    def boom(*_a, **_k):
        raise OSError("no gdbus")
    assert alive(boom) is False
