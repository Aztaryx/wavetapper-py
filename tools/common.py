"""Helpers shared by the analysis tools."""
import json
from pathlib import Path

import cv2
import typer
from rich import print as rprint


def fail(message: str):
    rprint(f"[red]error:[/red] {message}")
    raise typer.Exit(1)


def open_video(path) -> cv2.VideoCapture:
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        fail(f"could not open video: {path}")
    return cap


def read_regions_file(path):
    """Return {block: (x, y, w, h)} for whatever blocks the file contains."""
    return {int(r["block"]): (int(r["x"]), int(r["y"]), int(r["w"]), int(r["h"]))
            for r in json.loads(Path(path).read_text())}


def load_regions(path, num_blocks: int):
    """Return [(x, y, w, h), ...] ordered by block number; every block must be present."""
    path = Path(path)
    if not path.exists():
        fail(f"{path} not found. Run `calibrate` or `gui` first.")
    by_block = read_regions_file(path)
    missing = [b for b in range(num_blocks) if b not in by_block]
    if missing:
        fail(f"{path} has no region for block(s) {missing}")
    return [by_block[b] for b in range(num_blocks)]


def save_regions(path, regions):
    """regions[b] is (x, y, w, h) or None (block not placed yet, skipped)."""
    lines = ",\n".join("  " + json.dumps({"block": b, "x": x, "y": y, "w": w, "h": h})
                       for b, r in enumerate(regions) if r is not None for x, y, w, h in [r])
    Path(path).write_text("[\n" + lines + "\n]\n")
