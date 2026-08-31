"""Write the two sounds the viewer makes.

They are generated rather than sampled so they can be tuned in one place and
so the repository carries no borrowed audio. Run this after changing anything
here and commit the result:

    python3 tools/make_sounds.py

Opening makes a **click** — a few milliseconds of noise under a steep decay,
the sound of a switch rather than of a notification. It happens every time a
window appears, so it has to be the kind of sound you stop hearing.

Copying makes one short **note**, because it is the thing you actually asked
for and the only confirmation you get: a sine with a quiet second harmonic
under a fast decay, with a few milliseconds of attack so the speaker is never
asked to start at full amplitude.
"""

from __future__ import annotations

import math
import random
import struct
import wave
from pathlib import Path

RATE = 48_000
OUT = Path(__file__).resolve().parent.parent / "src" / "magpie" / "assets"

#: Quiet. This plays every time a window opens, and anything louder becomes
#: the reason the sound gets turned off a week later.
LEVEL = 0.22

#: The click is quieter still, and it is the one you hear most.
CLICK_LEVEL = 0.09


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


def click(seconds: float = 0.007, decay: float = 0.0013, hz: float = 2000.0) -> list[float]:
    """A tick: noise and one high cycle, gone almost before it started.

    The noise is what makes it read as a physical click rather than a beep;
    the tone under it keeps it from sounding like a fault. Seeded, so the file
    is the same every time this is run.
    """
    noise = random.Random(31)
    frames = int(RATE * seconds)
    out = []
    for i in range(frames):
        at = i / RATE
        envelope = math.exp(-at / decay)
        body = 0.7 * noise.uniform(-1.0, 1.0) + 0.3 * math.sin(2 * math.pi * hz * at)
        out.append(body * envelope * CLICK_LEVEL)
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
    # Opening: a click. The window is already there; this is only the edge of
    # it arriving, and anything more is a jingle you will want gone by Friday.
    write("open", click())
    # Copying: one note, landing. Higher and shorter, so it reads as "done"
    # rather than as another window appearing.
    write("copy", tone(987.77, 932.33, 0.07, decay=0.035, harmonic=0.3))


if __name__ == "__main__":
    main()
