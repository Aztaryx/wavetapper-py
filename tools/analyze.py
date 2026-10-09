"""analyze: work out when each block is lit from the video, write blocks.json.

Steps: average colour per region per frame -> distance from each block's dim colour
-> scale per block -> hysteresis on/off -> drop very short intervals.
The slow part (reading the video) is cached in samples.npz, so re-running with
different thresholds takes seconds.
"""
import hashlib
import json
import shutil
from pathlib import Path

import cv2
import numpy as np
from rich import print as rprint
from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
from rich.table import Table

from engine.timeline import load_song
from tools.common import fail, load_regions


# ---------- pure functions (tested without a video) ----------

def region_means(frame, regions):
    """Mean BGR colour inside each region -> array (blocks, 3)."""
    return np.array([frame[y:y + h, x:x + w].reshape(-1, 3).mean(axis=0) for x, y, w, h in regions],
                    dtype=np.float32)


LUMA_BGR = np.array([0.114, 0.587, 0.299], dtype=np.float32)  # brightness weights for B, G, R


def dim_baseline(samples, fps, dim_at=None, dark_fraction=0.10, window=0.25):
    """Each block's 'dim' colour, shape (blocks, 3).

    Default: the average of that block's darkest 10% of frames. A median would be
    wrong for any block that is lit more than half the time (its median is the
    lit colour, so the detection comes out backwards).
    With dim_at (seconds): the average colour over `window` seconds from that time,
    for when you know a moment when every block is dim.
    """
    if dim_at is not None:
        start = min(max(int(round(dim_at * fps)), 0), len(samples) - 1)
        return samples[start:start + max(1, int(round(window * fps)))].mean(axis=0)
    luma = samples @ LUMA_BGR                                  # (frames, blocks)
    cutoff = np.percentile(luma, dark_fraction * 100, axis=0)  # (blocks,)
    return np.stack([samples[luma[:, b] <= cutoff[b], b].mean(axis=0) for b in range(samples.shape[1])])


def scores_from_samples(samples, fps=30.0, dim_at=None):
    """samples (frames, blocks, 3) -> distance from each block's dim colour (frames, blocks)."""
    return np.linalg.norm(samples - dim_baseline(samples, fps, dim_at), axis=2)


def normalise(scores, ref_percentile, min_range):
    """Scale each block's scores so its own 'fully lit' level is about 1.0.

    This gives every block the same thresholds even if its lit colour is close
    to its dim colour. Blocks whose range is below min_range are treated as
    never lit (their scores become 0) because scaling noise up would invent flashes.
    """
    ref = np.percentile(scores, ref_percentile, axis=0)
    usable = ref >= min_range
    norm = np.where(usable, scores / np.maximum(ref, 1e-6), 0.0)
    return norm, ref, usable


def hysteresis(values, on, off):
    """On at >= on, off at < off. The gap between the two stops flicker."""
    state = np.zeros(len(values), dtype=bool)
    cur = False
    for i, v in enumerate(values.tolist()):
        if cur:
            if v < off:
                cur = False
        elif v >= on:
            cur = True
        state[i] = cur
    return state


def state_to_intervals(state, fps, min_length):
    """Boolean per frame -> [(start, end)] seconds, dropping intervals shorter than min_length."""
    edges = np.diff(np.concatenate(([0], state.astype(np.int8), [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return [(s / fps, e / fps) for s, e in zip(starts, ends) if (e - s) / fps >= min_length]


def detect(samples, fps, on, off, min_length, ref_percentile=99.0, min_range=15.0, dim_at=None):
    """Full detection. Returns (intervals_per_block, info_per_block)."""
    scores = scores_from_samples(samples, fps, dim_at)
    norm, ref, usable = normalise(scores, ref_percentile, min_range)
    per_block, info = [], []
    for b in range(samples.shape[1]):
        state = hysteresis(norm[:, b], on, off)
        per_block.append(state_to_intervals(state, fps, min_length))
        info.append({"range": float(ref[b]), "usable": bool(usable[b]), "lit_fraction": float(state.mean())})
    return per_block, info


# ---------- video reading and caching ----------

class AnalysisError(Exception):
    """Something wrong with the video or regions (the GUI shows this in a dialog)."""


def read_samples(video, regions, on_progress=None):
    """Read every frame and return (samples (frames, blocks, 3), fps). No terminal output."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise AnalysisError(f"could not open video: {video}")
    fps = cap.get(cv2.CAP_PROP_FPS)
    if not fps or fps <= 0:
        raise AnalysisError("the video reports no frame rate")
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    for b, (x, y, w, h) in enumerate(regions):
        if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > width or y + h > height:
            raise AnalysisError(f"region {b} {(x, y, w, h)} does not fit in the {width}x{height} video. "
                                "Were the regions made from a different video?")
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) or None

    rows = []
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        rows.append(region_means(frame, regions))
        if on_progress:
            on_progress(len(rows), total)
    cap.release()
    if not rows:
        raise AnalysisError("no frames could be read from the video")
    return np.stack(rows), float(fps)


def extract_samples(video, regions):
    """read_samples with a terminal progress bar, for the command line."""
    with Progress(TextColumn("reading frames"), BarColumn(), TextColumn("{task.completed}/{task.total}"),
                  TimeRemainingColumn()) as progress:
        task = progress.add_task("", total=None)

        def on_progress(done, total):
            progress.update(task, completed=done, total=total)

        try:
            return read_samples(video, regions, on_progress)
        except AnalysisError as e:
            progress.stop()
            fail(str(e))


def cache_key(video, regions):
    st = Path(video).stat()
    raw = json.dumps([str(Path(video).resolve()), st.st_size, int(st.st_mtime), [list(r) for r in regions]])
    return hashlib.sha1(raw.encode()).hexdigest()


def load_cache(cache_path, key):
    """Return (samples, fps) if the cache file matches this key, else None."""
    if not Path(cache_path).exists():
        return None
    with np.load(cache_path) as data:
        if str(data["key"]) == key:
            return data["samples"], float(data["fps"])
    return None


def save_cache(cache_path, samples, fps, key):
    np.savez(cache_path, samples=samples, fps=fps, key=key)


def load_or_extract(video, regions, cache_path, rescan):
    key = cache_key(video, regions)
    cached = None if rescan else load_cache(cache_path, key)
    if cached:
        rprint(f"using cached frame data ({Path(cache_path).name}); pass --rescan to re-read the video")
        return cached
    samples, fps = extract_samples(video, regions)
    save_cache(cache_path, samples, fps, key)
    return samples, fps


# ---------- command ----------

def save_blocks(path, intervals_per_block):
    """Write blocks.json, keeping the previous file as blocks.json.bak. Returns the interval count."""
    path = Path(path)
    if path.exists():
        shutil.copy(path, path.with_name("blocks.json.bak"))
    entries = sorted(({"block": b, "start": round(s, 3), "end": round(e, 3)}
                      for b, ivs in enumerate(intervals_per_block) for s, e in ivs),
                     key=lambda e: (e["start"], e["block"]))
    path.write_text("[\n" + ",\n".join("  " + json.dumps(e) for e in entries) + "\n]\n")
    return len(entries)


def run(video, song_dir, on_threshold, off_threshold, min_length, ref_percentile, min_range, rescan,
        dim_at=None):
    if not 0 < off_threshold < on_threshold:
        fail("need 0 < --off-threshold < --on-threshold")
    song = load_song(song_dir)
    regions = load_regions(song.regions_path, song.num_blocks)
    samples, fps = load_or_extract(video, regions, song.folder / "samples.npz", rescan)

    per_block, info = detect(samples, fps, on_threshold, off_threshold, min_length, ref_percentile, min_range, dim_at)

    had_old = song.blocks_path.exists()
    count = save_blocks(song.blocks_path, per_block)
    if had_old:
        rprint("[dim]previous blocks.json saved as blocks.json.bak[/dim]")

    table = Table(title=f"{len(samples)} frames at {fps:.2f} fps ({len(samples) / fps:.1f} s)")
    for col in ("block", "intervals", "lit %", "colour range", "note"):
        table.add_column(col, justify="right" if col != "note" else "left")
    for b, (ivs, i) in enumerate(zip(per_block, info)):
        note = ""
        if not i["usable"]:
            note = "[yellow]never lit? colour range too small[/yellow]"
        table.add_row(str(b), str(len(ivs)), f"{i['lit_fraction'] * 100:.1f}", f"{i['range']:.0f}", note)
    rprint(table)
    rprint(f"[green]wrote[/green] {count} intervals to {song.blocks_path}")
