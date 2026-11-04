import os
import stat
import sys
import time
from pathlib import Path
import pytest
from PIL import Image

from magpie.shot.upscale import (
    BINARY,
    LOW_RES_EDGE,
    LOW_RES_PIXELS,
    MAX_INPUT_PIXELS,
    Cancelled,
    Job,
    UpscaleError,
    available,
    binary,
    command,
    start,
    suggest,
)


def test_suggest_table():
    """Table of test resolutions for suggest(w, h):
    Thresholds: LOW_RES_PIXELS = 500_000, LOW_RES_EDGE = 1000.
    True if w*h < LOW_RES_PIXELS or max(w, h) < LOW_RES_EDGE.

    Table:
    - 300x200:   pixels=60,000 (<500k),   max_edge=300 (<1000)   -> True
    - 800x600:   pixels=480,000 (<500k),  max_edge=800 (<1000)   -> True
    - 1200x300:  pixels=360,000 (<500k),  max_edge=1200 (>=1000) -> True (pixels < 500k)
    - 900x900:   pixels=810,000 (>=500k), max_edge=900 (<1000)   -> True (edge < 1000)
    - 1920x1080: pixels=2,073,600,        max_edge=1920          -> False
    - 3000x400:  pixels=1,200,000,        max_edge=3000          -> False
    """
    assert suggest(300, 200) is True
    assert suggest(800, 600) is True
    assert suggest(1200, 300) is True
    assert suggest(900, 900) is True
    assert suggest(1920, 1080) is False
    assert suggest(3000, 400) is False


def test_command_exact_list():
    bin_path = "/usr/bin/realesrgan-ncnn-vulkan"
    expected = [
        bin_path,
        "-i",
        "in.png",
        "-o",
        "out.png",
        "-n",
        "realesrgan-x4plus",
        "-s",
        "4",
        "-g",
        "0",
        "-f",
        "png",
        "-v",
    ]
    assert command(bin_path, "in.png", "out.png", 4) == expected
    assert command(bin_path, "in.png", "out.png", 2) == expected

    with pytest.raises(ValueError):
        command(bin_path, "in.png", "out.png", 3)


def _create_fake_binary(bin_dir: Path, script_body: str) -> Path:
    bin_path = bin_dir / BINARY
    content = f"#!{sys.executable}\n" + script_body
    bin_path.write_text(content)
    bin_path.chmod(bin_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_path


def test_upscale_with_fake_binary(tmp_path, monkeypatch):
    seen_src_file = tmp_path / "seen_src.txt"

    # Fake tool that logs src, writes progress, and enlarges input 4x
    fake_code = f"""
import sys, argparse
from PIL import Image

args = sys.argv[1:]
src = args[args.index("-i") + 1]
dst = args[args.index("-o") + 1]

with open(r"{seen_src_file}", "w") as f:
    f.write(src)

sys.stderr.write("0.00%\\n")
sys.stderr.flush()
sys.stderr.write("50.00%\\n")
sys.stderr.flush()
sys.stderr.write("100.00%\\n")
sys.stderr.flush()

im = Image.open(src)
im.resize((im.width * 4, im.height * 4), Image.NEAREST).save(dst)
"""
    _create_fake_binary(tmp_path, fake_code)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")
    assert available() is True

    # 1. Factor 4 test with RGBA image
    img_rgba = Image.new("RGBA", (20, 10), (255, 0, 0, 128))
    done_calls = []
    progress_updates = []

    def on_progress(p):
        progress_updates.append(p)

    def on_done(j):
        done_calls.append(j)

    job4 = start(img_rgba, 4, on_progress=on_progress, on_done=on_done)
    res4 = job4.result()

    assert res4.size == (80, 40)
    assert res4.mode == "RGBA"
    # Check alpha was preserved
    assert res4.getpixel((0, 0))[3] == 128
    assert job4.progress == 1.0
    assert 1.0 in progress_updates
    assert len(done_calls) == 1
    assert done_calls[0] is job4

    # Verify temp dir is removed
    seen_src = seen_src_file.read_text().strip()
    assert seen_src != ""
    assert not Path(seen_src).parent.exists()

    # 2. Factor 2 test
    img_rgb = Image.new("RGB", (30, 20), (0, 255, 0))
    job2 = start(img_rgb, 2)
    res2 = job2.result()
    assert res2.size == (60, 40)
    assert res2.mode == "RGB"
    assert job2.progress == 1.0


def test_upscale_error_exit_code(tmp_path, monkeypatch):
    fake_code = """
import sys
sys.stderr.write("internal failure: boom\\n")
sys.exit(1)
"""
    _create_fake_binary(tmp_path, fake_code)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")

    img = Image.new("RGB", (10, 10))
    job = start(img, 4)
    with pytest.raises(UpscaleError) as exc_info:
        job.result()
    assert "boom" in str(exc_info.value)


def test_upscale_cancel(tmp_path, monkeypatch):
    fake_code = """
import time
time.sleep(30)
"""
    _create_fake_binary(tmp_path, fake_code)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ.get('PATH', '')}")

    img = Image.new("RGB", (10, 10))
    t0 = time.monotonic()
    job = start(img, 4)
    time.sleep(0.1)
    job.cancel()

    with pytest.raises(Cancelled):
        job.result()

    duration = time.monotonic() - t0
    assert duration < 3.0


def test_no_binary_on_path(monkeypatch):
    monkeypatch.setenv("PATH", "")
    assert available() is False
    assert binary() is None

    img = Image.new("RGB", (10, 10))
    with pytest.raises(UpscaleError) as exc_info:
        start(img, 4)
    assert "realesrgan-ncnn-vulkan is not installed" in str(exc_info.value)


def test_oversized_input_raises_synchronously():
    # 3000 x 2000 = 6_000_000 pixels > MAX_INPUT_PIXELS (4_000_000)
    huge = Image.new("RGB", (3000, 2000))
    with pytest.raises(UpscaleError) as exc_info:
        start(huge, 4)
    assert "image too large to upscale" in str(exc_info.value)
