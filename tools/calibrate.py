"""calibrate: draw one box per block on a video frame and save regions.json."""
import cv2
from rich import print as rprint

from engine.timeline import load_song
from tools.common import fail, open_video, save_regions

WINDOW = "calibrate"


def shrink_box(x, y, w, h, shrink):
    """Remove `shrink` (a fraction, e.g. 0.2) of the width and height, evenly from all sides."""
    dx = int(round(w * shrink / 2))
    dy = int(round(h * shrink / 2))
    return x + dx, y + dy, max(1, w - 2 * dx), max(1, h - 2 * dy)


def draw_regions(frame, regions, thickness=2):
    """Return a copy of frame with each region boxed and numbered."""
    out = frame.copy()
    for b, (x, y, w, h) in enumerate(regions):
        cv2.rectangle(out, (x, y), (x + w, y + h), (0, 255, 0), thickness)
        cv2.putText(out, str(b), (x + 3, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1, cv2.LINE_AA)
    return out


def grab_frame(video, at):
    cap = open_video(video)
    cap.set(cv2.CAP_PROP_POS_MSEC, at * 1000.0)
    ok, frame = cap.read()
    cap.release()
    if not ok:
        fail(f"could not read a frame at {at}s")
    return frame


def run(video, song_dir, at, shrink, max_width=1280):
    song = load_song(song_dir)
    n = song.num_blocks
    frame = grab_frame(video, at)

    scale = min(1.0, max_width / frame.shape[1])
    view = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame

    rprint(f"Draw a box on each of the {n} blocks, in order 0 to {n - 1}, "
           f"{song.cols} per row, left to right then top to bottom.\n"
           "Drag a box, press [bold]ENTER[/bold] to confirm it, [bold]C[/bold] to cancel everything.")

    boxes = []  # in view coordinates
    for b in range(n):
        canvas = draw_regions(view, boxes, 1)
        cv2.putText(canvas, f"Block {b} of {n - 1}: drag, ENTER = confirm, C = cancel", (10, 24),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2, cv2.LINE_AA)
        x, y, w, h = cv2.selectROI(WINDOW, canvas, showCrosshair=False)
        if w == 0 or h == 0:
            cv2.destroyAllWindows()
            fail("cancelled, nothing saved")
        boxes.append((x, y, w, h))
    cv2.destroyAllWindows()

    height, width = frame.shape[:2]
    regions = []
    for x, y, w, h in boxes:
        x, y, w, h = (int(round(v / scale)) for v in (x, y, w, h))
        x, y, w, h = shrink_box(x, y, w, h, shrink)
        x, y = max(0, x), max(0, y)
        regions.append((x, y, min(w, width - x), min(h, height - y)))

    save_regions(song.regions_path, regions)
    preview_path = song.folder / "regions_preview.png"
    cv2.imwrite(str(preview_path), draw_regions(frame, regions))
    rprint(f"[green]saved[/green] {song.regions_path} and {preview_path}")
