# Wavetapper CLI

16 coloured blocks flash in the terminal in sync with a song. See the project plan for the design.

## Setup

    pip install -r requirements.txt

## 1. Check the engine with the demo (no video needed)

    python tools/make_demo.py          # writes songs/demo: click track + hand-made blocks.json
    python main.py songs/demo          # every flash starts with a click: check sync by ear
    python main.py songs/demo --no-audio

Window must be at least 14 columns by 11 rows.

## 2. Make Wavetapper's timing data

Put your own audio at `songs/wavetapper/audio.wav` and have your own copy of the video.

### The window (recommended)

    python tools/cli.py gui path\to\video.mp4

- Drag a box on each block. The selected block advances by itself; boxes are numbered 0-15, left to right,
  top to bottom. Drag a box to move it, drag a corner to resize, right-click or press Delete to remove one.
- Scrub the slider or press Space to play, Left/Right to step a frame (Shift = 1 second).
  Playback stays in real time by drawing up to about 30 frames a second (60 fps video is shown every
  other frame). Tick **every frame** to draw them all if your computer can keep up, or step with
  Left/Right to check exact frames.
- Press **Analyze**. The strip under the video shows every detected flash per block; click it to jump there.
  Lit blocks light up on the video as it plays, so you can see straight away if a box is in the wrong place.
- Change the thresholds and press Analyze again: this takes a moment because the video is only read once.
- **Save blocks.json** keeps the result (the old file is kept as `blocks.json.bak`). Boxes are saved
  automatically when you analyze, and reloaded the next time you open the window.

Keep each box well inside its block, away from the edges, so it only samples that block's colour.

### Command line

    python tools/cli.py calibrate video.mp4 --at 30   # draw 16 boxes in order; saves regions.json
    python tools/cli.py analyze   video.mp4           # writes blocks.json (old one kept as blocks.json.bak)
    python tools/cli.py preview   video.mp4           # video with boxes + detected state drawn on it

`--at` is a time (seconds) where all 16 blocks are visible and dim. The window and the command line share
the same files, so you can mix them.

    python tools/cli.py analyze video.mp4 --on-threshold 0.6 --off-threshold 0.35 --min-length 0.06

Thresholds are fractions of each block's own lit level (not raw colour distance), so every block can use the
same values. A block marked `!` in the window (or flagged in the command-line table) never changed colour
enough to detect, so check its box is on the block.

What "dim" looks like is found automatically for each block (the average of its darkest 10% of frames), so
blocks that are lit most of the time work too. If a block still looks backwards, give the analyzer a moment
when every cube is dim: in the window, scrub there and press **Here** next to "dim frame (s)", then Analyze;
on the command line, add `--dim-at 0.5`.

then play it:

    python main.py songs/wavetapper

## Offset

`offset` in `song.json` shifts all timing in seconds (positive = flashes later). Tune it by ear:

    python main.py songs/wavetapper --offset 0.08

then copy the value into `song.json`.

## Tests

    python -m pytest -q

Includes an end-to-end test: a synthetic 4x4 video is analysed and compared with known timing.
The window tests need a display and are skipped without one (on Linux: `xvfb-run -a python -m pytest`).

## Not built yet

`tap` (manual correction), pause/seek hotkeys, `--reduce-flash`.
