from __future__ import annotations

import os
import subprocess
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import magpie.shot.output as shot_output
from magpie.shot.output import (
    DEFAULT_ROOT,
    FALLBACK_ROOT,
    Saved,
    UploadError,
    copy_image,
    deliver,
    notify,
    save_png,
    target_path,
    upload_catbox,
)


def test_target_path_formatting_and_mount_usable(tmp_path):
    fixed_time = datetime(2026, 11, 4, 19, 36, 39)
    root = tmp_path / "screenshots"

    # Usable mount
    p, fell_back = target_path(
        fixed_time,
        root=root,
        fallback=tmp_path / "fallback",
        is_mount=lambda path: path == tmp_path,
    )
    assert not fell_back
    assert p == root / "2026-11" / "04-11-2026--19-36-39.png"


def test_target_path_unusable_mount_falls_back(tmp_path):
    fixed_time = datetime(2026, 11, 4, 19, 36, 39)
    unusable_root = tmp_path / "nomount" / "x"
    fallback_root = tmp_path / "fallback"

    p, fell_back = target_path(
        fixed_time,
        root=unusable_root,
        fallback=fallback_root,
        is_mount=lambda path: False,
    )
    assert fell_back
    assert p == fallback_root / "2026-11" / "04-11-2026--19-36-39.png"


def test_target_path_collision_avoidance(tmp_path):
    fixed_time = datetime(2026, 11, 4, 19, 36, 39)
    root = tmp_path / "screenshots"
    month_dir = root / "2026-11"
    month_dir.mkdir(parents=True)

    base_file = month_dir / "04-11-2026--19-36-39.png"
    base_file.touch()

    # First collision should give -1
    p1, _ = target_path(fixed_time, root=root, is_mount=lambda p: p == tmp_path)
    assert p1 == month_dir / "04-11-2026--19-36-39-1.png"

    # Create -1, next collision should give -2
    p1.touch()
    p2, _ = target_path(fixed_time, root=root, is_mount=lambda p: p == tmp_path)
    assert p2 == month_dir / "04-11-2026--19-36-39-2.png"


def test_save_png_writes_and_cleans_up_on_error(tmp_path, monkeypatch):
    target = tmp_path / "sub" / "shot.png"
    data = b"fake-png-bytes"

    save_png(data, target)
    assert target.exists()
    assert target.read_bytes() == data
    assert (target.stat().st_mode & 0o777) == 0o644

    # Verify no .tmp files left
    tmp_files = list((tmp_path / "sub").glob(".*.tmp"))
    assert not tmp_files

    # When os.replace fails, temp file must be cleaned up and error re-raised
    def fail_replace(src, dst):
        raise OSError("Disk full")

    monkeypatch.setattr(os, "replace", fail_replace)
    target2 = tmp_path / "sub" / "shot2.png"
    with pytest.raises(OSError, match="Disk full"):
        save_png(data, target2)

    assert not target2.exists()
    assert not list((tmp_path / "sub").glob(".*.tmp"))


def test_copy_image(tmp_path, png, monkeypatch):
    flag = tmp_path / "ignore_clip_notify"
    monkeypatch.setattr(shot_output, "IGNORE_FLAG", flag)

    recorded_calls = []

    def fake_run(cmd, **kwargs):
        recorded_calls.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    copy_image(png, run=fake_run)
    assert flag.exists()
    assert len(recorded_calls) == 1
    cmd, kwargs = recorded_calls[0]
    assert cmd == ["wl-copy", "--type", "image/png"]
    assert kwargs.get("input") == png
    assert kwargs.get("check") is True
    assert kwargs.get("timeout") == 10


def test_deliver_success(tmp_path, store, png, monkeypatch):
    flag = tmp_path / "ignore_clip_notify"
    monkeypatch.setattr(shot_output, "IGNORE_FLAG", flag)

    recorded_run = []
    recorded_play = []

    def fake_run(cmd, **kwargs):
        recorded_run.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    def fake_play(sound):
        recorded_play.append(sound)

    saved = deliver(
        png,
        store,
        now=datetime(2026, 11, 4, 19, 36, 39),
        root=tmp_path / "shots",
        is_mount=lambda p: p == tmp_path,
        run=fake_run,
        play=fake_play,
    )

    assert isinstance(saved, Saved)
    assert not saved.fell_back
    assert saved.path.exists()
    assert saved.path.read_bytes() == png

    # wl-copy called correctly
    assert len(recorded_run) == 1
    assert recorded_run[0][0] == ["wl-copy", "--type", "image/png"]
    assert recorded_run[0][1]["input"] == png

    # Indexed in store
    assert store.count(source="screenshot") == 1

    # Sound played
    assert recorded_play == ["copy"]


def test_deliver_clipboard_failure_preserves_file_and_store(tmp_path, store, png, monkeypatch):
    flag = tmp_path / "ignore_clip_notify"
    monkeypatch.setattr(shot_output, "IGNORE_FLAG", flag)

    def failing_run(cmd, **kwargs):
        raise subprocess.CalledProcessError(1, cmd, stderr="wl-copy: error")

    play_called = []

    with pytest.raises(RuntimeError) as exc_info:
        deliver(
            png,
            store,
            now=datetime(2026, 11, 4, 19, 36, 39),
            root=tmp_path / "shots",
            is_mount=lambda p: p == tmp_path,
            run=failing_run,
            play=lambda s: play_called.append(s),
        )

    # Path mentioned in error
    assert str(tmp_path / "shots") in str(exc_info.value)
    # File still exists
    expected_path = tmp_path / "shots" / "2026-11" / "04-11-2026--19-36-39.png"
    assert expected_path.exists()
    assert expected_path.read_bytes() == png
    # Store entry was still created
    assert store.count(source="screenshot") == 1
    # Sound was still played
    assert play_called == ["copy"]


def test_upload_catbox(tmp_path):
    dummy_file = tmp_path / "test.png"
    dummy_file.write_bytes(b"data")

    # Success case
    def success_run(cmd, **kwargs):
        assert cmd[:4] == ["curl", "-s", "--max-time", "60"]
        assert f"fileToUpload=@{dummy_file}" in cmd
        return subprocess.CompletedProcess(cmd, 0, stdout="https://files.catbox.moe/abc123.png\n", stderr="")

    url = upload_catbox(dummy_file, run=success_run)
    assert url == "https://files.catbox.moe/abc123.png"

    # Non-zero exit code
    def fail_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 28, stdout="", stderr="Connection timed out")

    with pytest.raises(UploadError, match="Connection timed out"):
        upload_catbox(dummy_file, run=fail_run)

    # Non-http response
    def bad_resp_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 0, stdout="Error: file too large", stderr="")

    with pytest.raises(UploadError, match="Error: file too large"):
        upload_catbox(dummy_file, run=bad_resp_run)


def test_notify_open_action(tmp_path, monkeypatch):
    saved = Saved(tmp_path / "shot.png", fell_back=False)
    opened = []

    monkeypatch.setattr(shot_output, "_open", lambda p: opened.append(p))

    def fake_spawn(target, daemon=True):
        assert daemon is True
        class SyncThread:
            def start(self):
                target()
        return SyncThread()

    def fake_run(cmd, **kwargs):
        if cmd[0] == "notify-send":
            return subprocess.CompletedProcess(cmd, 0, stdout="open\n")
        return subprocess.CompletedProcess(cmd, 0)

    notify(saved, spawn=fake_spawn, run=fake_run)
    assert opened == [saved.path]


def test_notify_upload_action(tmp_path, monkeypatch):
    saved = Saved(tmp_path / "shot.png", fell_back=False)
    flag = tmp_path / "ignore_clip_notify"
    monkeypatch.setattr(shot_output, "IGNORE_FLAG", flag)

    run_calls = []

    def fake_spawn(target, daemon=True):
        class SyncThread:
            def start(self):
                target()
        return SyncThread()

    def fake_run(cmd, **kwargs):
        run_calls.append(cmd)
        if cmd[0] == "notify-send" and "-A" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout="upload\n")
        if cmd[0] == "curl":
            return subprocess.CompletedProcess(cmd, 0, stdout="https://files.catbox.moe/xyz.png\n")
        return subprocess.CompletedProcess(cmd, 0)

    notify(saved, spawn=fake_spawn, run=fake_run)

    assert flag.exists()
    # Check that wl-copy was called with the uploaded URL
    wl_copy_calls = [cmd for cmd in run_calls if cmd[0] == "wl-copy"]
    assert len(wl_copy_calls) == 1
    assert wl_copy_calls[0] == ["wl-copy", "https://files.catbox.moe/xyz.png"]
