"""Engine defaults. A song's song.json can override the grid and palette."""

GRID_COLS = 4
GRID_ROWS = 4
BLOCK_W = 2   # '#' characters per block, across
BLOCK_H = 2   # rows per block, down
GAP_X = 2     # empty columns between blocks
GAP_Y = 1     # empty rows between blocks
FPS = 30

# (dim, lit) 256-colour codes, roughly matched to the reference image.
DEFAULT_PALETTE = [
    (52, 196),    # red
    (94, 208),    # orange-brown
    (100, 226),   # olive yellow
    (64, 118),    # olive green
    (22, 46),     # green
    (28, 34),     # dark green
    (23, 43),     # teal
    (30, 51),     # cyan teal
    (17, 27),     # navy
    (18, 33),     # blue
    (19, 21),     # deep blue
    (54, 129),    # purple
    (53, 165),    # magenta purple
    (88, 197),    # maroon
    (236, 250),   # dark grey
    (244, 255),   # light grey
]
