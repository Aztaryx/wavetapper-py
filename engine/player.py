"""Audio playback and the clock. The main loop only ever asks for position()."""
from __future__ import annotations

import time


class Player:
    """Plays an audio file with just_playback; position() is the audio clock."""

    def __init__(self, path):
        from just_playback import Playback  # imported here so tools never need audio libs

        self._pb = Playback()
        self._pb.load_file(str(path))
        self.duration = self._pb.duration

    def start(self):
        self._pb.play()

    def position(self) -> float:
        return self._pb.curr_pos

    def active(self) -> bool:
        return self._pb.active

    def stop(self):
        self._pb.stop()


class SilentPlayer:
    """Same interface, no audio: a wall clock that runs for `duration` seconds."""

    def __init__(self, duration: float):
        self.duration = duration
        self._t0 = None

    def start(self):
        self._t0 = time.perf_counter()

    def position(self) -> float:
        return 0.0 if self._t0 is None else time.perf_counter() - self._t0

    def active(self) -> bool:
        return self._t0 is not None and self.position() < self.duration

    def stop(self):
        pass
