"""Generate songs/demo: a 12 s click track plus a matching blocks.json.

Every block flash starts with a click (pitch depends on the block), so you can
check by ear that flashes and sound line up. Run from the project root:

    python tools/make_demo.py
"""
import json
import math
import struct
import wave
from pathlib import Path

RATE = 44100
BEAT = 0.5      # 120 BPM
BEATS = 24      # 12 seconds


def demo_events():
    """Hand-made timing: one block per beat, plus a few edge cases."""
    ev = [{"block": i % 16, "start": i * BEAT, "end": i * BEAT + 0.25} for i in range(BEATS)]
    ev.append({"block": 5, "start": 2.0, "end": 4.0})      # long, overlaps block 5's own beat at 2.5
    for b in (1, 5, 9, 13):                                # a column lit together
        ev.append({"block": b, "start": 10.0, "end": 10.4})
    ev.append({"block": 15, "start": 11.75, "end": 11.78})  # 30 ms flash: below the ~35 ms redraw limit
    return sorted(ev, key=lambda e: (e["start"], e["block"]))


def write_click_track(path, events, length):
    buf = [0.0] * int(RATE * length)
    for e in events:
        freq = 300 + 60 * e["block"]
        start = int(e["start"] * RATE)
        for n in range(int(0.04 * RATE)):
            if start + n < len(buf):
                buf[start + n] += 0.4 * math.sin(2 * math.pi * freq * n / RATE) * math.exp(-n / (0.01 * RATE))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1, min(1, s)) * 32767)) for s in buf))


def main():
    folder = Path(__file__).resolve().parents[1] / "songs" / "demo"
    folder.mkdir(parents=True, exist_ok=True)
    events = demo_events()

    lines = ",\n".join("  " + json.dumps({k: round(v, 3) if isinstance(v, float) else v for k, v in e.items()})
                       for e in events)
    (folder / "blocks.json").write_text("[\n" + lines + "\n]\n")
    (folder / "song.json").write_text(json.dumps({
        "title": "Demo click track", "artist": "-", "audio": "audio.wav",
        "offset": 0.0, "grid": {"cols": 4, "rows": 4},
    }, indent=2) + "\n")
    write_click_track(folder / "audio.wav", events, BEATS * BEAT + 0.5)
    print(f"wrote {folder}/ (blocks.json, song.json, audio.wav)")


if __name__ == "__main__":
    main()
