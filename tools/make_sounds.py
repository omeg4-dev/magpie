"""Write the two sounds the viewer makes.

They are generated rather than sampled so they can be tuned in one place and
so the repository carries no borrowed audio. Run this after changing anything
here and commit the result:

    python3 tools/make_sounds.py

Both are the same shape — a sine with a quiet second harmonic under a fast
exponential decay, and a few milliseconds of attack so the speaker is never
asked to start at full amplitude, which is what a click is. Short, low, and
pitched well above the desk noise: a cue, not a jingle.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

RATE = 48_000
OUT = Path(__file__).resolve().parent.parent / "src" / "magpie" / "assets"

#: Quiet. This plays every time a window opens, and anything louder becomes
#: the reason the sound gets turned off a week later.
LEVEL = 0.22


def tone(start: float, end: float, seconds: float, decay: float,
         harmonic: float = 0.18) -> list[float]:
    """A glide from `start` Hz to `end` Hz, dying away over `decay` seconds."""
    frames = int(RATE * seconds)
    attack = int(RATE * 0.004)
    out = []
    phase = 0.0
    for i in range(frames):
        along = i / frames
        hz = start + (end - start) * along
        phase += 2 * math.pi * hz / RATE
        value = math.sin(phase) + harmonic * math.sin(2 * phase)
        envelope = math.exp(-(i / RATE) / decay)
        if i < attack:
            envelope *= i / attack
        out.append(value * envelope * LEVEL)
    return out


def write(name: str, samples: list[float]) -> Path:
    path = OUT / f"{name}.wav"
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(RATE)
        wav.writeframes(b"".join(
            struct.pack("<h", max(-32767, min(32767, int(s * 32767))))
            for s in samples))
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    # Opening: a short rise, the sound of something coming towards you.
    write("open", tone(523.25, 783.99, 0.11, decay=0.075))
    # Copying: one note, landing. Higher and shorter, so it reads as "done"
    # rather than as another window appearing.
    write("copy", tone(987.77, 932.33, 0.07, decay=0.035, harmonic=0.3))


if __name__ == "__main__":
    main()
