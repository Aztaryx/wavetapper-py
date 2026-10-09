"""Loads a song folder and answers "which blocks are lit at time t"."""
from __future__ import annotations

import json
from bisect import bisect_right
from dataclasses import dataclass
from pathlib import Path

import config


@dataclass
class Song:
    folder: Path
    title: str
    artist: str
    audio: Path
    offset: float
    cols: int
    rows: int
    palette: list  # [(dim, lit), ...], one per block

    @property
    def num_blocks(self) -> int:
        return self.cols * self.rows

    @property
    def blocks_path(self) -> Path:
        return self.folder / "blocks.json"

    @property
    def regions_path(self) -> Path:
        return self.folder / "regions.json"


def load_song(folder) -> Song:
    folder = Path(folder)
    meta_path = folder / "song.json"
    if not meta_path.exists():
        raise FileNotFoundError(f"{meta_path} not found")
    meta = json.loads(meta_path.read_text(encoding="utf-8"))

    grid = meta.get("grid", {})
    cols = int(grid.get("cols", config.GRID_COLS))
    rows = int(grid.get("rows", config.GRID_ROWS))
    n = cols * rows

    palette = [(int(e["dim"]), int(e["lit"])) for e in meta.get("palette", [])][:n]
    while len(palette) < n:  # fill gaps from the default palette
        palette.append(config.DEFAULT_PALETTE[len(palette) % len(config.DEFAULT_PALETTE)])

    return Song(
        folder=folder,
        title=meta.get("title", folder.name),
        artist=meta.get("artist", ""),
        audio=folder / meta.get("audio", "audio.wav"),
        offset=float(meta.get("offset", 0.0)),
        cols=cols,
        rows=rows,
        palette=palette,
    )


def _merge(intervals):
    """Merge overlapping or touching (start, end) pairs."""
    merged = []
    for s, e in sorted(intervals):
        if merged and s <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return merged


class Timeline:
    """Per-block sorted, non-overlapping intervals with a bisect lookup.

    Bisect (rather than a forward-only cursor) means seeking costs nothing
    extra, so pause/seek hotkeys can be added later without changing this.
    """

    def __init__(self, intervals, num_blocks: int):
        per_block = [[] for _ in range(num_blocks)]
        for i, iv in enumerate(intervals):
            block, start, end = int(iv["block"]), float(iv["start"]), float(iv["end"])
            if not 0 <= block < num_blocks:
                raise ValueError(f"entry {i}: block {block} is out of range 0-{num_blocks - 1}")
            if end <= start:
                raise ValueError(f"entry {i}: end ({end}) must be after start ({start})")
            per_block[block].append((start, end))

        merged = [_merge(p) for p in per_block]
        self._starts = [[s for s, _ in m] for m in merged]
        self._ends = [[e for _, e in m] for m in merged]
        self.num_blocks = num_blocks
        self.duration = max((e[-1] for e in self._ends if e), default=0.0)

    @classmethod
    def load(cls, path, num_blocks: int) -> "Timeline":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(data, num_blocks)

    def is_lit(self, block: int, t: float) -> bool:
        i = bisect_right(self._starts[block], t) - 1
        return i >= 0 and t < self._ends[block][i]

    def lit_at(self, t: float) -> list:
        return [self.is_lit(b, t) for b in range(self.num_blocks)]
