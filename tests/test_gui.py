"""Drives the real Tk window with simulated mouse events. Needs a display (skipped without one).

On a headless Linux box:  xvfb-run -a -s "-screen 0 1280x1024x24" python -m pytest tests/test_gui.py
"""
import json
import time

import pytest

tk = pytest.importorskip("tkinter")

from engine.timeline import Timeline
from tools.gui import App, xterm_hex
from tools.make_demo import demo_events
from test_pipeline import CELL_H, CELL_W, FPS, block_origin, make_video


@pytest.fixture
def root():
    try:
        r = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    r.geometry("+0+0")
    yield r
    try:
        r.destroy()
    except tk.TclError:
        pass


def pump(root, seconds=0.05):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.005)


def mouse(app, kind, vx, vy):
    """Send a mouse event at video-pixel position (vx, vy)."""
    x, y = int(vx * app.zoom), int(vy * app.zoom)
    if kind == "press":
        app.canvas.event_generate("<Button-1>", x=x, y=y)
    elif kind == "move":
        app.canvas.event_generate("<B1-Motion>", x=x, y=y, state=0x100)
    elif kind == "release":
        app.canvas.event_generate("<ButtonRelease-1>", x=x, y=y)
    elif kind == "right":
        app.canvas.event_generate("<Button-3>", x=x, y=y)
    root_update(app)


def root_update(app):
    app.root.update()


def drag(app, x0, y0, x1, y1):
    mouse(app, "press", x0, y0)
    mouse(app, "move", (x0 + x1) / 2, (y0 + y1) / 2)
    mouse(app, "move", x1, y1)
    mouse(app, "release", x1, y1)


@pytest.fixture
def app(root, tmp_path):
    events = demo_events()
    video = tmp_path / "synthetic.avi"
    make_video(video, Timeline(events, 16), 12.5)
    song = tmp_path / "song"
    song.mkdir()
    (song / "song.json").write_text(json.dumps({"title": "synthetic"}))
    a = App(root, song, video)
    pump(root)
    return a


def test_xterm_colours():
    assert xterm_hex(196) == "#ff0000" and xterm_hex(46) == "#00ff00" and xterm_hex(244) == "#808080"


def test_place_all_boxes_analyse_and_save(app, root):
    # Draw a box inside each block. The selected block advances by itself after each one.
    for b in range(16):
        assert app.block == b
        ox, oy = block_origin(b)
        drag(app, ox + 20, oy + 20, ox + CELL_W - 20, oy + CELL_H - 20)
        assert app.boxes[b] is not None
    assert app.block == 15  # nothing left to advance to

    app.analyze_clicked()
    deadline = time.time() + 30
    while app.analysing and time.time() < deadline:
        pump(root, 0.1)
    assert not app.analysing and app.per_block is not None

    truth = Timeline(demo_events(), 16)
    for b in range(16):
        expected = [(s, e) for s, e in zip(truth._starts[b], truth._ends[b]) if e - s > 0.1]
        got = app.per_block[b]
        assert len(got) == len(expected), f"block {b}: {expected} vs {got}"
        for (gs, ge), (es, ee) in zip(got, expected):
            assert abs(gs - es) <= 1.5 / FPS and abs(ge - ee) <= 1.5 / FPS

    # Regions were auto-saved, and the timing strip drew something for each lit block.
    saved = json.loads(app.song.regions_path.read_text())
    assert len(saved) == 16
    assert len(app.roll.find_all()) > 16 * 2

    # On screen: block 0 is lit at frame 1 (outline thick), dim at frame 10.
    app.show(1)
    assert int(float(app.canvas.itemcget(app.rects[0], "width"))) == 4
    app.show(10)
    assert int(float(app.canvas.itemcget(app.rects[0], "width"))) == 2

    # Changing only the thresholds re-detects from memory, with no new video read.
    key = app.samples_key
    app.on_var.set("0.7")
    app.analyze_clicked()
    assert not app.analysing and app.samples_key == key

    # The "dim frame" box: Here fills in the current time, and analysing with it works.
    app.show(0)
    app.use_this_frame_as_dim()
    assert app.dim_var.get() == "0.00"
    app.analyze_clicked()
    assert not app.analysing and app.samples_key == key and sum(len(v) for v in app.per_block) > 0
    app.dim_var.set("")

    app.save_blocks_clicked()
    assert json.loads(app.song.blocks_path.read_text())


def test_move_resize_delete_and_click(app, root):
    ox, oy = block_origin(0)
    drag(app, ox + 20, oy + 20, ox + 100, oy + 80)
    x, y, w, h = app.boxes[0]
    assert (round(w), round(h)) == (80, 60) and app.block == 1

    # A plain click on empty space neither creates a box nor changes the selected block.
    mouse(app, "press", 600, 450)
    mouse(app, "release", 600, 450)
    assert app.boxes[1] is None and app.block == 1

    # Move: press inside box 0 (selects it) and drag by (+30, +10).
    mouse(app, "press", ox + 60, oy + 50)
    mouse(app, "move", ox + 75, oy + 55)
    mouse(app, "move", ox + 90, oy + 60)
    mouse(app, "release", ox + 90, oy + 60)
    nx, ny, nw, nh = app.boxes[0]
    assert app.block == 0 and abs(nx - (x + 30)) < 2 and abs(ny - (y + 10)) < 2 and (round(nw), round(nh)) == (80, 60)

    # Resize: grab the bottom-right corner and pull it 20 px further.
    cx, cy = nx + nw, ny + nh
    mouse(app, "press", cx, cy)
    mouse(app, "move", cx + 10, cy + 10)
    mouse(app, "move", cx + 20, cy + 20)
    mouse(app, "release", cx + 20, cy + 20)
    rx, ry, rw, rh = app.boxes[0]
    assert abs(rx - nx) < 2 and abs(rw - (nw + 20)) < 3 and abs(rh - (nh + 20)) < 3

    # Boxes cannot leave the frame.
    mouse(app, "press", rx + 10, ry + 10)
    mouse(app, "move", 400, 300)
    mouse(app, "move", 5000 / app.zoom * app.zoom, 5000 / app.zoom * app.zoom)
    mouse(app, "release", 640, 480)
    bx, by, bw, bh = app.boxes[0]
    assert bx + bw <= app.vw + 0.5 and by + bh <= app.vh + 0.5

    # Right-click deletes.
    mouse(app, "right", bx + bw / 2, by + bh / 2)
    assert app.boxes[0] is None


def test_playback_advances_and_stops(app, root):
    start = app.cur
    app.toggle_play()
    pump(root, 0.5)
    app.toggle_play()
    assert app.cur > start
    stopped_at = app.cur
    pump(root, 0.2)
    assert app.cur == stopped_at
    app.step(5)
    assert app.cur == stopped_at + 5
    app.show(app.nframes + 100)
    assert app.cur == app.nframes - 1


def test_existing_regions_and_blocks_are_loaded(root, tmp_path):
    song = tmp_path / "song"
    song.mkdir()
    (song / "song.json").write_text("{}")
    (song / "regions.json").write_text(json.dumps([{"block": 3, "x": 10, "y": 20, "w": 30, "h": 40}]))
    (song / "blocks.json").write_text(json.dumps([{"block": 3, "start": 1.0, "end": 2.0}]))
    app = App(root, song)
    assert app.boxes[3] == (10.0, 20.0, 30.0, 40.0) and app.boxes[0] is None
    assert app.timeline.is_lit(3, 1.5)


# ---------- playback performance ----------

def test_slider_echo_does_not_reshow_frames(app, root):
    """Tk delivers the slider's callback after scale.set(). It used to re-show (seek and decode) every frame."""
    calls = []
    original = app.show
    app.show = lambda i: (calls.append(i), original(i))[1]
    for i in range(10, 20):
        app.show(i)
        pump(root, 0.02)
    assert calls == list(range(10, 20))


def test_unchanged_overlay_costs_no_tk_calls(app, root):
    for b in range(4):
        app.boxes[b] = (10 + 100 * b, 10, 60, 60)
    app.update_overlay()
    n = []
    real = app.canvas.itemconfig
    app.canvas.itemconfig = lambda *a, **k: (n.append(1), real(*a, **k))[1]
    app.update_overlay()
    assert n == []                       # nothing changed, nothing touched
    app.boxes[0] = (20, 10, 60, 60)
    app.update_overlay()
    assert 0 < len(n) < 10               # only the one box that moved (plus its handles)


def test_playback_runs_in_real_time(app, root):
    start = app.cur
    started = time.perf_counter()
    app.toggle_play()
    pump(root, 1.0)
    app.toggle_play()
    wall = time.perf_counter() - started
    played = (app.cur - start) / app.fps
    assert 0.6 * wall < played < 1.3 * wall, f"played {played:.2f}s of video in {wall:.2f}s"
    assert app.time_label.cget("text").strip().startswith(f"{app.cur / app.fps:.2f}")  # label synced on pause
