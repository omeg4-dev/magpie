"""Wrapper around the realesrgan-ncnn-vulkan upscaler."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

from PIL import Image

__all__ = [
    "BINARY",
    "LOW_RES_PIXELS",
    "LOW_RES_EDGE",
    "MAX_INPUT_PIXELS",
    "UpscaleError",
    "Cancelled",
    "Job",
    "binary",
    "available",
    "suggest",
    "command",
    "start",
]

BINARY = "realesrgan-ncnn-vulkan"
LOW_RES_PIXELS = 500_000
LOW_RES_EDGE = 1000
MAX_INPUT_PIXELS = 4_000_000

_PROGRESS_RE = re.compile(r"(\d+(?:\.\d+)?)%")
_LANCZOS = getattr(getattr(Image, "Resampling", Image), "LANCZOS", Image.LANCZOS)


def binary() -> str | None:
    return shutil.which(BINARY)


def available() -> bool:
    return binary() is not None


def suggest(width: int, height: int) -> bool:
    """Pure function: True if width*height < LOW_RES_PIXELS or max(width, height) < LOW_RES_EDGE."""
    return (width * height < LOW_RES_PIXELS) or (max(width, height) < LOW_RES_EDGE)


class UpscaleError(Exception):
    """Raised when an upscale operation fails."""


class Cancelled(UpscaleError):
    """Raised when an upscale operation was cancelled."""


class Job:
    def __init__(self) -> None:
        self.progress: float = 0.0
        self._cancelled: bool = False
        self._process: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._done_event = threading.Event()
        self._result: Image.Image | None = None
        self._error: Exception | None = None

    def cancel(self) -> None:
        """Terminate the subprocess, idempotent."""
        self._cancelled = True
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                try:
                    self._process.terminate()
                except OSError:
                    pass

    def result(self) -> Image.Image:
        """Block until finished; raises UpscaleError or Cancelled."""
        self._done_event.wait()
        if self._cancelled or isinstance(self._error, Cancelled):
            raise Cancelled("upscale cancelled")
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise UpscaleError("upscale produced no result")
        return self._result

    def _run(
        self,
        image: Image.Image,
        factor: int,
        bin_path: str,
        on_progress: Callable[[float], None] | None,
        on_done: Callable[[Job], None] | None,
    ) -> None:
        try:
            if self._cancelled:
                raise Cancelled("upscale cancelled")

            orig_w, orig_h = image.size
            has_alpha = ("A" in image.getbands()) or ("transparency" in image.info)

            if has_alpha:
                rgba = image.convert("RGBA")
                rgb_image = rgba.convert("RGB")
                alpha_channel = rgba.getchannel("A")
            else:
                rgb_image = image.convert("RGB")
                alpha_channel = None

            with tempfile.TemporaryDirectory() as tmp_dir:
                tmp_path = Path(tmp_dir)
                src_path = str(tmp_path / "input.png")
                dst_path = str(tmp_path / "output.png")

                rgb_image.save(src_path, format="PNG")

                cmd = command(bin_path, src_path, dst_path, factor)

                with self._lock:
                    if self._cancelled:
                        raise Cancelled("upscale cancelled")
                    self._process = subprocess.Popen(
                        cmd,
                        stderr=subprocess.PIPE,
                        stdout=subprocess.DEVNULL,
                        text=True,
                        bufsize=1,
                    )

                stderr_lines: list[str] = []
                assert self._process.stderr is not None
                for line in iter(self._process.stderr.readline, ""):
                    line_str = line.strip()
                    if line_str:
                        stderr_lines.append(line_str)
                        m = _PROGRESS_RE.search(line_str)
                        if m:
                            self.progress = float(m.group(1)) / 100.0
                            if on_progress:
                                try:
                                    on_progress(self.progress)
                                except Exception:
                                    pass

                self._process.wait()

                if self._cancelled:
                    raise Cancelled("upscale cancelled")

                if self._process.returncode != 0:
                    tail = "\n".join(stderr_lines[-10:])
                    raise UpscaleError(
                        f"upscale failed (exit {self._process.returncode}): {tail}"
                    )

                if not os.path.exists(dst_path):
                    tail = "\n".join(stderr_lines[-10:])
                    raise UpscaleError(f"upscale produced no output file: {tail}")

                with Image.open(dst_path) as out_im:
                    upscaled_4x = out_im.convert("RGB")
                    upscaled_4x.load()

                if upscaled_4x.size != (orig_w * 4, orig_h * 4):
                    raise UpscaleError(
                        f"unexpected tool output size {upscaled_4x.size}, expected ({orig_w * 4}, {orig_h * 4})"
                    )

                target_size = (orig_w * factor, orig_h * factor)
                if factor == 4:
                    final_rgb = upscaled_4x
                else:
                    final_rgb = upscaled_4x.resize(target_size, _LANCZOS)

                if has_alpha and alpha_channel is not None:
                    final_alpha = alpha_channel.resize(target_size, _LANCZOS)
                    final_img = final_rgb.convert("RGBA")
                    final_img.putalpha(final_alpha)
                else:
                    final_img = final_rgb

            self._result = final_img

        except Cancelled as exc:
            self._error = exc
        except UpscaleError as exc:
            self._error = exc
        except Exception as exc:
            self._error = UpscaleError(str(exc))
        finally:
            self._done_event.set()
            if on_done is not None:
                try:
                    on_done(self)
                except Exception:
                    pass


def command(
    binary_path: str,
    src: str,
    dst: str,
    factor: int,
    model: str = "realesrgan-x4plus",
) -> list[str]:
    if factor not in (2, 4):
        raise ValueError(f"factor must be 2 or 4, got {factor}")
    return [
        binary_path,
        "-i",
        src,
        "-o",
        dst,
        "-n",
        model,
        "-s",
        "4",
        "-g",
        "0",
        "-f",
        "png",
        "-v",
    ]


def start(
    image: Image.Image,
    factor: int,
    on_progress: Callable[[float], None] | None = None,
    on_done: Callable[[Job], None] | None = None,
) -> Job:
    if factor not in (2, 4):
        raise ValueError(f"factor must be 2 or 4, got {factor}")

    pixels = image.width * image.height
    if pixels > MAX_INPUT_PIXELS:
        mp = round(pixels / 1_000_000)
        raise UpscaleError(f"image too large to upscale ({mp} MP)")

    bin_path = binary()
    if bin_path is None:
        raise UpscaleError(f"{BINARY} is not installed")

    job = Job()
    thread = threading.Thread(
        target=job._run,
        args=(image, factor, bin_path, on_progress, on_done),
        daemon=True,
    )
    thread.start()
    return job
