"""侧面的幼年金毛。头大、眼睛圆、腿短，尾巴蓬松地翘起来。"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

LW, LH = 360, 340
GROUND = 308

FUR = (228, 170, 84, 255)
FUR_DARK = (200, 140, 62, 255)
FUR_LIGHT = (246, 208, 138, 255)
FUR_PALE = (255, 236, 206, 255)
EAR = (214, 150, 72, 255)
EAR_IN = (240, 196, 140, 255)
NOSE = (72, 52, 46, 255)
EYE = (110, 68, 40, 255)
EYE_DARK = (54, 34, 26, 255)
BLUSH = (236, 148, 128, 120)
TONGUE = (214, 120, 128, 255)

_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def _font(size: int) -> ImageFont.ImageFont:
    hit = _FONT_CACHE.get(size)
    if hit is not None:
        return hit
    for path in (
        r"C:\Windows\Fonts\msyh.ttc",
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\segoeui.ttf",
    ):
        if os.path.exists(path):
            face = ImageFont.truetype(path, size)
            _FONT_CACHE[size] = face
            return face
    face = ImageFont.load_default()
    _FONT_CACHE[size] = face
    return face


@dataclass
class Frame:
    facing: int = 1
    pose: str = "sit"
    phase: float = 0.0
    pupil: tuple[float, float] = (0.0, 0.0)
    expression: str = "normal"
    bubble: str | None = None
    file_mode: str = "none"  # none, sniff, hold, toss
    file_label: str | None = None
    file_fly: float = 0.0
    hearts: float = 0.0
    zzz: bool = False
    roll: float = 0.0


class Pen:
    """在「面向右」的逻辑坐标里作画，facing < 0 时左右镜像。"""

    def __init__(self, image: Image.Image, scale: int, facing: int):
        self.im = image
        self.d = ImageDraw.Draw(image)
        self.s = scale
        self.facing = 1 if facing >= 0 else -1

    def sx(self, x: float) -> float:
        return x if self.facing > 0 else LW - x

    def _box(self, x0, y0, x1, y1):
        a, b = self.sx(x0), self.sx(x1)
        if a > b:
            a, b = b, a
        s = self.s
        return [a * s, y0 * s, b * s, y1 * s]

    def oval(self, x0, y0, x1, y1, fill):
        self.d.ellipse(self._box(x0, y0, x1, y1), fill=fill)

    def circle(self, cx, cy, r, fill):
        self.oval(cx - r, cy - r, cx + r, cy + r, fill)

    def poly(self, pts, fill):
        s = self.s
        self.d.polygon([(self.sx(x) * s, y * s) for x, y in pts], fill=fill)

    def line(self, a, b, fill, width=2):
        s = self.s
        self.d.line(
            [(self.sx(a[0]) * s, a[1] * s), (self.sx(b[0]) * s, b[1] * s)],
            fill=fill,
            width=max(1, int(width * s)),
        )

    def arc(self, x0, y0, x1, y1, start, end, fill, width=2):
        box = self._box(x0, y0, x1, y1)
        if self.facing < 0:
            start, end = 180 - end, 180 - start
        self.d.arc(box, start, end, fill=fill, width=max(1, int(width * self.s)))

    def text(self, xy, text, fill, size=16, anchor="mm"):
        s = self.s
        self.d.text(
            (xy[0] * s, xy[1] * s),
            text,
            font=_font(max(8, int(size * s))),
            fill=fill,
            anchor=anchor,
        )


def _gait(pose: str, phase: float) -> dict:
    bob = math.sin(phase * 2.0)
    if pose == "walk":
        return dict(bob=bob * 2.6, lift=math.sin(phase), wag=math.sin(phase * 6) * 14, ear=math.sin(phase) * 2)
    if pose == "run":
        return dict(bob=bob * 3.8, lift=math.sin(phase), wag=math.sin(phase * 11) * 18, ear=4, lean=8)
    if pose == "sniff":
        return dict(bob=bob * 0.6, lift=math.sin(phase) * 0.2, wag=math.sin(phase * 5) * 6, ear=1, nose=math.sin(phase * 9) * 2)
    if pose == "dig":
        return dict(bob=abs(math.sin(phase * 2)) * 1.4, lift=math.sin(phase * 2.2), wag=math.sin(phase * 8) * 8, ear=1)
    if pose == "held":
        return dict(bob=math.sin(phase * 3) * 2, lift=math.sin(phase * 3), wag=math.sin(phase * 5) * 12, ear=2, dy=-46)
    if pose == "sleep":
        return dict(bob=math.sin(phase) * 1.0, lift=0, wag=math.sin(phase) * 3, ear=0)
    return dict(bob=math.sin(phase * 2) * 1.1, lift=0, wag=math.sin(phase * 4.5) * 12, ear=math.sin(phase * 4) * 1.5)


def _leg(pen: Pen, x, top, bottom, width, color):
    """短而圆的腿，脚掌是一个圆。"""
    bottom = max(bottom, top + width * 2)
    pen.oval(x - width, top, x + width * 0.9, bottom - width * 0.15, color)
    pen.oval(x - width * 1.35, bottom - width * 1.35, x + width * 1.45, bottom + 3, color)


def _plume(pen: Pen, x, y, wag, reach=1.0):
    """往后上方卷起的一团毛。"""
    steps = ((0, 6, 17), (-14, -4, 16), (-20, -20, 15), (-12, -34, 14), (0, -42, 12))
    for i, (dx, dy, radius) in enumerate(steps):
        sway = wag * (0.1 + i * 0.16)
        pen.circle(x + dx * reach, y + dy * reach - sway, radius * reach, FUR_LIGHT if i == 4 else FUR)


def _eye(pen: Pen, cx, cy, pupil, expression):
    px = max(-1.0, min(1.0, pupil[0])) * 2.0
    py = max(-1.0, min(1.0, pupil[1])) * 1.3
    if expression == "closed":
        pen.arc(cx - 12, cy - 3, cx + 13, cy + 11, 205, 345, EYE_DARK, width=3.0)
        return
    radius = 8.6 if expression == "happy" else 10.2
    pen.circle(cx, cy, radius, (255, 252, 248, 255))
    pen.circle(cx + px * 0.3, cy + py * 0.2, radius * 0.76, EYE)
    pen.circle(cx + px * 0.4, cy + 1.0 + py * 0.15, radius * 0.4, EYE_DARK)
    pen.circle(cx - radius * 0.32, cy - radius * 0.34, radius * 0.24, (255, 255, 255, 245))


def _head(pen: Pen, hx, hy, frame: Frame, ear_drop=0, nose_wiggle=0, lowered=False):
    """圆脑袋、垂耳、短吻。眼睛占了脸的很大一块。"""
    pen.oval(hx - 52, hy - 22 + ear_drop, hx + 2, hy + 40, EAR)
    pen.oval(hx - 42, hy - 8 + ear_drop, hx - 8, hy + 28, EAR_IN)

    pen.circle(hx, hy, 40, FUR)
    pen.oval(hx - 24, hy - 32, hx + 2, hy - 10, FUR_LIGHT)

    muzzle_y = hy + (18 if lowered else 12)
    pen.oval(hx + 6, muzzle_y - 18, hx + 42 + nose_wiggle, muzzle_y + 16, FUR)
    pen.oval(hx + 12, muzzle_y - 2, hx + 40 + nose_wiggle, muzzle_y + 16, FUR_PALE)

    nx = hx + 38 + nose_wiggle
    ny = muzzle_y - 4
    pen.circle(nx, ny, 7.2, NOSE)
    pen.circle(nx - 2.4, ny - 2.4, 2.1, (255, 255, 255, 210))

    _eye(pen, hx + 1, hy - 8, frame.pupil, frame.expression)
    pen.oval(hx + 8, hy + 8, hx + 24, hy + 16, BLUSH)

    if frame.file_mode in ("hold", "toss"):
        pen.oval(nx - 12, ny + 5, nx - 2, ny + 13, (120, 68, 60, 255))
    else:
        pen.arc(hx + 16, muzzle_y + 2, hx + 34, muzzle_y + 16, 20, 160, (176, 114, 78, 255), width=1.8)
    return hx, hy, nx, ny


def _draw_dog(pen: Pen, frame: Frame) -> tuple[float, float, float, float]:
    g = _gait(frame.pose, frame.phase)
    g.setdefault("lean", 0)
    g.setdefault("nose", 0)
    g.setdefault("dy", 0)
    bob = g["bob"]
    pose = frame.pose
    ground = GROUND + g["dy"]

    if pose == "sleep":
        bx, by = 162, 262 + bob
        _plume(pen, bx - 72, by - 4, g["wag"] * 0.2, 0.7)
        pen.oval(bx - 78, by - 32, bx + 58, by + 38, FUR)
        pen.oval(bx - 8, by - 4, bx + 40, by + 28, FUR_PALE)
        pen.circle(bx + 46, by + 14, 16, FUR)
        return _head(pen, bx + 72, by - 10, frame, ear_drop=14, lowered=True)

    if pose in ("walk", "run", "sniff", "dig"):
        stretch = 8 if pose == "run" else 0
        drop = 20 if pose == "sniff" else (8 if pose == "dig" else 0)
        bx, by = 152, 216 + bob
        lift_a = max(0.0, g["lift"]) * (14 if pose == "run" else 9)
        lift_b = max(0.0, -g["lift"]) * (14 if pose == "run" else 9)
        _plume(pen, bx - 48, by - 4, g["wag"], 0.92)
        _leg(pen, bx - 30, by + 8, ground - lift_b, 12, FUR)
        _leg(pen, bx - 8, by + 12, ground - lift_a, 12, FUR)
        pen.oval(bx - 58, by - 34, bx + 46 + stretch, by + 32, FUR)
        pen.oval(bx + 14, by - 16, bx + 42, by + 6, FUR_PALE)
        _leg(pen, bx + 14, by + 4, ground - lift_a, 12, FUR)
        scratch = max(0.0, g["lift"]) * 12 if pose == "dig" else 0
        reach = 8 if pose == "sniff" else 0
        _leg(pen, bx + 36 + reach, by + 2, ground - lift_b - scratch, 12, FUR)
        hx = bx + 52 + (12 if pose == "sniff" else 0)
        hy = by - 50 + drop
        pen.circle(bx + 30, by - 18, 22, FUR)
        return _head(pen, hx, hy, frame, ear_drop=g["ear"], nose_wiggle=g["nose"], lowered=pose == "sniff")

    bx, by = 150, 226 + bob + g["dy"]
    _plume(pen, bx - 22, by - 4, g["wag"], 0.95)
    pen.oval(bx - 40, by - 6, bx + 24, ground + 4, FUR)
    pen.oval(bx + 2, by - 46, bx + 60, by + 26, FUR)
    pen.oval(bx + 20, by - 22, bx + 50, by + 6, FUR_PALE)
    pen.circle(bx + 26, by - 34, 20, FUR)
    if pose == "held":
        swing = g["lift"] * 5
        _leg(pen, bx + 22, by + 4, by + 58, 12, FUR)
        _leg(pen, bx + 46 + swing, by + 8, by + 66, 12, FUR_LIGHT)
    else:
        _leg(pen, bx + 24, by + 16, ground, 13, FUR)
        _leg(pen, bx + 48, by + 18, ground + 1, 12, FUR)
    return _head(pen, bx + 46, by - 60, frame, ear_drop=g["ear"])


def _file_icon(draw: ImageDraw.ImageDraw, scale: int, x, y, alpha=255, icon_scale=1.0):
    a = max(0, min(255, int(alpha)))
    s = scale
    w, h = 22 * icon_scale, 28 * icon_scale

    def X(v):
        return v * s

    def box(x0, y0, x1, y1):
        return [X(x0), y0 * s, X(x1), y1 * s]

    draw.rounded_rectangle(box(x, y, x + w, y + h), radius=2 * s, fill=(255, 253, 248, a), outline=(176, 148, 114, a), width=max(1, s))
    draw.polygon(
        [(X(x + w - 8), y * s), (X(x + w - 8), (y + 8) * s), (X(x + w), (y + 8) * s)],
        fill=(228, 210, 186, a),
    )
    ink = (132, 122, 112, a)
    for i in range(3):
        yy = y + 13 + i * 4.5
        draw.line([(X(x + 4), yy * s), (X(x + w - 5), yy * s)], fill=ink, width=max(1, int(s)))


def _bubble(draw: ImageDraw.ImageDraw, scale: int, text: str, anchor):
    s = scale
    font = _font(int(15 * s))
    raw = draw.textlength(text, font=font) / s
    tw = max(40, raw + 20)
    th = 28
    ax, ay = anchor
    x = min(max(8, ax - tw / 2), LW - tw - 8)
    y = max(6, ay - th - 14)
    draw.rounded_rectangle(
        [x * s, y * s, (x + tw) * s, (y + th) * s],
        radius=10 * s,
        fill=(255, 250, 242, 238),
    )
    draw.polygon(
        [((ax - 6) * s, (y + th - 1) * s), ((ax + 6) * s, (y + th - 1) * s), (ax * s, (y + th + 8) * s)],
        fill=(255, 250, 242, 238),
    )
    draw.text(((x + tw / 2) * s, (y + th / 2) * s), text, font=font, fill=(92, 62, 36, 255), anchor="mm")


def _ui(base: Image.Image, scale: int, frame: Frame, hx, hy, nx, ny, facing: int):
    """气泡、爱心、文件图标用屏幕坐标画，避免文字被镜像。"""
    draw = ImageDraw.Draw(base)
    head_x = hx if facing > 0 else LW - hx
    nose_x = nx if facing > 0 else LW - nx
    sign = 1 if facing > 0 else -1

    if frame.zzz:
        for i, ch in enumerate("zZ"):
            t = (frame.phase * 0.35 + i * 0.38) % 1.0
            alpha = int(210 * (1 - t))
            draw.text(
                ((head_x + sign * (36 + t * 16)) * scale, (hy - 24 - t * 32) * scale),
                ch,
                font=_font(int((15 + i * 3) * scale)),
                fill=(255, 255, 255, alpha),
                anchor="mm",
            )

    if frame.hearts > 0:
        t = 1 - frame.hearts
        for i in range(3):
            local = min(1.0, max(0.0, t * 1.15 - i * 0.12))
            alpha = int(255 * (1 - local))
            if alpha <= 0:
                continue
            cx = head_x - 12 + i * 14
            cy = hy - 62 - local * 36
            r = 5.5
            col = (228, 92, 110, alpha)
            draw.ellipse([((cx - r) * scale), ((cy - r) * scale), ((cx + r * 0.15) * scale), ((cy + r * 0.2) * scale)], fill=col)
            draw.ellipse([((cx - r * 0.15) * scale), ((cy - r) * scale), ((cx + r) * scale), ((cy + r * 0.2) * scale)], fill=col)
            draw.polygon(
                [(cx - r) * scale, cy * scale, (cx + r) * scale, cy * scale, cx * scale, (cy + r * 1.35) * scale],
                fill=col,
            )

    label = frame.bubble
    if label is None and frame.file_label and frame.file_mode in ("sniff", "hold"):
        label = frame.file_label
    if label and frame.file_mode != "toss":
        _bubble(draw, scale, label, (head_x, hy - 52))
    elif frame.bubble:
        _bubble(draw, scale, frame.bubble, (head_x, hy - 52))

    if frame.file_mode == "none":
        return
    fly = frame.file_fly if frame.file_mode == "toss" else 0.0
    alpha = 255 if fly < 0.72 else int(255 * (1 - (fly - 0.72) / 0.28))
    if frame.file_mode == "sniff":
        _file_icon(draw, scale, nose_x + sign * 14, ny - 10, alpha=220, icon_scale=0.82)
    else:
        ox = sign * (10 + fly * 48)
        oy = 4 - math.sin(min(1.0, fly) * math.pi) * 52
        _file_icon(draw, scale, nose_x - 12 + ox, ny - 2 + oy, alpha=alpha, icon_scale=1.0)


def render(frame: Frame, pixel_scale: float = 1.0) -> Image.Image:
    scale = 2
    canvas = Image.new("RGBA", (LW * scale, LH * scale), (0, 0, 0, 0))

    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    held = frame.pose == "held"
    sw = (86 if not held else 50) * scale
    sh = (15 if not held else 9) * scale
    scx, scy = (LW / 2) * scale, (GROUND - 4) * scale
    sd.ellipse([scx - sw, scy - sh, scx + sw, scy + sh], fill=(92, 62, 32, 36 if held else 58))
    canvas.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(radius=6)))

    dog = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    pen = Pen(dog, scale, frame.facing)
    hx, hy, nx, ny = _draw_dog(pen, frame)
    if abs(frame.roll) > 0.5:
        dog = dog.rotate(-frame.roll * frame.facing, resample=Image.Resampling.BICUBIC, center=(LW * scale / 2, (LH * 0.58) * scale))
    canvas.alpha_composite(dog)
    _ui(canvas, scale, frame, hx, hy, nx, ny, frame.facing)

    out_w = max(1, int(round(LW * pixel_scale)))
    out_h = max(1, int(round(LH * pixel_scale)))
    if canvas.size != (out_w, out_h):
        canvas = canvas.resize((out_w, out_h), Image.Resampling.LANCZOS)
    return canvas


def to_bgra_premul(image: Image.Image) -> bytes:
    im = image.convert("RGBA")
    r, g, b, a = im.split()
    r = ImageChops.multiply(r, a)
    g = ImageChops.multiply(g, a)
    b = ImageChops.multiply(b, a)
    return Image.merge("RGBA", (b, g, r, a)).tobytes()


def save_previews(folder: str) -> None:
    os.makedirs(folder, exist_ok=True)
    samples = [
        ("sit", Frame(pose="sit", expression="normal", bubble="汪")),
        ("walk", Frame(pose="walk", phase=1.1)),
        ("run", Frame(pose="run", phase=0.7, expression="happy")),
        ("sleep", Frame(pose="sleep", expression="closed", zzz=True, phase=0.5)),
        ("sniff", Frame(pose="sniff", file_mode="sniff", file_label="照片.jpg", phase=0.4)),
        ("carry", Frame(pose="run", file_mode="hold", file_label="照片.jpg", expression="happy", phase=0.5)),
        ("toss", Frame(pose="sit", file_mode="toss", file_fly=0.4, bubble="还给你", expression="happy")),
        ("held", Frame(pose="held", expression="happy", phase=0.6)),
        ("left", Frame(pose="walk", facing=-1, phase=2.1, pupil=(0.3, 0.1))),
        ("happy", Frame(pose="sit", expression="happy", hearts=0.55, bubble="嘿嘿")),
    ]
    sheet = Image.new("RGBA", (LW * 5, LH * 2), (214, 206, 196, 255))
    for i, (name, frame) in enumerate(samples):
        im = render(frame, 1.0)
        bg = Image.new("RGBA", im.size, (214, 206, 196, 255))
        bg.alpha_composite(im)
        bg.convert("RGB").save(os.path.join(folder, f"{name}.png"), quality=95)
        sheet.alpha_composite(im, ((i % 5) * LW, (i // 5) * LH))
    sheet.convert("RGB").save(os.path.join(folder, "sheet.png"), quality=90)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(__file__)), "preview")
    save_previews(out)
    print(out)
