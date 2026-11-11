"""让贴纸上的腿和尾巴动起来。

这张贴纸的腿和肚子、尾巴和屁股都是连着画的，抠下来整块转一定会裂开。
所以只做连续形变：位移从髋线、尾根处的 0 平滑增长到脚掌、尾尖，任何地方都不会被“剪开”。

腿的姿势预先烤成一组关键帧，播放下标由走过的距离决定（见 STRIDE），换步和窗口位移锁在一起。
尾巴每帧现算，尾尖比尾根晚一点，像带着惯性甩。脚下的影子单独重画，不跟着脚走。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

# 种子、界限和髋线都是原图像素的宽高比例。
# head：头在右边为 1，在左边为 -1，决定“向前迈步”往哪边。
# step / run_step：脚掌前后摆动的幅度，占腿长的比例。
_RIGS = {
    "walk": dict(
        tail_seed=(0.04, 0.40), tail_box=(0.00, 0.18, 0.17, 0.54), tail_pivot=(0.108, 0.495),
        hind_seed=(0.18, 0.90), front_seed=(0.63, 0.90), hip=0.768,
        head=1, step=0.30, run_step=0.42,
    ),
    "walk_left": dict(
        tail_seed=(0.97, 0.44), tail_box=(0.86, 0.36, 1.0, 0.58), tail_pivot=(0.90, 0.52),
        hind_seed=(0.67, 0.90), front_seed=(0.31, 0.90), hip=0.755,
        head=-1, step=0.30, run_step=0.42,
    ),
    "run": dict(
        tail_seed=(0.04, 0.40), tail_box=(0.00, 0.18, 0.15, 0.55), tail_pivot=(0.095, 0.50),
        hind_seed=(0.17, 0.90), front_seed=(0.61, 0.90), hip=0.775,
        head=1, step=0.36, run_step=0.46,
    ),
    "carry": dict(
        tail_seed=(0.04, 0.40), tail_box=(0.00, 0.18, 0.16, 0.55), tail_pivot=(0.10, 0.50),
        hind_seed=(0.18, 0.90), front_seed=(0.62, 0.90), hip=0.768,
        head=1, step=0.30, run_step=0.40,
    ),
    "sit": dict(
        tail_seed=(0.05, 0.74), tail_box=(0.00, 0.60, 0.20, 0.90), tail_pivot=(0.16, 0.80),
    ),
    "tilt": dict(
        tail_seed=(0.04, 0.74), tail_box=(0.00, 0.62, 0.20, 0.90), tail_pivot=(0.15, 0.78),
    ),
}

# 标记时尿柱的起点（抬起的后腿根）和落点，原图比例。
STREAM = {
    "walk": ((0.145, 0.80), (0.035, 0.955)),
    "walk_left": ((0.855, 0.80), (0.965, 0.955)),
}

_MAX_WAG = 30.0  # 尾巴最大摆角（度），预先算好扫过范围用
_MARK_STEP = 0.30  # 抬腿标记时脚掌往后挪的幅度，占腿长
_MARK_LIFT = 0.34
_WALK_LIFT = 0.16

# 一个完整步态循环对应的位移（逻辑像素）。支撑脚在一个循环里往后扫 2×step×腿长，
# 占循环的 stance 那一段：走路约 2×0.30×40/0.62 ≈ 39，跑步约 2×0.42×40/0.50 ≈ 67。
# 按这个距离推进，着地的那只脚相对桌面基本不动。
STRIDE = {"walk": 39.0, "run": 67.0}
# 每秒最多走几个循环。再快就把步幅拉长（脚会稍微滑），免得超过帧率、腿看起来倒着转。
MAX_CADENCE = {"walk": 2.4, "run": 2.9}
WALK_FRAMES = 10
RUN_FRAMES = 8
MARK_LEVELS = (0.0, 0.35, 0.7, 1.0)

_CACHE: dict[tuple, "_Prepared | None"] = {}
_BAKE: dict[tuple, list[np.ndarray]] = {}


def stream_fracs(name: str) -> tuple[tuple[float, float], tuple[float, float]] | None:
    return STREAM.get(name)


def _wag(phase: float, amp: float, bias: float = 0.0) -> float:
    """尾尖角度。副波让甩动一头稍快，不像节拍器。"""
    wave = 0.82 * math.sin(phase) + 0.18 * math.sin(2 * phase + 0.45)
    return bias + amp * wave


def _step_cycle(phase: float, stance: float = 0.60) -> tuple[float, float]:
    """返回 (前后 -1..1, 抬脚 0..1)。支撑段长、腾空段短，换步处速度连续。"""
    p = (phase / math.tau) % 1.0
    if p < stance:
        t = p / stance
        return math.cos(t * math.pi), 0.0
    t = (p - stance) / (1.0 - stance)
    s = t * t * (3 - 2 * t)
    return -math.cos(s * math.pi), math.sin(s * math.pi)


def _smooth(e0, e1, x):
    t = np.clip((x - e0) / (e1 - e0), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def _grow(mask: np.ndarray, size: int) -> np.ndarray:
    return np.asarray(Image.fromarray(mask.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(size))) > 0


# ---------------------------------------------------------------- 取样


def _is_body(r, g, b, a) -> bool:
    if a < 16:
        return False
    if r < 80 and g < 80 and b < 80:
        return False
    return True


def _flood(im: Image.Image, seed: tuple[float, float], allow) -> list[tuple[int, int]]:
    """只用来量腿的位置和长短，不拿它抠图。"""
    w, h = im.size
    px = im.load()
    sx, sy = int(seed[0] * w), int(seed[1] * h)
    found = None
    for rad in range(0, 18):
        for dy in range(-rad, rad + 1):
            for dx in range(-rad, rad + 1):
                x, y = sx + dx, sy + dy
                if 0 <= x < w and 0 <= y < h and allow(x, y) and _is_body(*px[x, y]):
                    found = (x, y)
                    break
            if found:
                break
        if found:
            break
    if found is None:
        return []
    seen: set[tuple[int, int]] = set()
    stack = [found]
    while stack:
        x, y = stack.pop()
        if (x, y) in seen or not (0 <= x < w and 0 <= y < h) or not allow(x, y):
            continue
        if not _is_body(*px[x, y]):
            continue
        seen.add((x, y))
        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return list(seen)


def _sample(src: np.ndarray, sx: np.ndarray, sy: np.ndarray) -> np.ndarray:
    """双线性取样，返回 float32。src 为预乘透明度的 (H, W, C)，最外一圈像素必须是透明的。"""
    h, w = src.shape[:2]
    sx = np.clip(sx, 0.0, w - 1.001)
    sy = np.clip(sy, 0.0, h - 1.001)
    x0 = sx.astype(np.int32)
    y0 = sy.astype(np.int32)
    fx = (sx - x0)[..., None].astype(np.float32)
    fy = (sy - y0)[..., None].astype(np.float32)
    flat = src.reshape(h * w, -1)
    i = y0 * w + x0
    top = flat[i] * (1 - fx) + flat[i + 1] * fx
    bottom = flat[i + w] * (1 - fx) + flat[i + w + 1] * fx
    return top * (1 - fy) + bottom * fy


def _store(values: np.ndarray) -> np.ndarray:
    return np.clip(values + 0.5, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- 骨架


@dataclass
class _Tail:
    pivot: tuple[float, float]  # 框内坐标
    layer: np.ndarray  # 框内只有尾巴的预乘图
    rows: np.ndarray  # 尾巴摆到最大角度也只会落在这些像素里（整图坐标）
    cols: np.ndarray
    dx: np.ndarray
    dy: np.ndarray
    radial: np.ndarray  # 尾根 0 → 尾尖 1


@dataclass
class _Legs:
    rows: np.ndarray  # 腿可能扫到的像素（整图坐标）
    cols: np.ndarray
    ramp_x: np.ndarray  # 前后位移比例：髋线 0 → 脚掌 1
    ramp_y: np.ndarray  # 抬脚比例
    hind: np.ndarray  # 属于后腿那一组的权重
    front: np.ndarray
    length: float


@dataclass
class _Prepared:
    pad: tuple[int, int]  # 画布左、上各加宽的像素，尾巴和脚甩出原图也不会被裁掉
    dog: np.ndarray  # 去掉影子和尾巴后的预乘图（uint8）
    shadow: Image.Image  # 重画的影子
    tail: _Tail | None
    legs: _Legs | None
    head: int
    step: float
    run_step: float


def _padded(im: Image.Image, rig: dict) -> tuple[Image.Image, dict, tuple[int, int]]:
    """贴边画的尾巴和脚甩出去会被裁掉，所以先四周留白，并把骨架比例换算到新画布。"""
    w, h = im.size
    px, top, bottom = math.ceil(0.14 * w), math.ceil(0.05 * h), math.ceil(0.03 * h)
    nw, nh = w + 2 * px, h + top + bottom
    canvas = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    canvas.paste(im.convert("RGBA"), (px, top))

    def fx(v):
        return (v * w + px) / nw

    def fy(v):
        return (v * h + top) / nh

    out = dict(rig)
    for key in ("tail_seed", "tail_pivot", "hind_seed", "front_seed"):
        if key in rig:
            out[key] = (fx(rig[key][0]), fy(rig[key][1]))
    if "tail_box" in rig:
        x0, y0, x1, y1 = rig["tail_box"]
        out["tail_box"] = (fx(x0), fy(y0), fx(x1), fy(y1))
    if "hip" in rig:
        out["hip"] = fy(rig["hip"])
    return canvas, out, (px, top)


def _split_shadow(dog: np.ndarray) -> Image.Image:
    """贴纸自带的地面影子是半透明的 (32,32,30)。从 dog 里去掉（原地修改），
    另画一个完整椭圆垫在底下，脚挪开后不会露洞。"""
    h, w = dog.shape[:2]
    a = dog[..., 3].astype(np.int32)
    shade = (a > 0) & (a <= 143) & (dog[..., :3].max(axis=-1).astype(np.int32) * 4 <= a + 5)
    shade[: int(h * 0.6)] = False
    dog[shade] = 0
    shadow = Image.new("RGBA", (w, h), (32, 32, 30, 0))
    ys, xs = np.nonzero(shade)
    if len(xs) < 20:
        return shadow
    k = 4
    mask = Image.new("L", (w * k, h * k), 0)
    ImageDraw.Draw(mask).ellipse([xs.min() * k, ys.min() * k, (xs.max() + 1) * k, (ys.max() + 1) * k], fill=128)
    shadow.putalpha(mask.resize((w, h), Image.Resampling.BOX))
    return shadow


def _tail_mask(im: Image.Image, rig: dict) -> np.ndarray | None:
    """沿描边找出整条尾巴（不是按方框切），返回布尔掩码。

    尾巴画在身体后面，尾根处被身体的描边隔开，所以把深色描边当墙来填充，
    不会漏进身体；最后顺着描边再长几像素，把尾巴自己的描边和抗锯齿边带上。
    """
    w, h = im.size
    rgba = np.asarray(im)
    alpha = rgba[..., 3]
    lum = rgba[..., 0] * 0.30 + rgba[..., 1] * 0.59 + rgba[..., 2] * 0.11
    # 先收一圈，堵住描边上抗锯齿留下的细缝。
    passable = ~_grow(~((alpha >= 128) & (lum >= 128)), 3)

    bx0, by0, bx1, by1 = rig["tail_box"]
    pad = 0.08
    x0, x1 = max(0, int((bx0 - pad) * w)), min(w, int(math.ceil((bx1 + pad) * w)))
    y0, y1 = max(0, int((by0 - pad) * h)), min(h, int(math.ceil((by1 + pad) * h)))
    sx, sy = int(rig["tail_seed"][0] * w), int(rig["tail_seed"][1] * h)
    start = None
    for rad in range(0, 24):
        for dy in range(-rad, rad + 1):
            for dx in range(-rad, rad + 1):
                x, y = sx + dx, sy + dy
                if x0 <= x < x1 and y0 <= y < y1 and passable[y, x]:
                    start = (x, y)
                    break
            if start:
                break
        if start:
            break
    if start is None:
        return None

    mask = np.zeros((h, w), bool)
    stack = [start]
    while stack:
        x, y = stack.pop()
        if not (x0 <= x < x1 and y0 <= y < y1) or mask[y, x] or not passable[y, x]:
            continue
        mask[y, x] = True
        stack.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    count = int(mask.sum())
    if count < 30 or count > 0.12 * w * h:
        return None
    # 只往描边和半透明边上长，碰到别的部件的毛色就停，描边整条带走又不啃到爪子。
    edge = np.zeros_like(mask)
    edge[y0:y1, x0:x1] = (alpha > 0)[y0:y1, x0:x1] & ~passable[y0:y1, x0:x1]
    for _ in range(max(4, round(h * 0.016))):
        mask |= _grow(mask, 3) & edge
    return mask


def _prep_tail(im: Image.Image, rig: dict, dog: np.ndarray) -> _Tail | None:
    """把尾巴从 dog 里拿出来单独成层（原地修改 dog）。"""
    mask = _tail_mask(im, rig)
    if mask is None:
        return None
    h, w = mask.shape
    pv = (rig["tail_pivot"][0] * w, rig["tail_pivot"][1] * h)
    # 尾根取尾巴和身体真正接触的那一段的中点，从这里开始弯，接缝处就不会动。
    touch = _grow(mask, 3) & ~mask & (dog[..., 3] > 128)
    ty, tx = np.nonzero(touch)
    if len(tx) >= 3:
        pv = (float(tx.mean()), float(ty.mean()))
    ys, xs = np.nonzero(mask)
    length = float(np.hypot(xs - pv[0], ys - pv[1]).max())
    if length < 8:
        return None
    # 绕尾根转时每个点离尾根的距离不变，所以尾巴永远落在这个圆里。
    reach = length + 2
    x0, x1 = max(0, int(pv[0] - reach)), min(w, int(math.ceil(pv[0] + reach)))
    y0, y1 = max(0, int(pv[1] - reach)), min(h, int(math.ceil(pv[1] + reach)))
    gy, gx = np.mgrid[y0:y1, x0:x1].astype(np.float32)
    dx, dy = gx - pv[0], gy - pv[1]
    sub = mask[y0:y1, x0:x1]
    # 尾根附近多带一圈身体垫在底下，弯动时接缝两边都是实心的，不会透出一条亮线。
    keep = sub | (_grow(sub, 9) & (np.hypot(dx, dy) < 0.3 * length))
    layer = np.zeros((y1 - y0, x1 - x0, 4), np.uint8)
    layer[keep] = dog[y0:y1, x0:x1][keep]
    dog[mask] = 0
    # 尾根贴着屁股不动，越往尾尖转得越多，整条尾巴像鞭子一样弯而不是整块甩。
    radial = _smooth(0.08 * length, 0.85 * length, np.hypot(dx, dy)).astype(np.float32)
    local = (pv[0] - x0, pv[1] - y0)

    # 每帧只算尾巴可能扫到的像素，省掉框里大片空白。
    alpha = layer[..., 3:4]
    swept = np.zeros(sub.shape, bool)
    for deg in np.linspace(-_MAX_WAG, _MAX_WAG, 15):
        theta = math.radians(deg) * radial
        c, s = np.cos(theta), np.sin(theta)
        swept |= _sample(alpha, local[0] + c * dx + s * dy, local[1] - s * dx + c * dy)[..., 0] > 0.5
    rows, cols = np.nonzero(_grow(swept, 5))
    return _Tail(local, layer, rows + y0, cols + x0, dx[rows, cols], dy[rows, cols], radial[rows, cols])


def _prep_legs(im: Image.Image, rig: dict, occupied: np.ndarray, max_step: float) -> _Legs | None:
    w, h = im.size
    hip = rig["hip"] * h
    # 以两颗种子的中点分界，伸过中线的脚掌也能量全。
    split = (rig["hind_seed"][0] + rig["front_seed"][0]) / 2 * w
    if rig["hind_seed"][0] < rig["front_seed"][0]:
        hind = _flood(im, rig["hind_seed"], lambda x, y: y >= hip - 1 and x < split)
        front = _flood(im, rig["front_seed"], lambda x, y: y >= hip - 1 and x >= split)
    else:
        hind = _flood(im, rig["hind_seed"], lambda x, y: y >= hip - 1 and x >= split)
        front = _flood(im, rig["front_seed"], lambda x, y: y >= hip - 1 and x < split)
    groups = []
    for pts in (hind, front):
        if 24 <= len(pts) <= 0.14 * w * h:
            bottom = max(p[1] for p in pts) + 1
            # 宽度只量腿和脚掌，髋线附近那条腹部描边会一直连到另一组腿。
            low = hip + 0.3 * (bottom - hip)
            xs = [p[0] for p in pts if p[1] >= low]
            groups.append((min(xs), max(xs) + 1, bottom))
        else:
            groups.append(None)
    if groups[0] is None and groups[1] is None:
        return None

    top = int(hip)
    length = max(8.0, max(g[2] for g in groups if g) - top)
    # 两组腿之间的空隙决定窗口能放多宽，免得一组腿把另一组扯过去。
    if groups[0] and groups[1]:
        left, right = sorted((groups[0], groups[1]), key=lambda g: g[0])
        gap = max(4.0, right[0] - left[1])
    else:
        gap = 0.3 * w
    reach = max_step * length + 2
    pad = min(reach, gap * 0.35)
    fall = max(3.0, (gap - 2 * pad) / 2)

    xs = np.arange(w, dtype=np.float32)

    def window(g):
        if g is None:
            return np.zeros(w, np.float32)
        a, b = g[0] - pad, g[1] + pad
        return (_smooth(a - fall, a, xs) * (1 - _smooth(b, b + fall, xs))).astype(np.float32)

    hind_w, front_w = window(groups[0]), window(groups[1])

    # 腿能扫到的范围：现有内容左右各扩一个步幅、往上扩一个抬脚高度，只在窗口里。
    region = occupied[top:].copy()
    spread = region.copy()
    for k in range(1, int(math.ceil(reach)) + 1):
        spread[:, k:] |= region[:, :-k]
        spread[:, :-k] |= region[:, k:]
    lifted = spread.copy()
    for k in range(1, int(math.ceil(_MARK_LIFT * length)) + 3):
        lifted[:-k] |= spread[k:]
    lifted &= ((hind_w + front_w) > 0)[None, :]
    rows, cols = np.nonzero(lifted)

    u = rows.astype(np.float32) / length
    # 前后摆：上段像绕髋转，下段脚掌整体平移，不会被拉斜；抬脚：脚掌整块抬起，腿段略缩。
    ramp_x = np.clip(u / 0.88, 0.0, 1.0)
    ramp_x = ramp_x * ramp_x * (1.6 - 0.6 * ramp_x)
    ramp_y = _smooth(0.0, 0.78, u).astype(np.float32)
    return _Legs(rows + top, cols, ramp_x.astype(np.float32), ramp_y, hind_w[cols], front_w[cols], length)


def _prepare(name: str, im: Image.Image) -> _Prepared | None:
    rig = _RIGS.get(name)
    if rig is None:
        return None
    im, rig, pad = _padded(im, rig)
    rgba = np.asarray(im)
    dog = rgba.copy()
    dog[..., :3] = (rgba[..., :3].astype(np.uint16) * rgba[..., 3:4] + 127) // 255
    shadow = _split_shadow(dog)
    head = int(rig.get("head", 1))
    step = float(rig.get("step", 0.0))
    run_step = float(rig.get("run_step", step))
    tail = _prep_tail(im, rig, dog)
    legs = None
    if "hind_seed" in rig:
        occupied = dog[..., 3] > 0
        if tail is not None:
            occupied[tail.rows, tail.cols] = True
        legs = _prep_legs(im, rig, occupied, max(step, run_step, _MARK_STEP))
    return _Prepared(pad, dog, shadow, tail, legs, head, step, run_step)


def _prepared(name: str, im: Image.Image) -> _Prepared | None:
    if name not in _RIGS:
        return None
    key = (name, im.size)
    if key not in _CACHE:
        try:
            _CACHE[key] = _prepare(name, im)
        except Exception:
            _CACHE[key] = None
    return _CACHE[key]


# ---------------------------------------------------------------- 形变


def _bend_tail(img: np.ndarray, tail: _Tail, phase: float, amp: float, bias: float = 0.0, lag: float = 0.9) -> None:
    """尾巴连续地弯，不切段。离尾根越远，相位越晚，尾尖才像带着惯性甩。

    弯角只跟到尾根的距离有关，每一圈像素整体转动，所以尾巴怎么甩都不会裂开。
    """
    wave = _wave(phase - lag * tail.radial)
    degrees = np.clip(bias + amp * wave, -_MAX_WAG, _MAX_WAG)
    theta = np.radians(degrees) * tail.radial
    c, s = np.cos(theta), np.sin(theta)
    sx = tail.pivot[0] + c * tail.dx + s * tail.dy
    sy = tail.pivot[1] - s * tail.dx + c * tail.dy
    bent = _sample(tail.layer, sx, sy)
    body = img[tail.rows, tail.cols].astype(np.float32)
    img[tail.rows, tail.cols] = _store(body + bent * (1 - body[:, 3:4] / 255))


def _wave(x):
    return 0.82 * np.sin(x) + 0.18 * np.sin(2 * x + 0.45)


def _move_legs(img: np.ndarray, legs: _Legs, hind: tuple[float, float], front: tuple[float, float]) -> None:
    """hind / front：(前后位移像素, 抬起像素)，位移从髋线 0 渐增到脚掌，腿和身体始终连着。"""
    shift_x = legs.ramp_x * (legs.hind * hind[0] + legs.front * front[0])
    shift_y = legs.ramp_y * (legs.hind * hind[1] + legs.front * front[1])
    img[legs.rows, legs.cols] = _store(_sample(img, legs.cols - shift_x, legs.rows + shift_y))


# ---------------------------------------------------------------- 关键帧


def _leg_pose(rig: _Prepared, kind: str, phase: float, level: float, amp_scale: float) -> np.ndarray:
    img = rig.dog.copy()
    legs = rig.legs
    if legs is None:
        return img
    n = legs.length
    if kind == "mark":
        # 后腿朝尾巴那边抬起来，前腿稳稳站着。
        _move_legs(img, legs, (-rig.head * _MARK_STEP * n * level, _MARK_LIFT * n * level), (0.0, 0.0))
        return img
    run = kind == "run"
    amp = (rig.run_step if run else rig.step) * n * amp_scale
    stance = 0.50 if run else 0.62
    lift = (0.26 if run else _WALK_LIFT) * n * (0.7 + 0.3 * amp_scale)
    hs, hl = _step_cycle(phase, stance)
    fs, fl = _step_cycle(phase + math.pi, stance)
    _move_legs(img, legs, (rig.head * hs * amp, hl * lift), (rig.head * fs * amp, fl * lift))
    return img


def _baked(rig: _Prepared, name: str, size: tuple[int, int], kind: str, short: bool) -> list[np.ndarray]:
    """腿的关键帧只算一次。尾巴不烤进去，每帧单独甩，才不会跟着步子一顿一顿。"""
    key = (name, size, kind, short)
    hit = _BAKE.get(key)
    if hit is not None:
        return hit
    scale = 0.62 if short else 1.0
    if kind == "mark":
        frames = [_leg_pose(rig, kind, 0.0, level, 1.0) for level in MARK_LEVELS]
    else:
        count = RUN_FRAMES if kind == "run" else WALK_FRAMES
        frames = [_leg_pose(rig, kind, (i + 0.5) / count * math.tau, 1.0, scale) for i in range(count)]
    _BAKE[key] = frames
    return frames


# ---------------------------------------------------------------- 每帧


def animate_sticker(
    name: str,
    im: Image.Image,
    phase: float,
    pose: str,
    mark: float,
    stride: float | None = None,
    step_scale: float = 1.0,
    planted: bool = False,
) -> tuple[Image.Image, tuple[int, int]]:
    """返回 (摆好姿势的新图, 新图比原图在左、上多出的像素)。

    phase 驱动尾巴；stride 是按走过的距离算出的步态相位，决定播哪一张腿的关键帧。
    没有骨架时原样返回原图和 (0, 0)，调用方不要改这个结果。
    """
    rig = _prepared(name, im)
    if rig is None:
        return im, (0, 0)
    gait = pose in ("walk", "run")
    marking = pose == "mark" and mark > 0.001
    if rig.legs is not None and marking:
        frames = _baked(rig, name, im.size, "mark", False)
        level = min(range(len(MARK_LEVELS)), key=lambda i: abs(MARK_LEVELS[i] - mark))
        img = frames[level].copy()
    elif rig.legs is not None and gait and not planted:
        kind = "run" if pose == "run" else "walk"
        frames = _baked(rig, name, im.size, kind, step_scale < 0.82)
        cycle = phase if stride is None else stride
        index = int(((cycle / math.tau) % 1.0) * len(frames)) % len(frames)
        img = frames[index].copy()
    else:
        img = rig.dog.copy()

    if rig.tail is not None:
        if marking:
            _bend_tail(img, rig.tail, phase * 1.45, 12, 14 * mark)
        elif pose == "run":
            _bend_tail(img, rig.tail, phase, 22, lag=1.1)
        elif pose == "walk":
            _bend_tail(img, rig.tail, phase, 18)
        elif name == "tilt":
            _bend_tail(img, rig.tail, phase * 1.75, 26, lag=1.0)
        else:
            _bend_tail(img, rig.tail, phase * 1.3, 22)

    dog = Image.fromarray(img, "RGBa").convert("RGBA")
    return Image.alpha_composite(rig.shadow, dog), rig.pad
