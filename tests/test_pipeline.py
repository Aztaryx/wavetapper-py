import io
import json

import cv2
import numpy as np
import pytest

from engine.grid import HIDE_CURSOR, SHOW_CURSOR, Grid
from engine.player import SilentPlayer
from engine.timeline import Timeline, load_song
from tools import analyze
from tools.calibrate import shrink_box
from tools.make_demo import demo_events
from tools.preview import draw_overlay


# ---------- timeline ----------

def test_timeline_boundaries_and_merge():
    tl = Timeline([
        {"block": 0, "start": 1.0, "end": 2.0},
        {"block": 0, "start": 1.5, "end": 3.0},   # overlaps -> merged to 1.0-3.0
        {"block": 1, "start": 5.0, "end": 5.5},
    ], 4)
    assert tl.lit_at(0.99) == [False] * 4
    assert tl.is_lit(0, 1.0)             # start is inclusive
    assert tl.is_lit(0, 2.5)             # inside the merged part
    assert not tl.is_lit(0, 3.0)         # end is exclusive
    assert tl.lit_at(5.2) == [False, True, False, False]
    assert tl.duration == 5.5


def test_timeline_rejects_bad_entries():
    with pytest.raises(ValueError):
        Timeline([{"block": 4, "start": 0, "end": 1}], 4)
    with pytest.raises(ValueError):
        Timeline([{"block": 0, "start": 1, "end": 1}], 4)


def test_song_defaults(tmp_path):
    (tmp_path / "song.json").write_text(json.dumps({"palette": [{"dim": 1, "lit": 2}]}))
    song = load_song(tmp_path)
    assert song.num_blocks == 16 and len(song.palette) == 16
    assert song.palette[0] == (1, 2)


# ---------- grid ----------

def test_grid_lit_and_dim_exact():
    pal = [(10 + i, 100 + i) for i in range(16)]
    grid = Grid(4, 4, pal)
    lit = [False] * 16
    lit[5] = True
    frame = grid.frame(lit, (80, 24))
    assert "\033[38;5;105m" in frame and "\033[38;5;15m" not in frame
    assert "\033[38;5;14m" in frame           # block 4 stays dim
    # centred: width 14 in 80 cols -> left col 34; height 11 in 24 rows -> top row 7
    assert frame.startswith("\033[7;34H")
    assert "Need 14x11 (have 30x5)" in grid.frame(lit, (30, 5))


# ---------- main loop ----------

def test_main_loop_runs_and_restores_terminal():
    import main
    tl = Timeline(demo_events(), 16)
    grid = Grid(4, 4, [(1, 2)] * 16)
    out = io.StringIO()
    main.run(tl, grid, SilentPlayer(0.3), 0.0, 30, out=out, size_fn=lambda: (80, 24))
    text = out.getvalue()
    assert text.startswith(HIDE_CURSOR)
    assert text.rstrip().endswith("\033[H") and SHOW_CURSOR in text
    assert "\033[38;5;2m" in text  # block 0 lit at t=0


# ---------- analysis maths ----------

def test_hysteresis_ignores_flicker():
    v = np.array([0, 0.6, 0.45, 0.55, 0.4, 0.35, 0.2, 0.0])
    # on at 0.6, stays on while >= 0.3, off at 0.2
    assert hysteresis_list(v) == [0, 1, 1, 1, 1, 1, 0, 0]


def hysteresis_list(v):
    return analyze.hysteresis(v, 0.5, 0.3).astype(int).tolist()


def test_state_to_intervals_min_length_and_end_of_video():
    state = np.array([0, 1, 0, 0, 1, 1, 1, 0, 1, 1], dtype=bool)  # 1 frame, 3 frames, 2 frames (to the end)
    ivs = analyze.state_to_intervals(state, 10, 0.15)
    assert ivs == [(0.4, 0.7), (0.8, 1.0)]


def test_normalise_marks_dead_blocks():
    scores = np.zeros((100, 2))
    scores[::10, 0] = 80.0     # block 0 has a real range
    scores[::10, 1] = 3.0      # block 1 only noise
    norm, ref, usable = analyze.normalise(scores, 99, 15)
    assert usable.tolist() == [True, False]
    assert norm[:, 1].max() == 0.0


def test_shrink_box():
    assert shrink_box(100, 100, 50, 50, 0.2) == (105, 105, 40, 40)


# ---------- end to end on a synthetic video ----------

FPS = 30
CELL_W, CELL_H = 120, 100


def block_origin(b):
    return (b % 4) * 150 + 20, (b // 4) * 110 + 20


def lit_bgr(b):
    return (60 + (b * 37) % 180, 255 - (b * 53) % 120, 100 + (b * 71) % 150)


def make_video(path, timeline, seconds):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), FPS, (640, 480))
    assert writer.isOpened()
    rng = np.random.default_rng(0)
    for i in range(int(seconds * FPS)):
        frame = np.full((480, 640, 3), 15, np.uint8)
        lit = timeline.lit_at(i / FPS)
        for b in range(16):
            x, y = block_origin(b)
            colour = lit_bgr(b) if lit[b] else (30, 30, 30)
            frame[y:y + CELL_H, x:x + CELL_W] = colour
        noise = rng.integers(-4, 5, frame.shape)
        writer.write(np.clip(frame.astype(int) + noise, 0, 255).astype(np.uint8))
    writer.release()


def test_end_to_end_matches_ground_truth(tmp_path):
    events = demo_events()
    truth_tl = Timeline(events, 16)

    video = tmp_path / "synthetic.avi"
    make_video(video, truth_tl, 12.5)

    song_dir = tmp_path / "song"
    song_dir.mkdir()
    (song_dir / "song.json").write_text(json.dumps({"title": "synthetic"}))
    regions = [(block_origin(b)[0] + 20, block_origin(b)[1] + 20, CELL_W - 40, CELL_H - 40) for b in range(16)]
    (song_dir / "regions.json").write_text(json.dumps(
        [{"block": b, "x": x, "y": y, "w": w, "h": h} for b, (x, y, w, h) in enumerate(regions)]))

    analyze.run(video, song_dir, 0.5, 0.3, 0.04, 99.0, 15.0, False)

    found = json.loads((song_dir / "blocks.json").read_text())
    found_tl = Timeline(found, 16)

    # Truth, merged, minus the 30 ms flash (shorter than one-and-a-bit frames; it must be dropped).
    expected = {b: [(s, e) for s, e in zip(truth_tl._starts[b], truth_tl._ends[b]) if e - s > 0.1] for b in range(16)}
    for b in range(16):
        got = list(zip(found_tl._starts[b], found_tl._ends[b]))
        assert len(got) == len(expected[b]), f"block {b}: expected {expected[b]}, got {got}"
        for (gs, ge), (es, ee) in zip(got, expected[b]):
            assert abs(gs - es) <= 1.5 / FPS and abs(ge - ee) <= 1.5 / FPS, f"block {b}: {(gs, ge)} vs {(es, ee)}"

    # Second run reads the cache instead of the video and gives the same answer.
    cache = song_dir / "samples.npz"
    stamp = cache.stat().st_mtime_ns
    analyze.run(video, song_dir, 0.5, 0.3, 0.04, 99.0, 15.0, False)
    assert cache.stat().st_mtime_ns == stamp
    assert json.loads((song_dir / "blocks.json").read_text()) == found
    assert (song_dir / "blocks.json.bak").exists()


# ---------- preview overlay ----------

def test_preview_overlay_draws():
    frame = np.zeros((200, 300, 3), np.uint8)
    regions = [(50 + 40 * i, 80, 30, 30) for i in range(4)]
    out = draw_overlay(frame, regions, [True, False, False, False], 2, 1.5)
    assert out.any()


# ---------- baseline: blocks that are lit most of the time ----------

def _mostly_lit_samples(frames=300):
    rng = np.random.default_rng(1)
    s = np.full((frames, 2, 3), 30.0, np.float32)
    s[60:270, 0] = (200, 200, 50)    # block 0 is lit for 70% of the video (2.0 s to 9.0 s at 30 fps)
    s[100:110, 1] = (50, 200, 200)   # block 1 flashes once (3.33 s to 3.67 s)
    return s + rng.normal(0, 2, s.shape).astype(np.float32)


def test_mostly_lit_block_is_not_detected_backwards():
    # A median baseline would be the lit colour here and report the dim parts (0-2 s, 9-10 s) as flashes.
    per_block, info = analyze.detect(_mostly_lit_samples(), 30, 0.5, 0.3, 0.04)
    assert len(per_block[0]) == 1
    assert per_block[0][0] == pytest.approx((2.0, 9.0), abs=1 / 30)
    assert per_block[1][0] == pytest.approx((100 / 30, 110 / 30), abs=1 / 30)
    assert info[0]["usable"] and info[1]["usable"]


def test_dim_at_override_matches_and_clamps():
    s = _mostly_lit_samples()
    auto, _ = analyze.detect(s, 30, 0.5, 0.3, 0.04)
    manual, _ = analyze.detect(s, 30, 0.5, 0.3, 0.04, dim_at=0.0)      # every block is dim at 0 s here
    assert manual[0][0] == pytest.approx(auto[0][0], abs=1 / 30)
    analyze.detect(s, 30, 0.5, 0.3, 0.04, dim_at=9999.0)               # past the end: clamped, no crash
