"""preview: replay the video with the 16 boxes and the detected state drawn on it."""
import cv2

from engine.timeline import Timeline, load_song
from tools.common import fail, load_regions, open_video


def draw_overlay(frame, regions, lit, cols, t):
    """Box each region (green = lit, red = dim), plus a mini grid and the time in the corner."""
    for b, (x, y, w, h) in enumerate(regions):
        colour = (0, 255, 0) if lit[b] else (0, 0, 255)
        cv2.rectangle(frame, (x, y), (x + w, y + h), colour, 3 if lit[b] else 1)
        cv2.putText(frame, str(b), (x + 3, y + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colour, 1, cv2.LINE_AA)

    cell, pad = 14, 8
    for b, is_lit in enumerate(lit):
        r, c = divmod(b, cols)
        x0, y0 = pad + c * (cell + 3), pad + r * (cell + 3)
        cv2.rectangle(frame, (x0, y0), (x0 + cell, y0 + cell), (255, 255, 255), -1 if is_lit else 1)
    rows = (len(lit) + cols - 1) // cols
    cv2.putText(frame, f"{t:7.2f}s", (pad, pad + rows * (cell + 3) + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA)
    return frame


def run(video, song_dir, speed):
    song = load_song(song_dir)
    regions = load_regions(song.regions_path, song.num_blocks)
    if not song.blocks_path.exists():
        fail(f"{song.blocks_path} not found. Run `analyze` first.")
    timeline = Timeline.load(song.blocks_path, song.num_blocks)

    cap = open_video(video)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    delay = max(1, int(1000 / fps / speed))
    print("keys: SPACE pause | a / d  -1s / +1s | , / .  step a frame (paused) | q quit")

    idx, frame, paused = -1, None, False
    jump = None  # frame number to jump to
    step = 0
    while True:
        if frame is None or not paused or jump is not None or step:
            new = jump if jump is not None else idx + (step or 1)
            new = max(0, new)
            if new != idx + 1:
                cap.set(cv2.CAP_PROP_POS_FRAMES, new)
            ok, f = cap.read()
            if not ok:
                break
            frame, idx = f, new
            jump, step = None, 0

        t = idx / fps
        shown = draw_overlay(frame.copy(), regions, timeline.lit_at(t), song.cols, t)
        cv2.imshow("preview", shown)
        key = cv2.waitKey(30 if paused else delay) & 0xFF
        if key in (ord("q"), 27):
            break
        elif key == ord(" "):
            paused = not paused
        elif key == ord("a"):
            jump = max(0, idx - int(fps))
        elif key == ord("d"):
            jump = idx + int(fps)
        elif key == ord(",") and paused:
            step = -1
        elif key == ord(".") and paused:
            step = 1
    cap.release()
    cv2.destroyAllWindows()
