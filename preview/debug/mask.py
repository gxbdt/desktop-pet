import sys

import numpy as np
from PIL import Image, ImageFilter

sys.path.insert(0, ".")
from pet import motion  # noqa: E402
from pet.sprite import _sticker_image  # noqa: E402

tiles = []
for n in ["walk", "walk_left", "run", "carry", "sit", "tilt"]:
    im = _sticker_image(n, 2.0)[0]
    mask = motion._tail_mask(im, motion._RIGS[n])
    vis = Image.new("RGBA", im.size, (30, 30, 34, 255))
    vis.alpha_composite(im)
    if mask is not None:
        red = Image.new("RGBA", im.size, (255, 0, 80, 150))
        vis.paste(red, (0, 0), Image.fromarray((mask * 255).astype(np.uint8)))
        print(n, int(mask.sum()))
    tiles.append(vis)
w = max(t.width for t in tiles)
h = max(t.height for t in tiles)
sheet = Image.new("RGBA", (w * 3, h * 2), (30, 30, 34, 255))
for i, t in enumerate(tiles):
    sheet.alpha_composite(t, ((i % 3) * w, (i // 3) * h))
sheet.save("preview/debug/masks.png")
