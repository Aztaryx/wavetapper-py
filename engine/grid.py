"""Draws the block grid as one ANSI string per frame."""
from __future__ import annotations

import config

RESET = "\033[0m"
HIDE_CURSOR = "\033[?25l"
SHOW_CURSOR = "\033[?25h"
CLEAR = "\033[2J"
HOME = "\033[H"


class Grid:
    def __init__(self, cols: int, rows: int, palette):
        self.cols = cols
        self.rows = rows
        self.palette = palette  # [(dim, lit), ...]
        self.width = cols * config.BLOCK_W + (cols - 1) * config.GAP_X
        self.height = rows * config.BLOCK_H + (rows - 1) * config.GAP_Y

    def fits(self, term_size) -> bool:
        return term_size[0] >= self.width and term_size[1] >= self.height

    def update(self, prev_lit, lit, term_size) -> str:
        """Escape string that redraws only the blocks whose state changed since prev_lit.

        Usually 1-3 blocks change per frame, so this writes a few dozen bytes instead of the
        whole grid, which matters because terminals (Windows ones especially) are the slow part.
        Only valid when the grid fits and the screen already shows prev_lit.
        """
        left = (term_size[0] - self.width) // 2 + 1
        top = (term_size[1] - self.height) // 2 + 1
        parts = []
        for idx in range(self.cols * self.rows):
            if prev_lit[idx] == lit[idx]:
                continue
            row = top + (idx // self.cols) * (config.BLOCK_H + config.GAP_Y)
            col = left + (idx % self.cols) * (config.BLOCK_W + config.GAP_X)
            dim, bright = self.palette[idx]
            colour = bright if lit[idx] else dim
            for dy in range(config.BLOCK_H):
                parts.append(f"\033[{row + dy};{col}H\033[38;5;{colour}m{'#' * config.BLOCK_W}")
        if parts:
            parts.append(RESET)
        return "".join(parts)

    def frame(self, lit, term_size) -> str:
        """Return the escape string that draws the grid centred in the terminal.

        Only block rows are written; gap rows stay blank from the last clear.
        Callers must write CLEAR whenever the terminal size changes.
        """
        term_w, term_h = term_size
        if not self.fits(term_size):
            msg = f"Need {self.width}x{self.height} (have {term_w}x{term_h})"
            return f"{CLEAR}{HOME}{msg[:max(term_w, 1)]}"

        left = (term_w - self.width) // 2 + 1  # cursor positions are 1-based
        top = (term_h - self.height) // 2 + 1
        row_pitch = config.BLOCK_H + config.GAP_Y

        out = []
        for y in range(self.height):
            grid_row, dy = divmod(y, row_pitch)
            if dy >= config.BLOCK_H:
                continue
            parts = [f"\033[{top + y};{left}H"]
            for col in range(self.cols):
                idx = grid_row * self.cols + col
                dim, bright = self.palette[idx]
                colour = bright if lit[idx] else dim
                parts.append(f"\033[38;5;{colour}m{'#' * config.BLOCK_W}{RESET}")
                if col < self.cols - 1:
                    parts.append(" " * config.GAP_X)
            out.append("".join(parts))
        return "".join(out)
