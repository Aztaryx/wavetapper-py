"""One CLI for all the analysis tools. Run from the project root:

    python tools/cli.py gui       [path/to/video.mp4]      <- the easy way: place boxes by hand
    python tools/cli.py calibrate path/to/video.mp4 --at 30
    python tools/cli.py analyze   path/to/video.mp4
    python tools/cli.py preview   path/to/video.mp4
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # so `engine` and `config` import

import typer  # noqa: E402

app = typer.Typer(no_args_is_help=True, add_completion=False, help="Wavetapper analysis tools.")

VIDEO = typer.Argument(..., exists=True, dir_okay=False, help="The video to analyse (supply your own file).")
SONG = typer.Option(Path("songs/wavetapper"), "--song", "-s", help="Song folder.")


@app.command()
def calibrate(
    video: Path = VIDEO,
    song: Path = SONG,
    at: float = typer.Option(0.0, help="Time in seconds of a frame where all blocks are visible and dim."),
    shrink: float = typer.Option(0.2, help="Fraction of each box trimmed away so edges are not sampled."),
):
    """Draw a box on each block; saves regions.json."""
    from tools import calibrate as mod
    mod.run(video, song, at, shrink)


@app.command()
def analyze(
    video: Path = VIDEO,
    song: Path = SONG,
    on_threshold: float = typer.Option(0.5, help="Turn on above this fraction of the block's lit level."),
    off_threshold: float = typer.Option(0.3, help="Turn off below this fraction (must be lower than on)."),
    min_length: float = typer.Option(0.04, help="Drop intervals shorter than this many seconds."),
    ref_percentile: float = typer.Option(99.0, help="Percentile of a block's scores treated as 'fully lit'."),
    min_range: float = typer.Option(15.0, help="Blocks with a smaller colour range are treated as never lit."),
    rescan: bool = typer.Option(False, help="Re-read the video instead of using cached frame data."),
    dim_at: float = typer.Option(None, help="A time (s) when every block is dim. Default: found automatically."),
):
    """Detect when each block is lit; writes blocks.json."""
    from tools import analyze as mod
    mod.run(video, song, on_threshold, off_threshold, min_length, ref_percentile, min_range, rescan, dim_at)


@app.command()
def preview(
    video: Path = VIDEO,
    song: Path = SONG,
    speed: float = typer.Option(1.0, help="Playback speed multiplier."),
):
    """Replay the video with the detected state drawn on it."""
    from tools import preview as mod
    mod.run(video, song, speed)


@app.command()
def gui(
    video: Path = typer.Argument(None, exists=True, dir_okay=False, help="Video to open (or choose one in the window)."),
    song: Path = SONG,
):
    """Open the window: place the detector boxes by hand, analyse, and check the timing."""
    from tools import gui as mod
    mod.main(song, video)


if __name__ == "__main__":
    app()
