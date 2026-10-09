"""gui: place the detector boxes on the video by hand, run the analysis, check the result.

    python tools/cli.py gui [video] [--song songs/wavetapper]

Uses Tkinter, which ships with Python, so there is nothing extra to install.
"""
import json
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `engine` and `tools` import when run directly

import cv2  # noqa: E402

from engine.timeline import Timeline, load_song  # noqa: E402
from tools import analyze  # noqa: E402
from tools.common import read_regions_file, save_regions  # noqa: E402

HANDLE = 8       # corner grab distance, in screen pixels
MIN_BOX = 4      # smallest allowed box, in video pixels
ROW_H = 11       # height of one block's row in the timing strip
ROLL_LEFT = 24   # room for block numbers at the left of the timing strip

_STD16 = ["#000000", "#800000", "#008000", "#808000", "#000080", "#800080", "#008080", "#c0c0c0",
          "#808080", "#ff0000", "#00ff00", "#ffff00", "#0000ff", "#ff00ff", "#00ffff", "#ffffff"]


def xterm_hex(code):
    """256-colour terminal code -> '#rrggbb', so the GUI uses the same colours as the terminal."""
    if code < 16:
        return _STD16[code]
    if code < 232:
        levels = [0, 95, 135, 175, 215, 255]
        c = code - 16
        return "#%02x%02x%02x" % (levels[c // 36], levels[(c // 6) % 6], levels[c % 6])
    v = 8 + 10 * (code - 232)
    return "#%02x%02x%02x" % (v, v, v)


def text_colour_for(hex_colour):
    r, g, b = (int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return "black" if 0.299 * r + 0.587 * g + 0.114 * b > 140 else "white"


class App:
    def __init__(self, root, song_dir, video=None):
        self.root = root
        self.song = load_song(song_dir)
        self.n = self.song.num_blocks
        self.colours = [xterm_hex(lit) for _, lit in self.song.palette]

        self.boxes = [None] * self.n          # (x, y, w, h) in video pixels, or None
        self.block = 0                        # selected block
        self.drag = None                      # current mouse drag, see on_press
        self.cap = None
        self.video = None
        self.playing = False
        self.cur = 0                          # index of the frame on screen
        self._drawn = [None] * self.n         # what each box currently looks like on the canvas
        self._handles_drawn = None
        self._ui_t = 0.0                      # last time the slider/label were refreshed
        self._echo = -1                       # last slider value we set ourselves
        self.read_pos = 0                     # index of the next frame cap.read() returns

        self.samples = self.samples_key = self.samples_fps = None
        self.per_block = None                 # detected [(start, end), ...] for each block
        self.infos = {}
        self.timeline = None
        self.analysing = False
        self.q = queue.Queue()

        self._build_ui()
        self._load_existing()
        if video:
            self.open_video(video)

    # ------------------------------------------------------------ layout

    def _build_ui(self):
        r = self.root
        r.title(f"Wavetapper analyzer: {self.song.folder}")
        sw, sh = r.winfo_screenwidth(), r.winfo_screenheight()
        self.max_w = max(320, min(1000, sw - 330))
        self.max_h = max(180, min(600, sh - 380))

        left = ttk.Frame(r)
        left.grid(row=0, column=0, sticky="n", padx=6, pady=6)
        right = ttk.Frame(r)
        right.grid(row=0, column=1, sticky="n", padx=(0, 6), pady=6)

        # video
        self.canvas = tk.Canvas(left, width=640, height=360, bg="black", highlightthickness=0, cursor="crosshair")
        self.canvas.pack()
        self.img_item = self.canvas.create_image(0, 0, anchor="nw")
        self.rects = [self.canvas.create_rectangle(0, 0, 0, 0, state="hidden") for _ in range(self.n)]
        self.labels = [self.canvas.create_text(0, 0, anchor="nw", state="hidden", font=("TkDefaultFont", 10, "bold"))
                       for _ in range(self.n)]
        self.handles = [self.canvas.create_rectangle(0, 0, 0, 0, state="hidden", fill="white", outline="black")
                        for _ in range(4)]
        self.canvas.bind("<Button-1>", self.on_press)
        self.canvas.bind("<B1-Motion>", self.on_drag)
        self.canvas.bind("<ButtonRelease-1>", self.on_release)
        self.canvas.bind("<Button-3>", self.on_right_click)

        # transport
        bar = ttk.Frame(left)
        bar.pack(fill="x", pady=(4, 0))
        self.play_btn = ttk.Button(bar, text="Play", width=7, command=self.toggle_play)
        self.play_btn.pack(side="left")
        self.scale = tk.Scale(bar, from_=0, to=1, orient="horizontal", showvalue=0, command=self.on_scale,
                              length=300)
        self.scale.pack(side="left", fill="x", expand=True, padx=6)
        self.full_rate = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="every frame", variable=self.full_rate).pack(side="left")
        self.time_label = ttk.Label(bar, text="--", width=24)
        self.time_label.pack(side="left")

        # timing strip
        self.roll = tk.Canvas(left, width=640 + ROLL_LEFT, height=self.n * ROW_H, bg="#111", highlightthickness=0)
        self.roll.pack(pady=(6, 0))
        self.roll.bind("<Button-1>", self.on_roll)
        self.roll.bind("<B1-Motion>", self.on_roll)
        self.playhead = None

        # right panel
        ttk.Button(right, text="Open video…", command=self.choose_video).pack(fill="x")
        self.video_label = ttk.Label(right, text="no video loaded", wraplength=230)
        self.video_label.pack(fill="x", pady=(2, 8))

        ttk.Label(right, text="Block to place (numbered left to right,\ntop to bottom):").pack(anchor="w")
        grid = ttk.Frame(right)
        grid.pack(pady=4)
        self.block_var = tk.IntVar(value=0)
        self.block_btns = []
        cols = self.song.cols
        for b in range(self.n):
            btn = tk.Radiobutton(grid, variable=self.block_var, value=b, indicatoron=False, width=6, height=2,
                                 bg=self.colours[b], fg=text_colour_for(self.colours[b]),
                                 selectcolor=self.colours[b], activebackground=self.colours[b],
                                 command=self.on_select_block)
            btn.grid(row=b // cols, column=b % cols, padx=1, pady=1)
            self.block_btns.append(btn)

        form = ttk.Frame(right)
        form.pack(fill="x", pady=(10, 0))
        self.on_var, self.off_var, self.len_var = tk.StringVar(value="0.5"), tk.StringVar(value="0.3"), tk.StringVar(value="0.04")
        self.dim_var = tk.StringVar(value="")
        for i, (label, var) in enumerate((("on threshold", self.on_var), ("off threshold", self.off_var),
                                          ("min length (s)", self.len_var), ("dim frame (s)", self.dim_var))):
            ttk.Label(form, text=label).grid(row=i, column=0, sticky="w")
            ttk.Entry(form, textvariable=var, width=7).grid(row=i, column=1, padx=6, pady=1)
        ttk.Button(form, text="Here", width=5, command=self.use_this_frame_as_dim).grid(row=3, column=2)

        self.analyze_btn = ttk.Button(right, text="Analyze", command=self.analyze_clicked)
        self.analyze_btn.pack(fill="x", pady=(10, 2))
        ttk.Button(right, text="Save blocks.json", command=self.save_blocks_clicked).pack(fill="x", pady=2)
        ttk.Button(right, text="Save regions", command=self.save_regions_clicked).pack(fill="x", pady=2)
        self.progress = ttk.Progressbar(right, mode="determinate")
        self.progress.pack(fill="x", pady=(8, 2))
        self.status = ttk.Label(right, text="Open a video, then drag a box on each block.", wraplength=230,
                                justify="left")
        self.status.pack(fill="x")

        ttk.Label(right, justify="left", foreground="#666", wraplength=230, text=(
            "Drag on empty space: draw the selected block's box.\n"
            "Drag a box to move it, drag a corner to resize.\n"
            "Right-click or Delete: remove a box.\n"
            "Space: play/pause. Left/Right: step a frame (Shift: 1 s).\n"
            "Keep each box inside its block, away from the edges.\n"
            "Dim frame: leave blank. Only if a block looks backwards, scrub to a moment when every cube "
            "is dim, press Here, then Analyze.")).pack(fill="x", pady=(10, 0))

        r.bind("<space>", lambda e: self._key(self.toggle_play))
        r.bind("<Left>", lambda e: self._key(lambda: self.step(-1)))
        r.bind("<Right>", lambda e: self._key(lambda: self.step(1)))
        r.bind("<Shift-Left>", lambda e: self._key(lambda: self.step(-self._fps_int())))
        r.bind("<Shift-Right>", lambda e: self._key(lambda: self.step(self._fps_int())))
        r.bind("<Delete>", lambda e: self._key(self.delete_selected))
        r.protocol("WM_DELETE_WINDOW", self.close)
        self._refresh_block_buttons()

    def _key(self, fn):
        """Run a hotkey unless the user is typing in a text box."""
        if isinstance(self.root.focus_get(), (tk.Entry, ttk.Entry)):
            return
        fn()

    def _fps_int(self):
        return max(1, int(round(self.fps))) if self.cap else 1

    # ------------------------------------------------------------ video

    def choose_video(self):
        path = filedialog.askopenfilename(title="Choose the video", filetypes=[
            ("Video", "*.mp4 *.mkv *.webm *.avi *.mov"), ("All files", "*.*")])
        if path:
            self.open_video(path)

    def open_video(self, path):
        cap = cv2.VideoCapture(str(path))
        if not cap.isOpened():
            messagebox.showerror("Open video", f"Could not open {path}")
            return
        nframes = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if nframes <= 0:
            messagebox.showerror("Open video", "Could not work out how many frames the video has.")
            return
        self.playing = False
        self.play_btn.config(text="Play")
        if self.cap:
            self.cap.release()
        self.cap, self.video = cap, Path(path)
        self.nframes = nframes
        self.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        self.vw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.vh = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.zoom = min(self.max_w / self.vw, self.max_h / self.vh, 2.0)
        self.dw, self.dh = int(self.vw * self.zoom), int(self.vh * self.zoom)
        self.canvas.config(width=self.dw, height=self.dh)
        self.scale.config(to=max(1, nframes - 1))
        self.video_label.config(text=f"{self.video.name}\n{self.vw}x{self.vh}, {self.fps:.2f} fps, "
                                     f"{nframes / self.fps:.1f} s")

        off_screen = [b for b, box in enumerate(self.boxes) if box and
                      (box[0] + box[2] > self.vw or box[1] + box[3] > self.vh)]
        for b in off_screen:
            self.boxes[b] = None
        if off_screen:
            self.say(f"Removed boxes {off_screen}: they did not fit this video. Place them again.")

        self.samples = self.samples_key = None
        self._drawn = [None] * self.n
        self._handles_drawn = None
        self.read_pos = -1
        self.draw_roll()
        self.show(0)

    def show(self, i):
        """Display frame i. Returns False if it could not be read."""
        i = max(0, min(self.nframes - 1, int(i)))
        if i != self.read_pos:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, frame = self.cap.read()
        if not ok:
            self.read_pos = -1
            return False
        self.read_pos, self.cur = i + 1, i

        # sharper resize when paused, cheaper while playing
        interp = cv2.INTER_AREA if (self.zoom < 1 and not self.playing) else cv2.INTER_LINEAR
        small = cv2.resize(frame, (self.dw, self.dh), interpolation=interp)
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        self.photo = tk.PhotoImage(data=b"P6 %d %d 255\n" % (self.dw, self.dh) + rgb.tobytes())
        self.canvas.itemconfig(self.img_item, image=self.photo)

        self.update_overlay()
        if not self.playing or time.perf_counter() - self._ui_t >= 0.1:  # ~10 refreshes a second while playing
            self._sync_ui()
        return True

    def _sync_ui(self):
        """Bring the slider, time label and strip playhead up to date with the frame on screen."""
        self._ui_t = time.perf_counter()
        self._echo = self.cur
        self.scale.set(self.cur)
        self.time_label.config(text=f"{self.cur / self.fps:8.2f} s   frame {self.cur}")
        self.update_playhead()

    def step(self, delta):
        if self.cap:
            self.show(self.cur + delta)
            self.rebase_play()

    def on_scale(self, value):
        # Tk runs this callback later, not inside scale.set(), so a flag around scale.set()
        # is already cleared by then. Our own updates arrive as the value we just set.
        v = int(float(value))
        if not self.cap or v == self._echo or v == self.cur:
            return
        self.show(v)
        self.rebase_play()

    def toggle_play(self):
        if not self.cap:
            return
        self.playing = not self.playing
        self.play_btn.config(text="Pause" if self.playing else "Play")
        if self.playing:
            if self.cur >= self.nframes - 1:
                self.show(0)
            self.rebase_play()
            self.tick()
        else:
            self._sync_ui()

    def rebase_play(self):
        self.play_t0, self.play_i0 = time.perf_counter(), self.cur

    def _stop_playing(self):
        self.playing = False
        self.play_btn.config(text="Play")
        self._sync_ui()

    def tick(self):
        """Advance by wall-clock time. Frames we cannot draw in time are skipped, not delayed.

        Unless "every frame" is ticked, at most about 30 frames a second are drawn, which keeps
        60 fps video smooth on slower machines; step with Left/Right to see every frame.
        """
        if not self.playing:
            return
        target = self.play_i0 + int((time.perf_counter() - self.play_t0) * self.fps)
        if target >= self.nframes:
            self._stop_playing()
            return
        stride = 1 if self.full_rate.get() else max(1, int(round(self.fps / 30)))
        if target >= self.cur + stride:
            while self.read_pos < target:
                self.cap.grab()
                self.read_pos += 1
            if not self.show(target):
                self._stop_playing()
                return
        self.root.after(5, self.tick)

    # ------------------------------------------------------------ boxes

    def _to_video(self, x, y):
        return x / self.zoom, y / self.zoom

    def _clamp(self, x, y):
        return min(max(x, 0), self.vw), min(max(y, 0), self.vh)

    def _order(self):
        """Selected block first, so overlapping boxes favour it."""
        return [self.block] + [b for b in range(self.n) if b != self.block]

    def _box_at(self, vx, vy):
        for b in self._order():
            box = self.boxes[b]
            if box and box[0] <= vx <= box[0] + box[2] and box[1] <= vy <= box[1] + box[3]:
                return b
        return None

    def on_press(self, e):
        if not self.cap:
            return
        self.canvas.focus_set()
        vx, vy = self._to_video(e.x, e.y)

        box = self.boxes[self.block]
        if box:  # grab a corner of the selected box?
            x, y, w, h = box
            for fx in (0, 1):
                for fy in (0, 1):
                    if abs(e.x - (x + fx * w) * self.zoom) <= HANDLE and abs(e.y - (y + fy * h) * self.zoom) <= HANDLE:
                        anchor = (x + (1 - fx) * w, y + (1 - fy) * h)
                        self.drag = {"mode": "box", "block": self.block, "anchor": anchor, "prev": box}
                        return

        hit = self._box_at(vx, vy)
        if hit is not None:
            self.select_block(hit)
            x, y, w, h = self.boxes[hit]
            self.drag = {"mode": "move", "block": hit, "off": (vx - x, vy - y), "prev": self.boxes[hit]}
        else:
            self.drag = {"mode": "box", "block": self.block, "anchor": self._clamp(vx, vy),
                         "prev": self.boxes[self.block], "new": True}

    def on_drag(self, e):
        d = self.drag
        if not d:
            return
        d["moved"] = True
        vx, vy = self._to_video(e.x, e.y)
        b = d["block"]
        if d["mode"] == "move":
            x, y, w, h = self.boxes[b]
            x = min(max(vx - d["off"][0], 0), self.vw - w)
            y = min(max(vy - d["off"][1], 0), self.vh - h)
            self.boxes[b] = (x, y, w, h)
        else:
            ax, ay = d["anchor"]
            px, py = self._clamp(vx, vy)
            self.boxes[b] = (min(ax, px), min(ay, py), abs(px - ax), abs(py - ay))
        self.update_overlay()

    def on_release(self, e):
        d, self.drag = self.drag, None
        if not d or not d.get("moved"):
            return
        b = d["block"]
        box = self.boxes[b]
        if d["mode"] == "box" and box and (box[2] < MIN_BOX or box[3] < MIN_BOX):
            self.boxes[b] = d["prev"]  # a click, or a box too small to use: undo
        elif d["mode"] == "box" or box != d["prev"]:
            self.regions_changed()
            if d.get("new"):  # just drew a new box: move on to the next empty block
                nxt = next((i for i in range(b + 1, self.n) if self.boxes[i] is None), None)
                if nxt is not None:
                    self.select_block(nxt)
        self._refresh_block_buttons()
        self.update_overlay()

    def on_right_click(self, e):
        if not self.cap:
            return
        hit = self._box_at(*self._to_video(e.x, e.y))
        if hit is not None:
            self.boxes[hit] = None
            self.regions_changed()
            self._refresh_block_buttons()
            self.update_overlay()

    def delete_selected(self):
        if self.boxes[self.block]:
            self.boxes[self.block] = None
            self.regions_changed()
            self._refresh_block_buttons()
            self.update_overlay()

    def select_block(self, b):
        self.block = b
        self.block_var.set(b)
        self.update_overlay()

    def on_select_block(self):
        self.block = self.block_var.get()
        self.update_overlay()

    def regions_changed(self):
        self.say("Boxes changed. Press Analyze to update the timing.")

    def _region(self, b):
        x, y, w, h = (int(round(v)) for v in self.boxes[b])
        x, y = max(0, x), max(0, y)
        return x, y, max(1, min(w, self.vw - x)), max(1, min(h, self.vh - y))

    # ------------------------------------------------------------ drawing

    def update_overlay(self):
        """Draw the boxes. Only boxes whose shape or lit state changed cost any Tk calls."""
        if not self.cap:
            return
        lit = self.timeline.lit_at(self.cur / self.fps) if self.timeline else [False] * self.n
        c = self.canvas
        for b in range(self.n):
            box = self.boxes[b]
            key = (box, lit[b])
            if key == self._drawn[b]:
                continue
            self._drawn[b] = key
            if not box:
                c.itemconfig(self.rects[b], state="hidden")
                c.itemconfig(self.labels[b], state="hidden")
                continue
            x0, y0 = box[0] * self.zoom, box[1] * self.zoom
            x1, y1 = (box[0] + box[2]) * self.zoom, (box[1] + box[3]) * self.zoom
            c.coords(self.rects[b], x0, y0, x1, y1)
            c.itemconfig(self.rects[b], state="normal", outline=self.colours[b],
                         width=4 if lit[b] else 2, fill=self.colours[b] if lit[b] else "",
                         stipple="gray50" if lit[b] else "")
            c.coords(self.labels[b], x0 + 3, y0 + 2)
            c.itemconfig(self.labels[b], state="normal", text=str(b), fill=self.colours[b])

        box = self.boxes[self.block]
        if (self.block, box) != self._handles_drawn:
            self._handles_drawn = (self.block, box)
            for i, hd in enumerate(self.handles):
                if not box:
                    c.itemconfig(hd, state="hidden")
                    continue
                cx = (box[0] + (i % 2) * box[2]) * self.zoom
                cy = (box[1] + (i // 2) * box[3]) * self.zoom
                c.coords(hd, cx - 3, cy - 3, cx + 3, cy + 3)
                c.itemconfig(hd, state="normal")
                c.tag_raise(hd)

    def _refresh_block_buttons(self):
        for b, btn in enumerate(self.block_btns):
            line1 = f"{b} ✓" if self.boxes[b] else f"{b}"
            info = self.infos.get(b)
            line2 = ""
            if self.per_block is not None and self.boxes[b]:
                warn = " !" if info and not info["usable"] else ""
                line2 = f"{len(self.per_block[b])} on{warn}"
            btn.config(text=f"{line1}\n{line2}")

    def draw_roll(self):
        c = self.roll
        c.delete("all")
        width = getattr(self, "dw", 640)
        c.config(width=ROLL_LEFT + width, height=self.n * ROW_H)
        for b in range(self.n):
            y = b * ROW_H
            c.create_text(ROLL_LEFT - 4, y + ROW_H / 2, text=str(b), anchor="e", fill="#999", font=("TkDefaultFont", 7))
            c.create_line(ROLL_LEFT, y + ROW_H, ROLL_LEFT + width, y + ROW_H, fill="#222")
        if self.per_block and self.cap:
            duration = self.nframes / self.fps
            for b, ivs in enumerate(self.per_block):
                for s, e in ivs:
                    x0 = ROLL_LEFT + s / duration * width
                    x1 = max(x0 + 1, ROLL_LEFT + e / duration * width)
                    c.create_rectangle(x0, b * ROW_H + 1, x1, (b + 1) * ROW_H - 1, fill=self.colours[b], outline="")
        self.playhead = c.create_line(ROLL_LEFT, 0, ROLL_LEFT, self.n * ROW_H, fill="white")
        self.update_playhead()

    def update_playhead(self):
        if self.playhead is None or not self.cap:
            return
        x = ROLL_LEFT + self.cur / max(1, self.nframes - 1) * self.dw
        self.roll.coords(self.playhead, x, 0, x, self.n * ROW_H)

    def on_roll(self, e):
        if self.cap:
            frac = min(max((e.x - ROLL_LEFT) / self.dw, 0.0), 1.0)
            self.show(frac * (self.nframes - 1))
            self.rebase_play()

    def say(self, text):
        self.status.config(text=text)

    # ------------------------------------------------------------ saving and loading

    def _load_existing(self):
        if self.song.regions_path.exists():
            try:
                for b, box in read_regions_file(self.song.regions_path).items():
                    if b < self.n:
                        self.boxes[b] = tuple(float(v) for v in box)
            except (ValueError, KeyError, json.JSONDecodeError):
                self.say("regions.json could not be read; starting with no boxes.")
        if self.song.blocks_path.exists():
            try:
                data = json.loads(self.song.blocks_path.read_text())
                per_block = [[] for _ in range(self.n)]
                for e in data:
                    per_block[int(e["block"])].append((float(e["start"]), float(e["end"])))
                self.per_block = per_block
                self.timeline = Timeline(data, self.n)
            except (ValueError, KeyError, IndexError, json.JSONDecodeError):
                self.say("blocks.json could not be read; ignoring it.")
        self._refresh_block_buttons()

    def save_regions_clicked(self):
        save_regions(self.song.regions_path, [self._region(b) if self.boxes[b] else None for b in range(self.n)])
        self.say(f"Saved {sum(1 for b in self.boxes if b)} boxes to {self.song.regions_path.name}.")

    def save_blocks_clicked(self):
        if self.per_block is None:
            messagebox.showinfo("Save blocks.json", "Nothing to save yet. Press Analyze first.")
            return
        count = analyze.save_blocks(self.song.blocks_path, self.per_block)
        self.say(f"Saved {count} intervals to {self.song.blocks_path.name} (the old one is kept as blocks.json.bak).")

    # ------------------------------------------------------------ analysis

    def use_this_frame_as_dim(self):
        if self.cap:
            self.dim_var.set(f"{self.cur / self.fps:.2f}")

    def _thresholds(self):
        try:
            on, off, min_len = float(self.on_var.get()), float(self.off_var.get()), float(self.len_var.get())
            dim_at = float(self.dim_var.get()) if self.dim_var.get().strip() else None
        except ValueError:
            raise ValueError("Thresholds, min length and dim frame must be numbers (dim frame can be blank).")
        if not 0 < off < on:
            raise ValueError("Need 0 < off threshold < on threshold.")
        if min_len < 0:
            raise ValueError("Min length cannot be negative.")
        return on, off, min_len, dim_at

    def analyze_clicked(self):
        if not self.cap:
            messagebox.showinfo("Analyze", "Open a video first.")
            return
        if self.analysing:
            return
        placed = [b for b in range(self.n) if self.boxes[b]]
        if not placed:
            messagebox.showinfo("Analyze", "Place at least one box first.")
            return
        try:
            thresholds = self._thresholds()
        except ValueError as err:
            messagebox.showerror("Analyze", str(err))
            return

        self.save_regions_clicked()
        regions = [self._region(b) for b in placed]
        key = analyze.cache_key(self.video, regions)

        if self.samples is not None and self.samples_key == key:  # only thresholds changed
            self.finish_detect(placed, thresholds)
            return
        cached = analyze.load_cache(self.song.folder / "samples.npz", key)
        if cached:
            self.samples, self.samples_fps = cached
            self.samples_key = key
            self.finish_detect(placed, thresholds)
            return

        self.analysing = True
        self.analyze_btn.config(state="disabled")
        self.progress.config(value=0, maximum=max(1, self.nframes))
        self.say("Reading the video…")
        threading.Thread(target=self._worker, args=(self.video, regions, key, placed, thresholds), daemon=True).start()
        self.root.after(100, self._poll)

    def _worker(self, video, regions, key, placed, thresholds):
        try:
            def on_progress(done, total):
                if done % 20 == 0:
                    self.q.put(("progress", done))

            samples, fps = analyze.read_samples(video, regions, on_progress)
            analyze.save_cache(self.song.folder / "samples.npz", samples, fps, key)
            self.q.put(("done", samples, fps, key, placed, thresholds))
        except analyze.AnalysisError as err:
            self.q.put(("error", str(err)))
        except Exception as err:  # keep the GUI alive whatever happens in the thread
            self.q.put(("error", f"{type(err).__name__}: {err}"))

    def _poll(self):
        finished = False
        try:
            while True:
                msg = self.q.get_nowait()
                if msg[0] == "progress":
                    self.progress.config(value=msg[1])
                elif msg[0] == "done":
                    _, self.samples, self.samples_fps, self.samples_key, placed, thresholds = msg
                    finished = True
                    self.analysing = False
                    self.analyze_btn.config(state="normal")
                    self.finish_detect(placed, thresholds)
                elif msg[0] == "error":
                    finished = True
                    self.analysing = False
                    self.analyze_btn.config(state="normal")
                    self.say("Analysis failed.")
                    messagebox.showerror("Analyze", msg[1])
        except queue.Empty:
            pass
        if self.analysing and not finished:
            self.root.after(100, self._poll)

    def finish_detect(self, placed, thresholds):
        on, off, min_len, dim_at = thresholds
        sub, info = analyze.detect(self.samples, self.samples_fps, on, off, min_len, dim_at=dim_at)
        self.per_block = [[] for _ in range(self.n)]
        self.infos = {}
        for i, b in enumerate(placed):
            self.per_block[b] = sub[i]
            self.infos[b] = info[i]
        self.timeline = Timeline([{"block": b, "start": s, "end": e}
                                  for b, ivs in enumerate(self.per_block) for s, e in ivs], self.n)
        self.progress.config(value=0)
        self.draw_roll()
        self._refresh_block_buttons()
        self.update_overlay()

        total = sum(len(v) for v in self.per_block)
        notes = []
        for b in placed:
            if not self.infos[b]["usable"]:
                notes.append(f"block {b} never seemed to change colour (is the box on the block?)")
        self.say(f"Found {total} flashes across {len(placed)} blocks. Press Save blocks.json to keep them."
                 + ("\n! " + "\n! ".join(notes) if notes else ""))

    # ------------------------------------------------------------ shutdown

    def close(self):
        self.playing = False
        if self.cap:
            self.cap.release()
        self.root.destroy()


def main(song_dir, video=None):
    root = tk.Tk()
    App(root, song_dir, video)
    root.mainloop()


if __name__ == "__main__":
    main(Path("songs/wavetapper"), sys.argv[1] if len(sys.argv) > 1 else None)
