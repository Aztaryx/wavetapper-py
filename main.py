#!/usr/bin/env python3
"""Play a song folder with the blocks flashing in sync.

    python main.py songs/wavetapper
    python main.py songs/demo --offset 0.05
    python main.py songs/demo --no-audio
"""
import argparse
import os
import shutil
import sys
import time

import config
from engine.grid import CLEAR, HIDE_CURSOR, HOME, RESET, SHOW_CURSOR, Grid
from engine.player import Player, SilentPlayer
from engine.timeline import Timeline, load_song

if os.name == "nt":
    os.system("")  # turns on ANSI escape codes in Windows terminals


class Stats:
    """Timing of the draw loop, to show whether the terminal is keeping up."""

    def __init__(self, fps):
        self.period = 1.0 / fps
        self.frames = 0
        self.intervals = []   # seconds between the starts of successive frames
        self.writes = []      # seconds each terminal write took
        self.duration = 0.0

    def report(self):
        if not self.intervals:
            return "stats: too short to measure"
        n = len(self.intervals)
        avg, worst = sum(self.intervals) / n, max(self.intervals)
        limit = 1.5 * self.period
        late = sum(1 for x in self.intervals if x > limit)
        lines = [
            f"drew {self.frames} frames in {self.duration:.1f} s: {self.frames / self.duration:.1f} fps "
            f"(target {1 / self.period:.0f})",
            f"frame to frame: avg {avg * 1000:.1f} ms, worst {worst * 1000:.0f} ms, "
            f"late (over {limit * 1000:.0f} ms): {late} ({100 * late / n:.1f}%)",
        ]
        if self.writes:
            w_avg = sum(self.writes) / len(self.writes)
            lines.append(f"terminal writes: {len(self.writes)}, avg {w_avg * 1000:.2f} ms, "
                         f"worst {max(self.writes) * 1000:.0f} ms")
            if late / n > 0.05 and w_avg > 0.3 * self.period:
                lines.append("-> the terminal is the slow part. Try Windows Terminal or a plain PowerShell "
                             "window instead of the VS Code panel, a smaller window, or --fps 20.")
        return "\n".join(lines)


def run(timeline, grid, player, offset, fps, out=sys.stdout, size_fn=shutil.get_terminal_size):
    """Main loop. Time comes from the audio position, never from a frame counter."""
    period = 1.0 / fps
    stats = Stats(fps)
    size = tuple(size_fn())
    last_size_check = time.perf_counter()
    prev_lit = None          # what the screen currently shows; None = needs a full redraw
    last_msg = None          # the "too small" message, so it is only written once

    out.write(HIDE_CURSOR + CLEAR)
    out.flush()
    try:
        player.start()
        loop_start = prev_start = time.perf_counter()
        while player.active():
            started = time.perf_counter()
            stats.intervals.append(started - prev_start) if stats.frames else None
            prev_start = started

            if started - last_size_check > 0.25:  # asking the terminal for its size is not free
                last_size_check = started
                new_size = tuple(size_fn())
                if new_size != size:
                    size, prev_lit, last_msg = new_size, None, None
                    out.write(CLEAR)

            lit = timeline.lit_at(player.position() - offset)
            if not grid.fits(size):
                data = grid.frame(lit, size) if last_msg is None else ""
                last_msg, prev_lit = data or last_msg, None
            elif prev_lit is None:
                data = grid.frame(lit, size)     # full draw: start, or after a resize
                prev_lit, last_msg = lit, None
            else:
                data = grid.update(prev_lit, lit, size)   # only the blocks that changed
                prev_lit = lit

            if data:
                w0 = time.perf_counter()
                out.write(data)
                out.flush()
                stats.writes.append(time.perf_counter() - w0)
            stats.frames += 1

            time.sleep(max(0.0, period - (time.perf_counter() - started)))
        stats.duration = time.perf_counter() - loop_start
    except KeyboardInterrupt:
        stats.duration = time.perf_counter() - loop_start
    finally:
        player.stop()
        out.write(RESET + SHOW_CURSOR + CLEAR + HOME)
        out.flush()
    return stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("song", help="song folder, e.g. songs/wavetapper")
    ap.add_argument("--offset", type=float, help="override offset (seconds) from song.json")
    ap.add_argument("--fps", type=int, default=config.FPS)
    ap.add_argument("--no-audio", action="store_true", help="run on a wall clock, no sound")
    ap.add_argument("--stats", action="store_true", help="print how smoothly the drawing ran, afterwards")
    args = ap.parse_args()

    song = load_song(args.song)
    if not song.blocks_path.exists():
        sys.exit(f"{song.blocks_path} not found. Run the analyzer, or try songs/demo.")
    timeline = Timeline.load(song.blocks_path, song.num_blocks)
    grid = Grid(song.cols, song.rows, song.palette)
    offset = song.offset if args.offset is None else args.offset

    if args.no_audio:
        player = SilentPlayer(timeline.duration + 0.5 + offset)
    else:
        if not song.audio.exists():
            sys.exit(f"audio file not found: {song.audio}\nPut your own audio there, or use --no-audio.")
        player = Player(song.audio)

    stats = run(timeline, grid, player, offset, args.fps)
    if args.stats:
        print(stats.report())


if __name__ == "__main__":
    main()
