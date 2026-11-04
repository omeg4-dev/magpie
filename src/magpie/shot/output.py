"""Screenshot output handling: filesystem storage, clipboard delivery, and notifications.

Handles mount detection for external storage, collision avoidance, atomic file writes,
Wayland clipboard synchronization, and desktop notifications.
"""

from __future__ import annotations

import os
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

__all__ = [
    "DEFAULT_ROOT",
    "FALLBACK_ROOT",
    "IGNORE_FLAG",
    "Saved",
    "UploadError",
    "target_path",
    "save_png",
    "copy_image",
    "deliver",
    "notify",
    "upload_catbox",
]

DEFAULT_ROOT = Path("/mnt/xv/Random/Screenshots/Screenshots")
FALLBACK_ROOT = Path.home() / "Pictures" / "Screenshots"
IGNORE_FLAG = Path("/dev/shm/ignore_clip_notify")


class UploadError(RuntimeError):
    """Raised when uploading a screenshot to Catbox fails."""


@dataclass(frozen=True)
class Saved:
    path: Path
    fell_back: bool  # True when DEFAULT_ROOT was unusable


def _open(path: Path | str) -> None:
    """Detach xdg-open to open the target file without blocking."""
    subprocess.Popen(
        ["xdg-open", str(path)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _is_usable(root: Path, is_mount) -> bool:
    """Check if root or any existing ancestor up to (not including) / is a mount point."""
    p = Path(root)
    root_anchor = Path(p.anchor) if p.is_absolute() else Path("/")
    while p != root_anchor:
        try:
            exists = p.exists()
        except OSError:
            exists = False
        if exists:
            try:
                if is_mount(p):
                    return True
            except OSError:
                pass
        parent = p.parent
        if parent == p:
            break
        p = parent
    return False


def target_path(
    now: datetime,
    *,
    root: Path = DEFAULT_ROOT,
    fallback: Path = FALLBACK_ROOT,
    is_mount=os.path.ismount,
) -> tuple[Path, bool]:
    """Compute the destination screenshot path, checking mount safety and collisions."""
    fell_back = not _is_usable(root, is_mount)
    base_dir = Path(fallback) if fell_back else Path(root)
    month_dir = base_dir / now.strftime("%Y-%m")
    stem = now.strftime("%d-%m-%Y--%H-%M-%S")
    candidate = month_dir / f"{stem}.png"
    if candidate.exists():
        i = 1
        while True:
            candidate = month_dir / f"{stem}-{i}.png"
            if not candidate.exists():
                break
            i += 1
    return candidate, fell_back


def save_png(png: bytes, path: Path) -> None:
    """Atomically write png bytes to path with 0o644 permissions."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.parent / f".{path.name}.tmp"
    try:
        tmp_path.write_bytes(png)
        os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, path)
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise


def copy_image(png: bytes, run=subprocess.run) -> None:
    """Send image/png bytes to Wayland clipboard using wl-copy."""
    try:
        IGNORE_FLAG.touch(exist_ok=True)
    except OSError:
        pass
    run(["wl-copy", "--type", "image/png"], input=png, check=True, timeout=10)


def deliver(
    png: bytes,
    store,
    *,
    now: datetime | None = None,
    root: Path = DEFAULT_ROOT,
    fallback: Path = FALLBACK_ROOT,
    is_mount=os.path.ismount,
    run=subprocess.run,
    play=None,
) -> Saved:
    """Save screenshot, copy to clipboard, index in store, and trigger audio feedback."""
    if now is None:
        now = datetime.now()
    target, fell_back = target_path(now, root=root, fallback=fallback, is_mount=is_mount)
    save_png(png, target)

    clip_err: Exception | None = None
    try:
        copy_image(png, run=run)
    except Exception as e:
        clip_err = e

    if store is not None:
        try:
            store.add_file(target, source="screenshot", mime="image/png")
        except Exception:
            pass

    if play is not None:
        try:
            play("copy")
        except Exception:
            pass

    if clip_err is not None:
        raise RuntimeError(f"saved to {target}, but the clipboard failed: {clip_err}") from clip_err

    return Saved(target, fell_back)


def upload_catbox(path: Path, run=subprocess.run) -> str:
    """Upload screenshot to Catbox and return the resulting URL."""
    cmd = [
        "curl",
        "-s",
        "--max-time",
        "60",
        "-F",
        "reqtype=fileupload",
        "-F",
        f"fileToUpload=@{path}",
        "https://catbox.moe/user/api.php",
    ]
    try:
        res = run(cmd, capture_output=True, text=True)
    except Exception as e:
        raise UploadError(str(e)) from e

    if res.returncode != 0:
        err = (res.stderr or res.stdout or f"curl exited with code {res.returncode}").strip()
        raise UploadError(err)

    out = (res.stdout or "").strip()
    if not out.startswith("http"):
        err = out or (res.stderr or "").strip() or "Empty response"
        raise UploadError(err)

    return out


def notify(saved: Saved, *, spawn=threading.Thread, run=subprocess.run) -> None:
    """Spawn a detached daemon thread to show a desktop notification with actions."""
    def _worker() -> None:
        try:
            if saved.fell_back:
                title = "Screenshot saved to Pictures"
                body = f"{saved.path.name}\nDrive is not mounted"
            else:
                title = "Screenshot saved"
                body = saved.path.name

            cmd = [
                "notify-send",
                "-a",
                "Screenshot",
                "-i",
                str(saved.path),
                "-t",
                "8000",
                "-h",
                "string:x-canonical-private-synchronous:screenshot",
                "-A",
                "open=Open",
                "-A",
                "upload=Upload",
                title,
                body,
            ]
            res = run(cmd, capture_output=True, text=True)
            stdout = res.stdout if isinstance(res.stdout, str) else (res.stdout.decode() if res.stdout else "")
            action = stdout.strip()

            if action == "open":
                _open(saved.path)
            elif action == "upload":
                run([
                    "notify-send",
                    "-a",
                    "Screenshot",
                    "-h",
                    "string:x-canonical-private-synchronous:screenshot",
                    "Uploading…",
                ])
                try:
                    url = upload_catbox(saved.path, run=run)
                except UploadError:
                    run([
                        "notify-send",
                        "-a",
                        "Screenshot",
                        "-u",
                        "critical",
                        "Upload failed",
                        "Still saved locally.",
                    ])
                    return

                try:
                    IGNORE_FLAG.touch(exist_ok=True)
                except OSError:
                    pass
                run(["wl-copy", url])
                run([
                    "notify-send",
                    "-a",
                    "Screenshot",
                    "-h",
                    "string:x-canonical-private-synchronous:screenshot",
                    "Link copied",
                    url,
                ])
        except Exception:
            pass

    t = spawn(target=_worker, daemon=True)
    t.start()
