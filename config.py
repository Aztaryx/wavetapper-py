"""Engine defaults. A song's song.json can override the grid and palette."""

GRID_COLS = 4
GRID_ROWS = 4
BLOCK_W = 4   # '#' characters per block, across
BLOCK_H = 4   # rows per block, down
GAP_X = 2     # empty columns between blocks
GAP_Y = 1     # empty rows between blocks
FPS = 30

# (dim, lit) 256-colour codes. Every block is the same grey when unlit (DIM_GREY) so that the
# lit colours stand out; the lit colours are roughly matched to the reference image.
# Greys run from 232 (almost black) to 255 (almost white): try 238 for darker, 244 for lighter.
DIM_GREY = 240

DEFAULT_PALETTE = [
    (DIM_GREY, 196),      # red
    (DIM_GREY, 208),      # orange-brown
    (DIM_GREY, 226),      # olive yellow
    (DIM_GREY, 118),      # olive green
    (DIM_GREY, 46),       # green
    (DIM_GREY, 34),       # dark green
    (DIM_GREY, 43),       # teal
    (DIM_GREY, 51),       # cyan teal
    (DIM_GREY, 27),       # navy
    (DIM_GREY, 33),       # blue
    (DIM_GREY, 21),       # deep blue
    (DIM_GREY, 129),      # purple
    (DIM_GREY, 165),      # magenta purple
    (DIM_GREY, 197),      # maroon
    (DIM_GREY, 250),      # dark grey
    (DIM_GREY, 255),      # light grey
]