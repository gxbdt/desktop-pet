"""金毛幼犬的画法：大圆脑袋、垂耳、奶油色吻部和胸毛、蓬松的尾巴，卡通描边。

所有身体部件都按「面朝右」画在逻辑坐标里，最后整张镜像；文字和图标在镜像之后再画。
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

from pet.motion import animate_sticker, stream_fracs

LW, LH = 360, 340
GROUND = 308

# 概念图配色：奶金色底毛、蜂蜜色阴影、奶油色胸毛和暖棕色轮廓。
FUR = (235, 174, 89, 255)
FUR_SHADE = (202, 131, 61, 255)
FUR_DEEP = (176, 105, 48, 255)
FUR_LIGHT = (255, 216, 143, 255)
TAIL_LIGHT = (247, 198, 119, 255)
TAIL_SHADE = (220, 157, 80, 255)
CREAM = (255, 232, 184, 255)
CREAM_SHADE = (239, 199, 137, 255)
EAR = (202, 133, 62, 255)
EAR_SHADE = (176, 105, 48, 255)
EAR_LIGHT = (231, 165, 87, 255)
OUTLINE = (139, 85, 43, 255)
NOSE = (77, 47, 35, 255)
EYE = (55, 32, 20, 255)
EYE_RING = (133, 77, 35, 255)
MOUTH = (124, 46, 44, 255)
TONGUE = (244, 120, 132, 255)
TONGUE_LINE = (214, 88, 104, 255)
BLUSH = (248, 160, 122, 210)
TOE = (176, 116, 62, 255)

STROKE = 2.1

# Figma 贴纸素材：按动作选用，阴影中心对准脚下 (180, GROUND)。
_STICKER_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "figma-assets")
# 名称 -> (文件, 逻辑高度, 阴影中心比例, 头中心比例, 鼻尖比例)，比例均为导出图的宽高分数。
_STICKER_META = {
    "sit":       ("sit_attentive.png",    205, (0.551, 0.952), (0.560, 0.262), (0.560, 0.360)),
    "tilt":      ("tilt_smile.png",       205, (0.488, 0.955), (0.534, 0.330), (0.534, 0.430)),
    "walk":      ("walk_side.png",        175, (0.441, 0.950), (0.638, 0.303), (0.639, 0.415)),
    "walk_left": ("left_facing.png",      175, (0.543, 0.950), (0.338, 0.330), (0.340, 0.430)),
    "run":       ("stand_playful.png",    180, (0.426, 0.951), (0.624, 0.300), (0.641, 0.425)),
    "sniff":     ("sniff_inquisitive.png", 150, (0.408, 0.937), (0.634, 0.467), (0.652, 0.600)),
    "eat":       ("eat_bone.png",         130, (0.436, 0.934), (0.661, 0.480), (0.700, 0.620)),
    "sleep":     ("sleep_curled.png",     120, (0.433, 0.942), (0.653, 0.566), (0.680, 0.600)),
    "held":      ("held_dangling.png",    225, (0.489, 0.955), (0.500, 0.268), (0.500, 0.380)),
    "hop":       ("hop_begging.png",      215, (0.492, 0.959), (0.505, 0.328), (0.505, 0.440)),
    "pat":       ("pat_headpats.png",     215, (0.504, 0.955), (0.522, 0.394), (0.522, 0.490)),
    "carry":     ("carry_document.png",   175, (0.437, 0.949), (0.634, 0.302), (0.635, 0.415)),
}
_STICKER_CACHE: dict[tuple[str, float], tuple | None] = {}


def _sticker_image(name: str, ss: float):
    """加载并缓存贴纸。返回 (图, 左, 顶, 头x, 头y, 鼻x, 鼻y)，坐标为面朝右的逻辑坐标。"""
    key = (name, ss)
    if key in _STICKER_CACHE:
        return _STICKER_CACHE[key]
    fname, h_logic, sfrac, ffrac, nfrac = _STICKER_META[name]
    path = os.path.join(_STICKER_DIR, fname)
    entry = None
    if os.path.exists(path):
        src = Image.open(path).convert("RGBA")
        w_logic = src.width / src.height * h_logic
        im = src.resize((max(1, round(w_logic * ss)), max(1, round(h_logic * ss))), Image.Resampling.LANCZOS)
        left_l = LW / 2 - sfrac[0] * w_logic
        top_l = GROUND - sfrac[1] * h_logic
        entry = (
            im, left_l, top_l,
            left_l + ffrac[0] * w_logic, top_l + ffrac[1] * h_logic,
            left_l + nfrac[0] * w_logic, top_l + nfrac[1] * h_logic,
        )
    _STICKER_CACHE[key] = entry
    return entry


def _pick_sticker(frame: Frame) -> str | None:
    pose = frame.pose
    if pose in ("walk", "mark"):
        return "walk_left" if frame.facing < 0 else "walk"
    if pose == "sit":
        return "tilt" if frame.expression in ("happy", "joy") else "sit"
    if pose == "run":
        return "carry" if frame.file_mode in ("hold",) else "run"
    if pose == "dig":
        return "eat"
    if pose in ("sniff", "eat", "sleep", "held", "hop", "pat"):
        return pose
    return None

# 嗅闻时鼻尖相对于脚下中心点的位置，dog.py 用它把鼻子凑到文件夹上。
SNIFF_NOSE = (54, -51)

_SRC_SIZE: dict[str, tuple[int, int]] = {}


def _src_size(name: str) -> tuple[int, int]:
    hit = _SRC_SIZE.get(name)
    if hit is not None:
        return hit
    with Image.open(os.path.join(_STICKER_DIR, _STICKER_META[name][0])) as im:
        _SRC_SIZE[name] = im.size
    return _SRC_SIZE[name]


def layout_point(name: str, frac: tuple[float, float]) -> tuple[float, float]:
    """原图上的比例点，换成面朝右画布里的逻辑坐标（还没镜像）。"""
    _fname, h_logic, sfrac, *_rest = _STICKER_META[name]
    sw, sh = _src_size(name)
    w_logic = sw / sh * h_logic
    left = LW / 2 - sfrac[0] * w_logic
    top = GROUND - sfrac[1] * h_logic
    return left + frac[0] * w_logic, top + frac[1] * h_logic


def mark_anchor(facing: int) -> tuple[float, float]:
    """尿柱落点相对脚下中心的偏移（逻辑像素，x 已经是屏幕方向）。"""
    name = "walk" if facing > 0 else "walk_left"
    fr = stream_fracs(name)
    if fr is None:
        return (-70.0 * facing, -4.0)
    x, y = layout_point(name, fr[1])
    return x - LW / 2, y - GROUND

_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}
_SHADOW_CACHE: dict[tuple, Image.Image] = {}


def _font(size: int) -> ImageFont.ImageFont:
    hit = _FONT_CACHE.get(size)
    if hit is not None:
        return hit
    for path in (
        r"C:\Windows\Fonts\msyhbd.ttc",
        r"C:\Windows\Fonts\msyh.ttc",
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
    pose: str = "sit"  # sit walk run sniff dig eat sleep held hop pat
    phase: float = 0.0
    pupil: tuple[float, float] = (0.0, 0.0)
    expression: str = "normal"  # normal happy joy closed curious
    bubble: str | None = None
    file_mode: str = "none"  # none, sniff, hold, toss
    file_label: str | None = None
    file_kind: str = "file"  # file folder
    file_fly: float = 0.0
    hearts: float = 0.0
    love: float = 0.0
    sparkle: float = 0.0
    question: float = 0.0
    zzz: bool = False
    roll: float = 0.0
    tilt: float = 0.0
    pat: float = -1.0
    treat: float = -1.0
    clock: float = 0.0
    mark: float = 0.0  # 0..1，抬后腿标记
    stride: float = 0.0  # 按走过的距离推进的步态相位
    lean: float = 0.0  # -1 起步后坐，+1 停步前倾
    step_scale: float = 1.0  # 小于 1 时换成步幅更短的一套关键帧
    planted: bool = False  # 双脚着地的停步帧，不播走路循环


class Sketch:
    """先记下所有形状，再画两遍：一遍加粗的描边色剪影，一遍填色。"""

    SOLID = ("oval", "capsule", "poly")

    def __init__(self):
        self.ops: list[tuple] = []

    def oval(self, x0, y0, x1, y1, fill, sep=False):
        self.ops.append(("oval", (x0, y0, x1, y1), fill, sep))

    def circle(self, cx, cy, r, fill, sep=False):
        self.oval(cx - r, cy - r, cx + r, cy + r, fill, sep)

    def capsule(self, a, b, r, fill, sep=False):
        self.ops.append(("capsule", (a, b, r), fill, sep))

    def poly(self, pts, fill, sep=False):
        self.ops.append(("poly", list(pts), fill, sep))

    def spot(self, x0, y0, x1, y1, fill):
        """没有描边的色块，比如高光、腮红。"""
        self.ops.append(("spot", (x0, y0, x1, y1), fill, False))

    def flat(self, pts, fill):
        self.ops.append(("flat", list(pts), fill, False))

    def line(self, pts, fill, width=2.0):
        self.ops.append(("line", (list(pts), width), fill, False))

    def arc(self, box, start, end, fill, width=2.0):
        self.ops.append(("arc", (box, start, end, width), fill, False))

    def paint(self, image: Image.Image, ss: float, dx: float = 0.0, dy: float = 0.0, rot: float = 0.0) -> None:
        """rot 为绕局部原点的旋转角（度），直接变换坐标，不做栅格旋转。"""
        d = ImageDraw.Draw(image)
        turn = abs(rot) > 0.2
        ca, sa = math.cos(math.radians(rot)), math.sin(math.radians(rot))

        def P(x, y):
            if turn:
                x, y = x * ca - y * sa, x * sa + y * ca
            return ((x + dx) * ss, (y + dy) * ss)

        def B(x0, y0, x1, y1, grow=0.0):
            a, b = P(x0 - grow, y0 - grow)
            c, e = P(x1 + grow, y1 + grow)
            return [a, b, c, e]

        def ellipse_pts(x0, y0, x1, y1, grow=0.0, start=0.0, end=360.0, n=40):
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            rx, ry = (x1 - x0) / 2 + grow, (y1 - y0) / 2 + grow
            span = end - start
            steps = max(6, int(n * span / 360))
            pts = []
            for i in range(steps + (0 if span >= 360 else 1)):
                a = math.radians(start + span * i / steps)
                pts.append(P(cx + rx * math.cos(a), cy + ry * math.sin(a)))
            return pts

        def oval(box, fill, grow=0.0):
            if turn:
                d.polygon(ellipse_pts(*box, grow=grow), fill=fill)
            else:
                d.ellipse(B(*box, grow=grow), fill=fill)

        def solid(kind, args, fill, grow):
            if kind == "oval":
                oval(args, fill, grow)
            elif kind == "capsule":
                (ax, ay), (bx, by), r = args
                r += grow
                d.line([P(ax, ay), P(bx, by)], fill=fill, width=max(1, int(round(2 * r * ss))))
                for x, y in ((ax, ay), (bx, by)):
                    px, py = P(x, y)
                    d.ellipse([px - r * ss, py - r * ss, px + r * ss, py + r * ss], fill=fill)
            elif kind == "poly":
                pts = [P(x, y) for x, y in args]
                d.polygon(pts, fill=fill)
                if grow > 0:
                    w = max(1, int(round(2 * grow * ss)))
                    d.line(pts + [pts[0]], fill=fill, width=w, joint="curve")

        for kind, args, fill, sep in self.ops:
            if kind in self.SOLID:
                solid(kind, args, OUTLINE, STROKE)
        for kind, args, fill, sep in self.ops:
            if kind in self.SOLID:
                if sep:
                    solid(kind, args, OUTLINE, STROKE)
                solid(kind, args, fill, 0.0)
            elif kind == "spot":
                oval(args, fill)
            elif kind == "flat":
                d.polygon([P(x, y) for x, y in args], fill=fill)
            elif kind in ("line", "arc"):
                if kind == "line":
                    pts, width = args
                    pts = [P(x, y) for x, y in pts]
                else:
                    box, start, end, width = args
                    pts = ellipse_pts(*box, start=start, end=end, n=48)
                w = max(1, int(round(width * ss)))
                d.line(pts, fill=fill, width=w, joint="curve")
                r = width * ss / 2
                for x, y in (pts[0], pts[-1]):
                    d.ellipse([x - r, y - r, x + r, y + r], fill=fill)


def _rot(px, py, cx, cy, deg):
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    x, y = px - cx, py - cy
    return cx + x * c - y * s, cy + x * s + y * c


def _teardrop(top_x, top_y, length, width, angle, steps=28):
    """上窄下圆的水滴形，用来画垂耳。angle 为相对竖直向下的偏转（度）。"""
    pts = []
    for i in range(steps):
        t = i / (steps - 1) * math.pi * 2
        # y 从 0 到 length，半宽在下部最大
        u = (1 - math.cos(t)) / 2
        y = u * length
        half = width / 2 * math.sin(math.pi * min(1.0, u ** 0.8)) ** 0.85
        if u > 0.62:
            k = (u - 0.62) / 0.38
            half = width / 2 * math.sqrt(max(0.0, 1 - k * k)) * 1.0
        x = half if t <= math.pi else -half
        pts.append(_rot(top_x + x, top_y + y, top_x, top_y, angle))
    return pts


def _bezier(p0, p1, p2, t):
    a = (1 - t) ** 2
    b = 2 * (1 - t) * t
    c = t * t
    return a * p0[0] + b * p1[0] + c * p2[0], a * p0[1] + b * p1[1] + c * p2[1]


def _tail(sk: Sketch, base, ctrl, tip, wag, r0=12.0, r1=7.0, feather=1.0):
    """柔软的羽状尾：平滑主轴、两处轻毛簇和顺着曲线渐隐的明暗。wag 为摆动角度。"""
    ctrl = _rot(*ctrl, *base, wag * 0.6)
    tip = _rot(*tip, *base, wag)
    n = 40
    left, right, centers, normals, radii = [], [], [], [], []
    for i in range(n + 1):
        t = i / n
        x, y = _bezier(base, ctrl, tip, t)
        x2, y2 = _bezier(base, ctrl, tip, min(1.0, t + 0.015))
        x1, y1 = _bezier(base, ctrl, tip, max(0.0, t - 0.015))
        dx, dy = x2 - x1, y2 - y1
        norm = math.hypot(dx, dy) or 1
        nx, ny = -dy / norm, dx / norm
        r = r0 + (r1 - r0) * t
        r *= 0.90 + 0.12 * math.sin(math.pi * t)
        if t > 0.80:
            r *= math.sqrt(max(0.0, 1 - ((t - 0.80) / 0.20) ** 2))

        # 只保留两三个轻柔毛簇，避免连续正弦波造成生硬的锯齿和分节感。
        outer = feather * (
            0.16 * math.exp(-((t - 0.42) / 0.075) ** 2)
            + 0.13 * math.exp(-((t - 0.66) / 0.085) ** 2)
        )
        inner = feather * 0.065 * math.exp(-((t - 0.57) / 0.11) ** 2)
        left.append((x + nx * r * (1 + outer), y + ny * r * (1 + outer)))
        right.append((x - nx * r * (1 + inner), y - ny * r * (1 + inner)))
        centers.append((x, y))
        normals.append((nx, ny))
        radii.append(r)

    sk.poly(left + right[::-1], FUR)

    # 阴影贴着内缘，高光沿毛流方向逐渐变细，不再横跨尾巴形成条纹。
    shade_a, shade_b, light_a, light_b = [], [], [], []
    for i in range(4, n - 4):
        t = i / n
        fade = math.sin(math.pi * (t - 0.10) / 0.80) ** 0.7
        x, y = centers[i]
        nx, ny = normals[i]
        r = radii[i]
        shade_a.append((x - nx * r * 0.48, y - ny * r * 0.48))
        shade_b.append((x - nx * r * (0.48 + 0.22 * fade), y - ny * r * (0.48 + 0.22 * fade)))
        light_a.append((x + nx * r * 0.12, y + ny * r * 0.12))
        light_b.append((x + nx * r * (0.12 + 0.34 * fade), y + ny * r * (0.12 + 0.34 * fade)))
    sk.flat(shade_a + shade_b[::-1], TAIL_SHADE)
    sk.flat(light_a + light_b[::-1], TAIL_LIGHT)

    # 两笔很短的顺向毛流，只补充细节，不切断尾巴的整体体积。
    for i in (20, 28):
        x, y = centers[i]
        nx, ny = normals[i]
        r = radii[i]
        x0, y0 = centers[i - 2]
        x1, y1 = centers[i + 2]
        sk.line([
            (x0 + nx * r * 0.30, y0 + ny * r * 0.30),
            (x + nx * r * 0.40, y + ny * r * 0.40),
            (x1 + nx * r * 0.28, y1 + ny * r * 0.28),
        ], FUR_LIGHT, 1.15)


def _paw(sk: Sketch, cx, ground, w=18.0, fill=FUR, toes=True):
    sk.oval(cx - w, ground - 16, cx + w, ground + 1, fill, sep=True)
    if fill == FUR:
        sk.spot(cx - w * 0.66, ground - 13, cx + w * 0.18, ground - 8, FUR_LIGHT)
    if toes:
        for k in (-0.34, 0.0, 0.34):
            x = cx + w * k + w * 0.08
            sk.line([(x, ground - 6), (x, ground - 1)], TOE, 1.45)


def _leg(sk: Sketch, hip, foot_x, ground, r=10.0, fill=FUR, sep=True, toes=True, paw_w=15.0):
    sk.capsule(hip, (foot_x, ground - 10), r, fill, sep=sep)
    _paw(sk, foot_x + 3, ground, paw_w, fill, toes)


def _gait(pose: str, phase: float) -> dict:
    if pose == "walk":
        return dict(bob=math.sin(phase * 2) * 1.15, swing=math.sin(phase), wag=math.sin(phase * 2.2) * 16, ear=math.sin(phase * 2) * 3)
    if pose == "mark":
        return dict(bob=math.sin(phase * 1.5) * 0.5, swing=0.0, wag=math.sin(phase * 1.8) * 14, ear=2)
    if pose == "run":
        return dict(bob=-abs(math.sin(phase)) * 9, swing=math.sin(phase), wag=math.sin(phase * 3) * 20, ear=10 + math.sin(phase * 2) * 6)
    if pose in ("sniff", "eat"):
        return dict(bob=math.sin(phase * 0.8) * 0.8, swing=0.0, wag=math.sin(phase * 1.6) * 18, ear=-4, nose=math.sin(phase * 9) * 1.4)
    if pose == "dig":
        return dict(bob=abs(math.sin(phase)) * 1.6, swing=math.sin(phase * 1.5), wag=math.sin(phase * 1.8) * 16, ear=-2)
    if pose == "held":
        return dict(bob=math.sin(phase * 1.5) * 2, swing=math.sin(phase * 1.5), wag=math.sin(phase * 2.5) * 14, ear=4)
    if pose == "sleep":
        return dict(bob=math.sin(phase) * 1.2, swing=0.0, wag=math.sin(phase * 0.5) * 3, ear=0)
    if pose == "hop":
        return dict(bob=-abs(math.sin(phase)) * 22, swing=0.0, wag=math.sin(phase * 5) * 26, ear=6 + abs(math.sin(phase)) * 10)
    if pose == "pat":
        return dict(bob=math.sin(phase * 2) * 1.2, swing=0.0, wag=math.sin(phase * 5) * 28, ear=-6)
    return dict(bob=math.sin(phase * 0.9) * 1.0, swing=0.0, wag=math.sin(phase * 1.6) * 14, ear=math.sin(phase * 1.2) * 1.2)


# ---------------------------------------------------------------- 头


def _eye(sk: Sketch, cx, cy, r, pupil, expression, far=False):
    if expression == "closed":
        sk.arc((cx - r, cy - r * 0.9, cx + r, cy + r * 0.7), 20, 160, EYE, 2.6)
        return
    if expression == "joy":
        sk.arc((cx - r, cy - r * 0.3, cx + r, cy + r * 1.5), 200, 340, EYE, 3.0)
        return
    px = max(-1.0, min(1.0, pupil[0])) * r * 0.22
    py = max(-1.0, min(1.0, pupil[1])) * r * 0.2
    if expression == "curious":
        r *= 1.1
    sk.spot(cx - r, cy - r * 1.06, cx + r, cy + r, EYE)
    sk.spot(cx - r * 0.78 + px, cy - r * 0.8 + py, cx + r * 0.78 + px, cy + r * 0.8 + py, EYE_RING)
    sk.spot(cx - r * 0.52 + px, cy - r * 0.52 + py, cx + r * 0.52 + px, cy + r * 0.52 + py, EYE)
    hx, hy = cx - r * 0.3 + px * 0.5, cy - r * 0.38 + py * 0.5
    hr = r * 0.4
    sk.spot(hx - hr, hy - hr, hx + hr, hy + hr, (255, 255, 255, 255))
    lx, ly = cx + r * 0.38 + px * 0.5, cy + r * 0.36 + py * 0.5
    lr = r * 0.17
    sk.spot(lx - lr, ly - lr, lx + lr, ly + lr, (255, 255, 255, 255))


def _mouth(sk: Sketch, f, mouth, phase):
    my = 21
    if mouth == "chew":
        mouth = "open_small" if math.sin(phase * 8) > 0 else "w"
    if mouth in ("open", "open_small"):
        big = mouth == "open"
        h = 17 if big else 10
        w = 11 if big else 8
        pts = [(f - w, my - 1)]
        for i in range(13):
            a = math.pi * i / 12
            pts.append((f - w * math.cos(a), my - 1 + h * math.sin(a)))
        pts.append((f + w, my - 1))
        sk.flat(pts, MOUTH)
        if big:
            tw = w * 0.72
            sk.spot(f - tw, my + h * 0.32, f + tw, my + h + 5, TONGUE)
            sk.line([(f, my + h * 0.45), (f, my + h + 1)], TONGUE_LINE, 1.4)
        sk.line([(f, my - 6), (f, my - 1)], EYE, 1.8)
        sk.arc((f - 11, my - 9, f + 1, my + 1), 10, 150, EYE, 1.9)
        sk.arc((f - 1, my - 9, f + 11, my + 1), 30, 170, EYE, 1.9)
        return
    if mouth == "o":
        sk.line([(f, my - 6), (f, my - 1)], EYE, 1.8)
        sk.spot(f - 3.5, my + 1, f + 3.5, my + 8, (150, 70, 66, 255))
        return
    sk.line([(f, my - 6), (f, my)], EYE, 1.8)
    sk.arc((f - 10, my - 7, f, my + 3), 10, 160, EYE, 1.9)
    sk.arc((f, my - 7, f + 10, my + 3), 20, 170, EYE, 1.9)


def _head_sketch(frame: Frame, shift: float, ear: float, nose: float = 0.0, mouth: str = "w", down: float = 0.0) -> Sketch:
    """头部，以 (0, 0) 为中心。shift 是脸朝面向方向偏移多少（3/4 侧脸）。"""
    sk = Sketch()
    f = shift
    expression = frame.expression

    # 宽圆脑袋、柔软的头顶毛簇和三瓣脸颊绒毛，是幼犬比例的核心。
    sk.poly([(-25, -37), (-23, -50), (-12, -45), (-7, -59), (1, -47),
             (12, -57), (13, -44), (28, -49), (23, -34)], FUR)
    sk.poly([(-43, 2), (-58, 13), (-49, 20), (-59, 29), (-44, 30),
             (-47, 42), (-27, 35)], FUR)
    sk.poly([(43 + f * 0.3, 2), (57 + f * 0.3, 14), (49 + f * 0.3, 20),
             (58 + f * 0.3, 29), (43 + f * 0.3, 31), (45 + f * 0.3, 41),
             (27 + f * 0.3, 35)], FUR)
    sk.oval(-53, -48, 53, 43, FUR)
    sk.spot(-37, -42, 2, -23, FUR_LIGHT)
    sk.spot(9, -45, 35, -34, (247, 198, 119, 255))
    sk.line([(-26, -31), (-19, -36), (-13, -34)], FUR_LIGHT, 1.8)
    sk.line([(8, -36), (15, -40), (22, -37)], FUR_LIGHT, 1.8)

    # 奶油色眉斑和更大的深棕色眼睛，保留 concept 的温柔表情。
    ey = -4 + down
    gap = 21 - f * 0.15
    left_x, right_x = f - gap, f + gap
    sk.spot(left_x - 8, ey - 22, left_x + 4, ey - 14, CREAM)
    sk.spot(right_x - 4, ey - 22, right_x + 8, ey - 14, CREAM)

    # 短而宽的双瓣吻部，避免普通小黄狗式的尖嘴感。
    sk.oval(f - 29, -1 + down * 0.7, f + 5, 31 + down * 0.5, CREAM)
    sk.oval(f - 5, -1 + down * 0.7, f + 29, 31 + down * 0.5, CREAM)
    sk.spot(f - 11, -18 + down, f + 11, 5 + down, CREAM)
    sk.spot(f - 21, 20 + down * 0.5, f + 21, 34 + down * 0.4, CREAM_SHADE)
    sk.spot(f - 19, 17 + down * 0.5, f + 19, 29 + down * 0.4, CREAM)

    r = 11.2
    if expression == "curious":
        r = 12.0
    _eye(sk, left_x, ey, r, frame.pupil, expression)
    _eye(sk, right_x, ey, r * 0.94, frame.pupil, expression, far=True)

    blush = BLUSH if expression not in ("joy",) else (250, 138, 118, 220)
    sk.spot(left_x - 19, ey + 13, left_x - 6, ey + 20, blush)
    sk.spot(right_x + 6, ey + 13, right_x + 18, ey + 20, blush)

    _mouth(sk, f + nose * 0.5, mouth, frame.phase)

    nx = f + nose
    sk.spot(nx - 11.5, 3 + down * 0.3, nx + 11.5, 17 + down * 0.3, NOSE)
    sk.spot(nx - 6, 5 + down * 0.3, nx + 1, 9 + down * 0.3, (183, 145, 117, 255))
    sk.spot(nx - 2, 15 + down * 0.3, nx + 2, 17 + down * 0.3, EYE)

    # 长垂耳贴着脸颊，内部用大块明暗和毛流线表现柔软感。
    left_angle = 22 + ear
    right_angle = -24 - ear - f * 0.8
    sk.poly(_teardrop(-38, -30, 67, 40, left_angle), EAR, sep=True)
    sk.flat(_teardrop(-37, -19, 49, 24, left_angle), EAR_LIGHT)
    sk.line([(-45, -5), (-48, 9), (-45, 23)], EAR, 1.7)
    sk.poly(_teardrop(39 + f * 0.45, -29 + f * 0.2, 63 - f * 0.4, 36 - f * 0.35, right_angle), EAR_SHADE, sep=True)
    sk.flat(_teardrop(39 + f * 0.45, -17 + f * 0.2, 46 - f * 0.35, 21, right_angle), EAR)
    sk.line([(48 + f * 0.3, -3), (52 + f * 0.3, 11), (49 + f * 0.3, 24)], EAR_LIGHT, 1.6)
    return sk


def _paint_head(layer: Image.Image, ss: float, frame: Frame, hx, hy, tilt=0.0, **kw):
    _head_sketch(frame, **kw).paint(layer, ss, hx, hy, rot=tilt)


# ---------------------------------------------------------------- 身体


def _chest(sk: Sketch, cx: float, top: float, width: float, height: float) -> None:
    """大块奶油色胸毛，下缘用柔和毛簇代替简单的椭圆。"""
    w, h = width, height
    sk.poly([
        (cx - w * 0.36, top), (cx + w * 0.36, top),
        (cx + w * 0.48, top + h * 0.28), (cx + w * 0.62, top + h * 0.43),
        (cx + w * 0.39, top + h * 0.46), (cx + w * 0.51, top + h * 0.62),
        (cx + w * 0.25, top + h * 0.60), (cx + w * 0.29, top + h * 0.79),
        (cx + w * 0.10, top + h * 0.74), (cx, top + h),
        (cx - w * 0.12, top + h * 0.75), (cx - w * 0.30, top + h * 0.81),
        (cx - w * 0.27, top + h * 0.61), (cx - w * 0.50, top + h * 0.64),
        (cx - w * 0.39, top + h * 0.46), (cx - w * 0.60, top + h * 0.43),
        (cx - w * 0.46, top + h * 0.25),
    ], CREAM)
    sk.line([(cx - w * 0.22, top + h * 0.22), (cx - w * 0.12, top + h * 0.40),
             (cx - w * 0.20, top + h * 0.52)], CREAM_SHADE, 1.5)
    sk.line([(cx + w * 0.20, top + h * 0.20), (cx + w * 0.11, top + h * 0.38),
             (cx + w * 0.18, top + h * 0.49)], CREAM_SHADE, 1.5)


def _sit_body(sk: Sketch, g: dict, pose: str, phase: float, lift: float = 0.0) -> None:
    y = g["bob"] - lift
    gr = GROUND + y
    _tail(sk, (132, 282 + y), (83, 292 + y), (84, 232 + y), g["wag"], 15, 10, feather=1.3)
    sk.oval(112, 233 + y, 190, gr - 2, FUR)
    sk.spot(119, 244 + y, 145, 269 + y, FUR_LIGHT)
    sk.oval(132, 181 + y, 226, gr - 5, FUR)
    sk.spot(139, 194 + y, 159, 239 + y, FUR_LIGHT)
    _chest(sk, 196, 188 + y, 66, 91)
    _paw(sk, 163, gr + 2, 20, FUR)
    if pose == "hop":
        # 作揖：两只前爪收在胸前上下扑腾
        swing = math.sin(phase * 4) * 3
        sk.capsule((207, 220 + y), (221, 238 + y + swing), 9.5, FUR_SHADE, sep=True)
        sk.oval(210, 231 + y + swing, 233, 252 + y + swing, FUR_SHADE, sep=True)
        sk.capsule((185, 222 + y), (198, 242 + y - swing), 10, FUR, sep=True)
        sk.oval(185, 234 + y - swing, 210, 257 + y - swing, FUR, sep=True)
        for k in (-5, 0, 5):
            sk.line([(198 + k, 249 + y - swing), (198 + k, 254 + y - swing)], TOE, 1.4)
        return
    _leg(sk, (209, 256 + y), 210, gr, 11.5, FUR_SHADE, paw_w=17)
    _leg(sk, (183, 254 + y), 185, gr + 2, 12.5, FUR, paw_w=19)


def _stand_body(sk: Sketch, g: dict, pose: str) -> tuple[float, float]:
    y = g["bob"]
    run = pose == "run"
    low = pose in ("sniff", "eat", "dig")
    sw = g["swing"] * (17 if run else 10)
    lift_a = max(0.0, g["swing"]) * (12 if run else 7)
    lift_b = max(0.0, -g["swing"]) * (12 if run else 7)
    if pose in ("sniff", "eat"):
        sw = lift_a = lift_b = 0.0
    stretch = 10 if run else 0
    tail_lift = 14 if low else 0
    _tail(sk, (110, 220 + y), (79, 211 + y - tail_lift), (76, 167 + y - tail_lift), g["wag"], 14, 9.5, feather=1.35)
    # 远侧两条腿（颜色深一点，在身体后面）
    _leg(sk, (126, 248 + y), 128 - sw - stretch, GROUND - lift_a, 10.5, FUR_SHADE, paw_w=16)
    front_far_x = 214 + sw + stretch
    if pose == "dig":
        front_far_x = 220 + math.sin(g["swing"] * 3) * 2
    _leg(sk, (208, 250 + y), front_far_x, GROUND - lift_b, 10.5, FUR_SHADE, paw_w=16)
    # 圆润的幼犬躯干、背部高光和胸前大块毛簇。
    front_drop = 10 if low else 0
    sk.oval(96 - stretch * 0.5, 195 + y, 238 + stretch, 272 + y, FUR)
    sk.oval(148, 208 + y + front_drop, 254 + stretch, 268 + y + front_drop * 0.6, FUR)
    sk.spot(112 - stretch * 0.2, 200 + y, 177, 215 + y, FUR_LIGHT)
    sk.spot(101, 213 + y, 127, 242 + y, (246, 195, 115, 255))
    _chest(sk, 224 + stretch, 214 + y + front_drop, 54, 60)
    # 近侧两条腿，脚掌稍大，突出幼年金毛的笨拙感。
    _leg(sk, (140, 250 + y), 138 + sw - stretch, GROUND - lift_b, 11.5, FUR, paw_w=18)
    if pose == "dig":
        scratch = math.sin(g["swing"] * 4)
        foot = 236 + scratch * 8
        _leg(sk, (224, 252 + y), foot, GROUND - max(0.0, scratch) * 12, 11.5, FUR, paw_w=18)
    else:
        _leg(sk, (224, 250 + y), 226 - sw + stretch, GROUND - lift_a, 11.5, FUR, paw_w=18)
    if low:
        return 266 + stretch, 228 + y
    if run:
        return 252 + stretch, 172 + y
    return 244, 168 + y


def _sleep_body(sk: Sketch, g: dict) -> tuple[float, float]:
    y = g["bob"]
    sk.oval(96, 244 - y, 258, GROUND + 2, FUR)
    sk.circle(132, 270 - y * 0.5, 36, FUR)
    sk.spot(110, 249 - y, 165, 266 - y, FUR_LIGHT)
    sk.spot(145, 248 - y, 222, 256 - y, (247, 198, 119, 255))
    return 238, 262


def _sleep_front(sk: Sketch, g: dict) -> None:
    _tail(sk, (105, 289), (121, 316), (187, 302), g["wag"] * 0.3, 14, 9.5, feather=1.0)
    _paw(sk, 238, GROUND + 1, 19, FUR)
    _paw(sk, 271, GROUND + 2, 18, FUR)


def _held_body(sk: Sketch, g: dict) -> tuple[float, float]:
    y = g["bob"]
    sw = g["swing"] * 4
    _tail(sk, (180, 248 + y), (169, 278 + y), (184, 301 + y), g["wag"] * 0.6, 12, 8, feather=1.1)
    _leg(sk, (160, 240 + y), 158 - sw, 292 + y, 11, FUR_SHADE, paw_w=15)
    _leg(sk, (200, 240 + y), 202 + sw, 292 + y, 11, FUR_SHADE, paw_w=15)
    sk.oval(136, 158 + y, 224, 264 + y, FUR)
    sk.spot(143, 170 + y, 157, 217 + y, FUR_LIGHT)
    _chest(sk, 180, 170 + y, 54, 73)
    _leg(sk, (156, 194 + y), 150 + sw, 252 + y, 11, FUR, paw_w=15)
    _leg(sk, (204, 194 + y), 210 - sw, 252 + y, 11, FUR, paw_w=15)
    return 180, 128 + y


def _draw_dog(layer: Image.Image, ss: float, frame: Frame) -> tuple[float, float, float, float]:
    """返回 (头中心 x, 头中心 y, 鼻尖 x, 鼻尖 y)，均为面朝右时的逻辑坐标。"""
    g = _gait(frame.pose, frame.phase)
    pose = frame.pose
    body = Sketch()
    front: Sketch | None = None
    mouth = "w"
    if frame.expression in ("happy", "joy"):
        mouth = "open"
    elif frame.expression == "curious":
        mouth = "o"
    if frame.file_mode in ("hold", "toss") or frame.expression == "closed":
        mouth = "w"
    if pose == "eat":
        mouth = "chew"

    tilt = frame.tilt
    nose = g.get("nose", 0.0)
    down = 0.0
    if pose == "sleep":
        hx, hy = _sleep_body(body, g)
        front = Sketch()
        _sleep_front(front, g)
        shift, ear = 4.0, -8.0
        tilt += 10
    elif pose == "held":
        hx, hy = _held_body(body, g)
        shift, ear = 0.0, g["ear"]
    elif pose in ("walk", "run", "sniff", "eat", "dig"):
        hx, hy = _stand_body(body, g, pose)
        shift = 13.0
        ear = g["ear"]
        if pose in ("sniff", "eat", "dig"):
            shift = 12.0
            tilt += 14
            down = 3.0
        if pose == "eat":
            hy += 14 + math.sin(frame.phase * 8) * 1.5
    else:
        lift = 0.0
        if pose == "hop":
            lift = -g["bob"]
            g = dict(g, bob=0.0)
        _sit_body(body, g, pose, frame.phase, lift)
        hx, hy = 196, 150 + g["bob"] - lift
        shift, ear = 8.0, g["ear"]
        if pose == "pat":
            press = max(0.0, math.sin(frame.pat * math.tau * 2)) * 5
            hy += press
            tilt += math.sin(frame.pat * math.tau) * 6

    body.paint(layer, ss)
    _paint_head(layer, ss, frame, hx, hy, tilt=tilt, shift=shift, ear=ear, nose=nose, mouth=mouth, down=down)
    if front is not None:
        front.paint(layer, ss)
    nx, ny = _rot(hx + shift + nose, hy + 10, hx, hy, tilt)
    return hx, hy, nx, ny


# ---------------------------------------------------------------- 界面元素（屏幕坐标）


def _file_icon(draw: ImageDraw.ImageDraw, s: float, x, y, alpha=255, icon_scale=1.0, kind="file"):
    a = max(0, min(255, int(alpha)))
    w, h = 24 * icon_scale, 28 * icon_scale

    def box(x0, y0, x1, y1):
        return [x0 * s, y0 * s, x1 * s, y1 * s]

    if kind == "folder":
        h = 20 * icon_scale
        tab = (232, 178, 60, a)
        draw.rounded_rectangle(box(x, y, x + w * 0.5, y + 6 * icon_scale), radius=2 * s, fill=tab)
        draw.rounded_rectangle(box(x, y + 3 * icon_scale, x + w, y + h), radius=2.5 * s, fill=(250, 204, 92, a), outline=(196, 140, 44, a), width=max(1, int(s)))
        draw.line([(x + 2) * s, (y + 8 * icon_scale) * s, (x + w - 2) * s, (y + 8 * icon_scale) * s], fill=(255, 226, 150, a), width=max(1, int(s)))
        return
    draw.rounded_rectangle(box(x, y, x + w, y + h), radius=2 * s, fill=(255, 253, 248, a), outline=(176, 148, 114, a), width=max(1, int(s)))
    draw.polygon([((x + w - 8) * s, y * s), ((x + w - 8) * s, (y + 8) * s), ((x + w) * s, (y + 8) * s)], fill=(228, 210, 186, a))
    for i in range(3):
        yy = y + 13 + i * 4.5
        draw.line([((x + 4) * s, yy * s), ((x + w - 5) * s, yy * s)], fill=(132, 122, 112, a), width=max(1, int(s)))


def _bubble(draw: ImageDraw.ImageDraw, s: float, text: str, anchor):
    font = _font(int(14 * s))
    raw = draw.textlength(text, font=font) / s
    tw = max(42, raw + 22)
    th = 28
    ax, ay = anchor
    x = min(max(6, ax - tw / 2), LW - tw - 6)
    y = max(4, ay - th - 12)
    outline = (214, 170, 120, 255)
    draw.rounded_rectangle([x * s, y * s, (x + tw) * s, (y + th) * s], radius=12 * s, fill=(255, 251, 244, 245), outline=outline, width=max(1, int(1.5 * s)))
    tip = [((ax - 7) * s, (y + th - 1.2) * s), ((ax + 7) * s, (y + th - 1.2) * s), (ax * s, (y + th + 9) * s)]
    draw.polygon(tip, fill=(255, 251, 244, 245))
    draw.line([tip[0], tip[2], tip[1]], fill=outline, width=max(1, int(1.5 * s)))
    draw.text(((x + tw / 2) * s, (y + th / 2) * s), text, font=font, fill=(110, 66, 30, 255), anchor="mm")


def _heart(draw, s, cx, cy, r, color):
    draw.ellipse([(cx - r) * s, (cy - r) * s, (cx + r * 0.12) * s, (cy + r * 0.18) * s], fill=color)
    draw.ellipse([(cx - r * 0.12) * s, (cy - r) * s, (cx + r) * s, (cy + r * 0.18) * s], fill=color)
    draw.polygon([((cx - r * 0.96) * s, (cy - r * 0.1) * s), ((cx + r * 0.96) * s, (cy - r * 0.1) * s), (cx * s, (cy + r * 1.25) * s)], fill=color)


def _star(draw, s, cx, cy, r, color):
    k = r * 0.3
    pts = [(cx, cy - r), (cx + k, cy - k), (cx + r, cy), (cx + k, cy + k), (cx, cy + r), (cx - k, cy + k), (cx - r, cy), (cx - k, cy - k)]
    draw.polygon([(x * s, y * s) for x, y in pts], fill=color)


def _hand(draw, s, cx, cy, sign):
    """摸头的手，手指朝下搭在头顶。"""
    skin = (255, 222, 196, 255)
    edge = (196, 140, 112, 255)
    w = max(1, int(1.8 * s))
    k = 1.15

    def rect(x0, y0, x1, y1, r, fill, outline):
        x0, x1 = cx + x0 * k * sign, cx + x1 * k * sign
        draw.rounded_rectangle([min(x0, x1) * s, (cy + y0 * k) * s, max(x0, x1) * s, (cy + y1 * k) * s], radius=r * k * s, fill=fill, outline=outline, width=w)

    for i, dx in enumerate((-15, -5, 5, 15)):
        length = 20 if i in (1, 2) else 16
        rect(dx - 5, -6, dx + 5, length, 5, skin, edge)
    rect(-22, -26, 22, 4, 12, skin, edge)
    rect(-24, -18, -12, -6, 6, skin, edge)
    rect(-26, -40, 26, -22, 6, (124, 170, 230, 255), (86, 126, 186, 255))


def _treat(draw, s, cx, cy, left: float):
    """一块骨头形饼干，left 为剩余比例。"""
    if left <= 0:
        return
    body = (226, 176, 118, 255)
    edge = (164, 110, 62, 255)
    half = 14 * left + 4
    w = max(1, int(1.6 * s))
    draw.rounded_rectangle([(cx - half) * s, (cy - 4) * s, (cx + 14) * s, (cy + 4) * s], radius=3 * s, fill=body, outline=edge, width=w)
    for dy in (-4, 4):
        draw.ellipse([(cx + 11) * s, (cy + dy - 5) * s, (cx + 21) * s, (cy + dy + 5) * s], fill=body, outline=edge, width=w)
    if left > 0.6:
        for dy in (-4, 4):
            draw.ellipse([(cx - half - 7) * s, (cy + dy - 5) * s, (cx - half + 3) * s, (cy + dy + 5) * s], fill=body, outline=edge, width=w)


def _mark_stream(draw: ImageDraw.ImageDraw, s: float, x0, y0, x1, y1, strength: float, clock: float) -> None:
    """一小股弧线水柱和地上的一滩，卡通、克制，对着图标的方向。"""
    if strength <= 0.04:
        return
    spray = max(0.0, min(1.0, (strength - 0.28) / 0.72))
    cx = (x0 + x1) / 2
    cy = min(y0, y1) - 16
    if spray > 0.02:
        for i in range(6):
            u = (clock * 2.4 + i / 6) % 1.0
            fade = math.sin(math.pi * u) ** 0.65
            alpha = int(220 * spray * fade)
            if alpha < 8:
                continue
            px = (1 - u) ** 2 * x0 + 2 * (1 - u) * u * cx + u ** 2 * x1
            py = (1 - u) ** 2 * y0 + 2 * (1 - u) * u * cy + u ** 2 * y1
            r = 1.55 + u * 1.7
            draw.ellipse(
                [(px - r) * s, (py - r) * s, (px + r) * s, (py + r) * s],
                fill=(255, 206, 72, alpha),
                outline=(196, 146, 42, alpha),
            )
    puddle = 0.35 + 0.65 * strength
    alpha = int(130 * puddle)
    rx, ry = 8 + 7 * puddle, 3.2 + 1.6 * puddle
    draw.ellipse([(x1 - rx) * s, (y1 - ry) * s, (x1 + rx) * s, (y1 + ry) * s], fill=(255, 198, 64, alpha))
    draw.ellipse(
        [(x1 - rx * 0.45) * s, (y1 - ry * 0.7) * s, (x1 - rx * 0.05) * s, (y1 - ry * 0.05) * s],
        fill=(255, 236, 180, int(alpha * 0.75)),
    )


def _ui(base: Image.Image, s: float, frame: Frame, hx, hy, nx, ny, facing: int, flip: bool = True, baked: dict | None = None, stream=None):
    draw = ImageDraw.Draw(base)
    sign = 1 if facing > 0 else -1

    def X(x):
        return x if sign > 0 else LW - x

    # flip=False 表示画布未镜像（如自带朝左的贴纸），坐标直接用，方向仍按 sign。
    head_x = X(hx) if flip else hx
    nose_x = X(nx) if flip else nx
    baked = baked or {}
    clock = frame.clock

    if frame.zzz:
        for i, ch in enumerate("zZz"):
            t = (clock * 0.32 + i * 0.33) % 1.0
            alpha = int(230 * math.sin(math.pi * t))
            draw.text(
                ((head_x + sign * (40 + t * 22 + i * 4)) * s, (hy - 30 - t * 40) * s),
                ch,
                font=_font(int((13 + i * 4) * s)),
                fill=(120, 140, 210, alpha),
                anchor="mm",
            )

    if frame.hearts > 0:
        t = 1 - frame.hearts
        for i in range(3):
            local = min(1.0, max(0.0, t * 1.15 - i * 0.12))
            alpha = int(255 * (1 - local))
            if alpha > 0:
                _heart(draw, s, head_x - 16 + i * 16, hy - 64 - local * 36, 6, (236, 84, 108, alpha))

    if frame.love > 0:
        for i in range(5):
            t = (clock * 0.55 + i / 5) % 1.0
            alpha = int(255 * frame.love * math.sin(math.pi * t))
            cx = head_x + math.sin(clock * 2.3 + i * 1.7) * 10 + (i - 2) * 22
            cy = hy - 40 - t * 70
            _heart(draw, s, cx, cy, 5 + (i % 3) * 1.5, (238, 80 + i * 12, 110, alpha))

    if frame.sparkle > 0:
        for i in range(6):
            a = i / 6 * math.tau + clock * 0.8
            t = (clock * 1.3 + i * 0.37) % 1.0
            alpha = int(255 * frame.sparkle * math.sin(math.pi * t))
            cx = LW / 2 + math.cos(a) * 92
            cy = 214 + math.sin(a) * 76
            _star(draw, s, cx, cy, 3 + 4 * math.sin(math.pi * t), (255, 214, 90, alpha))

    if stream and frame.mark > 0.02:
        def SX(x):
            return X(x) if flip else x

        _mark_stream(draw, s, SX(stream[0]), stream[1], SX(stream[2]), stream[3], frame.mark, clock)

    if frame.question > 0:
        alpha = int(255 * frame.question)
        bob = math.sin(clock * 5) * 2
        draw.text(((head_x + sign * 46) * s, (hy - 58 + bob) * s), "?", font=_font(int(26 * s)), fill=(236, 140, 40, alpha), anchor="mm",
                  stroke_width=max(1, int(2 * s)), stroke_fill=(255, 255, 255, alpha))

    if frame.pose in ("sniff", "eat") and frame.file_mode != "hold":
        for i in range(3):
            t = (clock * 1.6 + i / 3) % 1.0
            alpha = int(200 * math.sin(math.pi * t))
            cx = nose_x + sign * (46 + t * 16)
            cy = ny + 14 - i * 7 - t * 8
            draw.arc([(cx - 5) * s, (cy - 5) * s, (cx + 5) * s, (cy + 5) * s], 200 if sign > 0 else -20, 340 if sign > 0 else 120,
                     fill=(150, 110, 70, alpha), width=max(1, int(1.6 * s)))

    if frame.pat >= 0 and not baked.get("hand"):
        stroke = math.sin(frame.pat * math.tau * 2)
        press = max(0.0, stroke) * 5
        _hand(draw, s, head_x + stroke * 12 * sign - sign * 4, hy - 50 + press, sign)

    if frame.treat >= 0 and not baked.get("treat"):
        _treat(draw, s, nose_x + sign * 4 - 6, min(GROUND - 7, ny + 22), frame.treat)
        if frame.treat < 0.95 and not baked.get("treat"):
            for i in range(4):
                t = (clock * 1.2 + i / 4) % 1.0
                cx = nose_x + sign * (math.sin(i * 2.1) * 14)
                cy = ny + 8 + t * (GROUND - ny - 8)
                r = 1.6
                draw.ellipse([(cx - r) * s, (cy - r) * s, (cx + r) * s, (cy + r) * s], fill=(214, 160, 100, int(230 * (1 - t))))

    label = frame.bubble
    if label is None and frame.file_label and frame.file_mode in ("sniff", "hold"):
        label = frame.file_label
    anchor_y = hy - (98 if frame.pat >= 0 else 54)
    if label and frame.file_mode != "toss":
        _bubble(draw, s, label, (head_x, anchor_y))
    elif frame.bubble:
        _bubble(draw, s, frame.bubble, (head_x, anchor_y))

    if frame.file_mode == "none":
        return
    fly = frame.file_fly if frame.file_mode == "toss" else 0.0
    alpha = 255 if fly < 0.72 else int(255 * (1 - (fly - 0.72) / 0.28))
    if frame.file_mode == "sniff":
        _file_icon(draw, s, nose_x + sign * 6 - 10, ny - 2, alpha=230, icon_scale=0.82, kind=frame.file_kind)
    elif frame.file_mode == "hold" and baked.get("file"):
        pass  # 叼文件贴纸里已经画好了文件
    else:
        ox = sign * (6 + fly * 48)
        oy = 6 - math.sin(min(1.0, fly) * math.pi) * 52
        _file_icon(draw, s, nose_x - 12 + ox, ny - 6 + oy, alpha=alpha, icon_scale=1.0, kind=frame.file_kind)


def _shadow(size: tuple[int, int], ss: float, pose: str, lift: float) -> Image.Image:
    key = (size, pose, int(lift))
    hit = _SHADOW_CACHE.get(key)
    if hit is not None:
        return hit
    shadow = Image.new("RGBA", size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    shrink = max(0.55, 1 - lift / 50)
    if pose == "held":
        sw, sh, alpha = 44, 8, 34
    elif pose == "sleep":
        sw, sh, alpha = 92, 13, 60
    else:
        sw, sh, alpha = 82 * shrink, 13 * shrink, int(60 * shrink)
    cx, cy = LW / 2 * ss, (GROUND - 1) * ss
    sd.ellipse([cx - sw * ss, cy - sh * ss, cx + sw * ss, cy + sh * ss], fill=(90, 58, 26, alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=5 * ss / 2))
    if len(_SHADOW_CACHE) > 64:
        _SHADOW_CACHE.clear()
    _SHADOW_CACHE[key] = shadow
    return shadow


def render(frame: Frame, pixel_scale: float = 1.0) -> Image.Image:
    # 按两倍目标分辨率作画，最后 reduce(2) 抗锯齿，比任意比例缩放快得多。
    out_w = max(1, int(round(LW * pixel_scale)))
    out_h = max(1, int(round(LH * pixel_scale)))
    size = (out_w * 2, out_h * 2)
    ss = size[0] / LW
    baked: dict = {}
    stream = None
    flip = frame.facing < 0
    stick = _pick_sticker(frame)
    entry = _sticker_image(stick, ss) if stick else None
    if entry is not None:
        # 贴纸模式：贴纸自带阴影，不再画程序阴影；轻量浮动保持“活着”的感觉。
        im, left_l, top_l, hx, hy, nx, ny = entry
        walking = frame.pose in ("walk", "run")
        # 活着的狗用走过的距离推进步子；预览只填了 phase 时，也把它当成步态相位。
        cycle = frame.stride if walking and frame.stride else frame.phase
        # 走路时 phase 不再跟着步子走，尾巴改用时钟，免得走着走着尾巴僵住。
        if walking:
            tail_phase = frame.clock * (14.0 if frame.pose == "run" else 11.0)
        else:
            tail_phase = frame.phase
        posed, (pad_x, pad_y) = animate_sticker(
            stick, im, tail_phase, frame.pose, frame.mark,
            stride=cycle, step_scale=frame.step_scale, planted=frame.planted,
        )
        animated = posed is not im
        im = posed
        g = _gait(frame.pose, cycle)
        # 腿和尾巴自己在动时，整身只留很轻的起伏，避免又变成一起蹦。停步时不起伏。
        if walking and frame.planted:
            bob_scale = 0.0
        elif animated and frame.pose in ("walk", "run", "mark"):
            bob_scale = 0.28
        elif animated:
            bob_scale = 0.55
        else:
            bob_scale = 1.0
        dy = g["bob"] * (0.5 if frame.pose == "hop" else 1.0) * bob_scale
        # 坐着、趴着时胸口一起一伏。按脚下对齐着拉高一点点，脚不离地。
        if frame.pose in ("sit", "sleep", "sniff", "eat", "pat") and abs(frame.roll) < 0.5:
            breath = 1.0 + (0.008 if frame.pose == "sleep" else 0.006) * math.sin(frame.clock * (1.6 if frame.pose == "sleep" else 2.4))
            new_h = max(1, int(round(im.height * breath)))
            if new_h != im.height:
                im = im.resize((im.width, new_h), Image.Resampling.BILINEAR)
                dy -= (new_h - posed.height) / ss
        if stick == "walk_left":
            flip = False  # 素材本身就是朝左的
        if frame.mark > 0.02:
            fr = stream_fracs(stick)
            if fr:
                ax, ay = layout_point(stick, fr[0])
                bx, by = layout_point(stick, fr[1])
                stream = (ax, ay + dy, bx, by + dy)
        baked = {"hand": stick == "pat", "treat": stick == "eat", "file": stick == "carry"}
        dog = Image.new("RGBA", size, (0, 0, 0, 0))
        x = int(round(left_l * ss)) - pad_x
        y = int(round((top_l + dy) * ss)) - pad_y
        # alpha_composite 不接受负坐标，超出画布的部分先裁掉。
        if x < 0 or y < 0:
            im = im.crop((max(0, -x), max(0, -y), im.width, im.height))
            x, y = max(0, x), max(0, y)
        dog.alpha_composite(im, (x, y))
        if abs(frame.roll) > 0.5:
            dog = dog.rotate(-frame.roll, resample=Image.Resampling.BILINEAR, center=(LW * ss / 2, (LH * 0.66) * ss))
        canvas = dog
    else:
        # 兜底：素材缺失时仍用程序绘制的小狗。
        lift = 0.0
        if frame.pose == "hop":
            lift = abs(math.sin(frame.phase)) * 22
        elif frame.pose == "run":
            lift = abs(math.sin(frame.phase)) * 9
        canvas = _shadow(size, ss, frame.pose, lift // 3 * 3).copy()
        if abs(frame.roll) > 0.5:
            dog = Image.new("RGBA", size, (0, 0, 0, 0))
            hx, hy, nx, ny = _draw_dog(dog, ss, frame)
            dog = dog.rotate(-frame.roll, resample=Image.Resampling.BILINEAR, center=(LW * ss / 2, (LH * 0.66) * ss))
            canvas.alpha_composite(dog)
        else:
            hx, hy, nx, ny = _draw_dog(canvas, ss, frame)
    if flip:
        canvas = canvas.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    # 起步后坐、停步前倾：以地面为轴把上半身斜推，脚和影子留在原地。
    # 整张图旋转会让一只脚陷进地里、另一只翘起来，所以用错切不用旋转。
    if abs(frame.lean) > 0.03:
        sign = 1 if frame.facing > 0 else -1
        k = sign * frame.lean * 0.07
        canvas = canvas.transform(
            canvas.size,
            Image.Transform.AFFINE,
            (1, k, -k * GROUND * ss, 0, 1, 0),
            resample=Image.Resampling.BILINEAR,
        )
    # 界面元素有半透明，单独一层再混合，否则会在狗身上“抠洞”。
    ui = Image.new("RGBA", size, (0, 0, 0, 0))
    _ui(ui, ss, frame, hx, hy, nx, ny, frame.facing, flip=flip, baked=baked, stream=stream)
    canvas.alpha_composite(ui)
    return canvas.reduce(2)


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
        ("sleep", Frame(pose="sleep", expression="closed", zzz=True, phase=0.5, clock=0.5)),
        ("sniff", Frame(pose="sniff", expression="curious", question=1, file_kind="folder", bubble="「新建文件夹」？", phase=0.4, clock=0.3)),
        ("pat", Frame(pose="pat", expression="joy", pat=0.12, love=1, sparkle=1, bubble="好舒服~", phase=1.0, clock=0.4)),
        ("hop", Frame(pose="hop", expression="joy", phase=1.3, love=0.8, bubble="最喜欢你了！", clock=1.0)),
        ("eat", Frame(pose="eat", expression="happy", treat=0.7, phase=0.3, clock=0.6)),
        ("held", Frame(pose="held", expression="happy", phase=0.6, bubble="放下啦")),
        ("left", Frame(pose="walk", facing=-1, phase=2.1, pupil=(0.3, 0.1))),
        ("carry", Frame(pose="run", file_mode="hold", file_label="照片.jpg", expression="happy", phase=0.5)),
        ("happy", Frame(pose="sit", expression="happy", hearts=0.55, bubble="嘿嘿", tilt=8)),
    ]
    cols = 4
    rows = (len(samples) + cols - 1) // cols
    sheet = Image.new("RGBA", (LW * cols, LH * rows), (40, 40, 44, 255))
    for i, (name, frame) in enumerate(samples):
        im = render(frame, 1.0)
        sheet.alpha_composite(im, ((i % cols) * LW, (i // cols) * LH))
    sheet.convert("RGB").save(os.path.join(folder, "sheet.png"), quality=92)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "preview")
    save_previews(out)
    print(out)
