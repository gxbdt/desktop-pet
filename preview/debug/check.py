import math
import sys
import time

import numpy as np
from PIL import Image

sys.path.insert(0, ".")
from pet import motion  # noqa: E402
from pet.sprite import Frame, _sticker_image, render  # noqa: E402


def rigs():
    for n in ["walk", "walk_left", "run", "carry", "sit", "tilt"]:
        im = _sticker_image(n, 2.0)[0]
        r = motion._prepare(n, im)
        legs = r.legs
        msg = ""
        if legs is not None:
            msg = f"len={legs.length:.0f} leg px={len(legs.rows)}"
        tail = None if r.tail is None else (len(r.tail.rows), [round(v) for v in r.tail.pivot])
        print(n, im.size, "tail", tail, msg)


def sheets():
    cases = [("walk", 1), ("walk", -1), ("run", 1), ("sit", 1), ("mark", 1), ("mark", -1)]
    for pose, face in cases:
        tiles = []
        for i in range(4):
            fr = Frame(pose=pose, facing=face, phase=i * math.tau / 4, mark=1.0 if pose == "mark" else 0.0)
            tiles.append(render(fr, 3.0).crop((60, 330, 1020, 1000)))
        w, h = tiles[0].size
        sheet = Image.new("RGBA", (w * 2, h * 2), (30, 30, 34, 255))
        for i, t in enumerate(tiles):
            sheet.alpha_composite(t, ((i % 2) * w, (i // 2) * h))
        sheet.save(f"preview/debug/new_{pose}_{face}.png")


def timing():
    for pose in ("walk", "sit", "run"):
        render(Frame(pose=pose), 1.0)
        t = time.perf_counter()
        for i in range(40):
            render(Frame(pose=pose, phase=i * 0.2), 1.0)
        print(pose, "ms/frame", round((time.perf_counter() - t) / 40 * 1000, 1))


if __name__ == "__main__":
    what = sys.argv[1:] or ["rigs", "sheets", "timing"]
    for name in what:
        globals()[name]()
