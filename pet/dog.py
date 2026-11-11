"""小狗的位置、心情和要做的事。"""

from __future__ import annotations

import math
import random
from pathlib import Path

import win32api
import win32con

from pet.motion import MAX_CADENCE, STRIDE
from pet.sprite import GROUND, LH, SNIFF_NOSE, Frame, mark_anchor


def work_area(x: float, y: float) -> tuple[int, int, int, int]:
    monitor = win32api.MonitorFromPoint((int(x), int(y)), win32con.MONITOR_DEFAULTTONEAREST)
    left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Work"]
    return left, top, right, bottom


def label_of(files: list[str], fallback: str = "文件") -> str:
    if not files:
        return fallback
    name = Path(files[0]).name or fallback
    if len(name) > 14:
        name = name[:12] + "…"
    if len(files) > 1:
        return f"{name} 等{len(files)}个"
    return name


# 各姿势下头部中心相对脚下中心点的位置（逻辑像素，面朝右）
HEAD_AT = {
    "sit": (3, -142),
    "pat": (3, -121),
    "hop": (2, -136),
    "walk": (43, -111),
    "run": (38, -117),
    "sniff": (50, -70),
    "eat": (45, -59),
    "dig": (45, -59),
    "sleep": (35, -45),
    "held": (2, -155),
}

PAT_LINES = ["好舒服~", "嘿嘿嘿…", "再摸摸嘛", "最喜欢你了！", "尾巴停不下来啦"]
SNIFF_FOLDER = ["里面有好吃的吗？", "是你的味道！", "这个文件夹我认识", "嗯…有点意思", "闻起来好忙的样子"]
SNIFF_FILE = ["这个味道好熟悉", "是你的味道！", "嗯…有点意思", "闻过啦，没问题", "不是骨头…"]
MARK_LINES = ["这是我的！", "标记好了~", "汪，我的地盘", "这里有我的味道啦"]


class World:
    def __init__(self, scale: float):
        self.scale = scale
        self.cursor = (0, 0)
        self.file_drag = False
        self.drag_pos = (0, 0)
        self.drag_origin: tuple[float, float] | None = None
        self.drag_label: str | None = None
        self.drag_kind = "file"
        # 拖放结束时由 App 写入，小狗读走后清空
        self.drag_end: dict | None = None
        self.hover_files: list[str] = []
        self.hover_point: tuple[int, int] | None = None
        self.pending_drop: dict | None = None
        self.grabbed = False
        self.icons: list[tuple[str, float, float]] = []


class Dog:
    def __init__(self, x: float, y: float, scale: float, affection: int = 0, name: str = "小金"):
        self.name = name
        self.x = x
        self.y = y
        self.scale = scale
        self.facing = 1
        self.state = "sit"
        self.state_t = 0.0
        self.sit_for = 2.2
        self.sleep_for = 12.0
        self.phase = 0.0
        self.clock = 0.0
        self.mode = "free"
        self.expression = "happy"
        self.pupil = (0.0, 0.0)
        self.bubble: str | None = f"{name}来啦！"
        self.bubble_t = 2.0
        self.hearts = 0.0
        self.love = 0.0
        self.sparkle = 0.0
        self.question = 0.0
        self.tilt = 0.0
        self.tilt_to = 0.0
        self.affection = affection
        self.files: list[str] = []
        self.label: str | None = None
        self.file_kind = "file"
        self.file_fly = 0.0
        self.return_to = (x, y)
        self.roll = 0.0
        self.play_kind = ""
        self.play_for = 2.0
        self.target: tuple[float, float] | None = None
        self.calm = 0.0
        self.hovering = False
        self._greeted = False
        self._sniff_said = False
        self.blinking = False
        self._blink_in = random.uniform(2.0, 4.5)
        self._blink_left = 0.0
        self._forced_sleep = False
        self.cx = x
        self.cy = y
        self.rx = 120.0
        self.ry = 80.0
        self.angle = 0.0
        self.lap_left = 0.0
        self.notice = 270 * scale
        self.near = 145 * scale
        self.pat_hand = True
        self._pat_line = 0
        self.treat_left = -1.0
        self.inspect_at: tuple[float, float] | None = None
        self.inspect_label: str | None = None
        self.inspect_kind = "file"
        self._inspect_facing = 1
        self._inspect_said = False
        self._rub_x: float | None = None
        self._rub_dir = 0
        self._rub_travel = 0.0
        self._rub_hits = 0
        self._rub_last = -9.0
        self._icons: list[tuple[str, float, float]] = []
        self._mark_at = -99.0
        self._mark_name = ""
        self._mark_facing = 1
        self._mark_point: tuple[float, float] | None = None
        self._find_point: tuple[float, float] | None = None
        self._find_name = ""
        self._find_facing = 1
        self._find_barks = 0
        self._pooping = False
        self.speed = 0.0
        self.lean = 0.0
        self.stride = 0.0
        self.step_scale = 1.0
        self.planted = True
        self._did_step = False

    # ------------------------------------------------------------ 每帧

    def update(self, dt: float, world: World) -> None:
        dt = max(0.0, min(0.05, dt))
        self.clock += dt
        self._did_step = False
        try:
            self._update(dt, world)
        finally:
            if not self._did_step:
                self.speed = 0.0
                self.planted = True
                self.step_scale = 1.0
                self.lean += (0.0 - self.lean) * min(1.0, dt * 8)

    def _update(self, dt: float, world: World) -> None:
        self.scale = world.scale
        self.notice = 270 * self.scale
        self.near = 145 * self.scale
        self._icons = world.icons
        self.state_t += dt
        self.hovering = False
        self._tick_bubble(dt)
        self._tick_blink(dt)
        self._tick_effects(dt)

        if world.grabbed:
            self.state = "held"
            self.expression = "happy"
            self.roll = 0
            self.treat_left = -1
            self.phase += dt * 4
            self._look_at(world.cursor)
            self._clamp()
            return

        if world.pending_drop is not None:
            drop = world.pending_drop
            world.pending_drop = None
            self._begin_carry(drop)
            return

        if self.state == "carry":
            self._tick_carry(dt)
            return
        if self.state == "return":
            self._tick_return(dt)
            return
        if self.state == "toss":
            self._tick_toss(dt)
            return
        if self.state == "eat":
            self._tick_eat(dt)
            return

        if self.state in ("find_go", "found"):
            self._tick_find(dt)
            return

        if self._pooping and self.state in ("poop_go", "mark"):
            self._tick_mark(dt, world)
            return

        if world.hover_files:
            self._tick_hover(dt, world)
            return

        if world.file_drag:
            self._tick_chase(dt, world)
            return
        self._sniff_said = False

        if world.drag_end is not None:
            end = world.drag_end
            world.drag_end = None
            self._begin_investigate(end)

        if self.state == "investigate":
            self._tick_investigate(dt)
            return
        if self.state == "inspect":
            self._tick_inspect(dt)
            return
        if self.state in ("mark_go", "mark"):
            self._tick_mark(dt, world)
            return

        self._check_rub(world)
        if self.state == "headpat":
            self._tick_headpat(dt, world)
            return
        if self.state == "joy":
            self._tick_joy(dt, world)
            return

        if self._social(dt, world):
            return
        self._idle(dt, world)

    def make_frame(self) -> Frame:
        if self.state == "toss":
            file_mode = "toss"
        elif self.state in ("carry", "return"):
            file_mode = "hold"
        elif self.hovering:
            file_mode = "sniff"
        else:
            file_mode = "none"
        expression = self.expression
        if self.state == "sleep":
            expression = "closed"
        elif self.blinking and expression not in ("joy", "closed"):
            expression = "closed"
        roll = self.roll if self.state == "play" and self.play_kind == "roll" else 0.0
        pat = -1.0
        if self.state == "headpat" and self.pat_hand:
            pat = (self.state_t * 0.9) % 1.0
        return Frame(
            facing=self.facing,
            pose=self._pose(),
            phase=self.phase,
            pupil=self.pupil,
            expression=expression,
            bubble=self.bubble,
            file_mode=file_mode,
            file_label=self.label,
            file_kind=self.file_kind,
            file_fly=self.file_fly if self.state == "toss" else 0.0,
            hearts=self.hearts,
            love=self.love,
            sparkle=self.sparkle,
            question=self.question,
            zzz=self.state == "sleep",
            roll=roll,
            tilt=self.tilt,
            pat=pat,
            treat=self.treat_left if self.state == "eat" else -1.0,
            clock=self.clock,
            mark=self._mark_amount() if self.state == "mark" else 0.0,
            stride=self.stride,
            lean=self.lean,
            step_scale=self.step_scale,
            planted=self.planted,
        )

    def window_origin(self, size: tuple[int, int]) -> tuple[int, int]:
        width, height = size
        ground = GROUND / LH * height
        return int(self.x - width / 2), int(self.y - ground)

    def head_point(self) -> tuple[float, float]:
        dx, dy = HEAD_AT.get(self._pose(), HEAD_AT["sit"])
        return self.x + dx * self.facing * self.scale, self.y + dy * self.scale

    # ------------------------------------------------------------ 指令

    @property
    def busy_with_file(self) -> bool:
        return self.state in ("carry", "return", "toss")

    def pet(self) -> None:
        if self.busy_with_file:
            self.say("等我放好")
            return
        if self.state in ("headpat", "joy"):
            self.hearts = 1
            return
        self.state = "petted"
        self.state_t = 0
        self.expression = "joy"
        self.hearts = 1
        self.calm = 0
        self.roll = 0
        self._forced_sleep = False
        self.affection += 1
        self.say(random.choice(["嘿嘿", "汪！", "舒服~", "再来一下"]))

    def pat_head(self, hand: bool = True) -> None:
        if self.busy_with_file:
            self.say("等我放好")
            return
        if self.state == "headpat":
            self.state_t = min(self.state_t, 1.0)
            return
        self.state = "headpat"
        self.state_t = 0
        self.pat_hand = hand
        self.expression = "joy"
        self.roll = 0
        self.calm = 0
        self.target = None
        self.treat_left = -1
        self._forced_sleep = False
        self._pat_line = random.randrange(len(PAT_LINES))
        self.affection += 3
        self.hearts = 1
        self.say(PAT_LINES[self._pat_line], 1.4)

    def give_treat(self) -> None:
        if self.busy_with_file:
            self.say("等我放好")
            return
        self.state = "eat"
        self.state_t = 0
        self.treat_left = 1.0
        self.expression = "happy"
        self.roll = 0
        self.target = None
        self._forced_sleep = False
        self.say("哇！零食！", 1.2)

    def release(self) -> None:
        self._enter_sit(2.0)
        self.expression = "happy"
        self.say("放下啦")

    def set_mode(self, mode: str) -> None:
        self.mode = mode
        if mode == "follow":
            self.say("跟着你")
        elif mode == "stay":
            self.say("我待在这儿")
            self._enter_sit(60)
        else:
            self.say("我自己玩")
            self._enter_wander()

    def command_sleep(self) -> None:
        self._forced_sleep = True
        self._enter_sleep(28)
        self.say("困了")

    def command_play(self) -> None:
        self._forced_sleep = False
        self._enter_play()

    def command_mark(self) -> None:
        if self.busy_with_file:
            self.say("等我放好")
            return
        self._forced_sleep = False
        self.treat_left = -1
        if not self._begin_mark():
            self.say("没找到可以标记的")

    def command_find(self, name: str, x: float, y: float) -> None:
        """跑到桌面上这个图标旁边，再汪汪叫。"""
        if self.busy_with_file:
            self.say("等我放好")
            return
        tx, ty, facing = self._nose_spot((x, y), top_margin=48)
        self._forced_sleep = False
        self.treat_left = -1
        self.roll = 0
        self._find_name = name
        self._find_point = (float(x), float(y))
        self._find_facing = facing
        self._find_barks = 0
        self.target = (tx, ty)
        self.state = "find_go"
        self.state_t = 0
        self.expression = "curious"
        self.say(f"去找「{self._short_name(name)}」", 1.8)

    def command_poop(self, name: str, x: float, y: float) -> None:
        """跑到回收站旁边，抬腿对着它尿尿。"""
        if self.busy_with_file:
            self.say("等我放好")
            return
        sx, sy, facing = self._mark_stand(x, y)
        stand = self._clamp_point(sx, sy, top_margin=48, inset=64)
        self._forced_sleep = False
        self.treat_left = -1
        self.roll = 0
        self._pooping = True
        self._mark_name = name
        self._mark_point = (float(x), float(y))
        self._mark_facing = facing
        self._mark_at = self.clock
        self.target = stand
        self.state = "poop_go"
        self.state_t = 0
        self.expression = "curious"
        self.say("去回收站！", 1.6)

    def rename(self, name: str) -> None:
        old, self.name = self.name, name
        if self.busy_with_file:
            self.say(f"我叫{name}啦")
            return
        self.state = "joy"
        self.state_t = 0
        self.roll = 0
        self.target = None
        self.treat_left = -1
        self._forced_sleep = False
        self.hearts = 1
        self.say(f"我叫{name}啦！" if old != name else f"对，我就是{name}！", 2.6)

    def say(self, text: str, duration: float = 2.2) -> None:
        self.bubble = text
        self.bubble_t = duration

    # ------------------------------------------------------------ 内部

    def _pose(self) -> str:
        state = self.state
        if state == "held":
            return "held"
        if state == "sleep":
            return "sleep"
        if state in ("sniff", "inspect"):
            return "sniff"
        if state == "headpat":
            return "pat"
        if state in ("joy", "found"):
            return "hop"
        if state == "eat":
            return "eat" if self.state_t > 0.5 else "sit"
        if state == "play" and self.play_kind == "dig":
            return "dig"
        if state == "mark":
            return "mark"
        if state in ("wander", "approach", "mark_go"):
            return "walk"
        if state in ("investigate", "find_go", "poop_go"):
            return "run"
        if state in ("run", "carry", "return") or (state == "play" and self.play_kind == "pounce"):
            return "run"
        return "sit"

    def _tick_bubble(self, dt: float) -> None:
        if self.bubble_t > 0:
            self.bubble_t -= dt
            if self.bubble_t <= 0:
                self.bubble = None

    def _tick_blink(self, dt: float) -> None:
        if self._blink_left > 0:
            self._blink_left -= dt
            self.blinking = self._blink_left > 0
            if not self.blinking:
                self._blink_in = random.uniform(2.2, 5.5)
            return
        self._blink_in -= dt
        if self._blink_in <= 0 and self.state != "sleep":
            self._blink_left = 0.12
            self.blinking = True

    def _tick_effects(self, dt: float) -> None:
        if self.hearts > 0:
            self.hearts = max(0.0, self.hearts - dt / 1.5)
        love_to = 1.0 if self.state in ("headpat", "joy") else 0.0
        sparkle_to = 1.0 if self.state in ("headpat", "joy") else 0.0
        question_to = 1.0 if self.state in ("investigate", "find_go", "poop_go") or (self.state in ("sniff", "inspect") and self.expression == "curious") else 0.0
        self.love += (love_to - self.love) * min(1.0, dt * 3)
        self.sparkle += (sparkle_to - self.sparkle) * min(1.0, dt * 3)
        self.question += (question_to - self.question) * min(1.0, dt * 6)
        self.tilt += (self.tilt_to - self.tilt) * min(1.0, dt * 6)
        self.tilt_to = 0.0

    def _look_at(self, pos: tuple[float, float]) -> None:
        hx, hy = self.head_point()
        dx = pos[0] - hx
        dy = pos[1] - hy
        reach = 140 * self.scale
        target_x = max(-1.0, min(1.0, (dx * self.facing) / reach))
        target_y = max(-1.0, min(1.0, dy / reach))
        self.pupil = (
            self.pupil[0] + (target_x - self.pupil[0]) * 0.35,
            self.pupil[1] + (target_y - self.pupil[1]) * 0.35,
        )

    def _dist(self, pos: tuple[float, float]) -> float:
        return math.hypot(pos[0] - self.x, pos[1] - (self.y - 130 * self.scale))

    def _beside(self, pos: tuple[float, float]) -> tuple[float, float]:
        gap = 115 * self.scale
        tx = pos[0] - gap if pos[0] >= self.x else pos[0] + gap
        ty = pos[1] + 70 * self.scale
        return self._clamp_point(tx, ty)

    def _nose_spot(self, point: tuple[float, float], top_margin: float = 110) -> tuple[float, float, int]:
        """站在哪里、朝哪边，鼻尖正好凑到 point 旁边。"""
        px, py = point
        s = self.scale
        reach = (SNIFF_NOSE[0] + 22) * s
        left, top, right, bottom = work_area(px, py)
        facing = 1 if self.x < px else -1
        if facing == 1 and px - reach - 80 * s < left:
            facing = -1
        elif facing == -1 and px + reach + 80 * s > right:
            facing = 1
        x = px - facing * reach
        y = py - SNIFF_NOSE[1] * s + 6 * s
        x, y = self._clamp_point(x, y, top_margin=top_margin)
        return x, y, facing

    def _ease(self, desired: float, dt: float, cruise: float) -> None:
        """速度缓入缓出。刚起步时更慢一点，身体才能先往后坐。"""
        diff = desired - self.speed
        rate = (720.0 if diff > 0 else 980.0) * self.scale
        if self.speed < 18 * self.scale and diff > 0:
            rate *= 0.12
        step = rate * dt
        if abs(diff) <= step:
            self.speed = desired
        else:
            self.speed += math.copysign(step, diff)
        span = max(cruise, self.speed, 40 * self.scale)
        target = max(-1.0, min(1.0, (self.speed - desired) / span))
        self.lean += (target - self.lean) * min(1.0, dt * 6)

    def _note_move(self, moved: float, kind: str) -> None:
        """步态相位跟实际位移走。慢下来就换成步幅更短的一套帧。"""
        if moved < 0.01:
            return
        cruise = (72.0 if kind == "walk" else 280.0) * self.scale
        if self.step_scale >= 1.0 and self.speed < cruise * 0.62:
            self.step_scale = 0.62
        elif self.step_scale < 1.0 and self.speed > cruise * 0.9:
            self.step_scale = 1.0
        base = max(STRIDE[kind] * self.scale * self.step_scale, self.speed / MAX_CADENCE[kind])
        self.stride += moved / max(base, 0.01) * math.tau

    def _step(self, tx: float, ty: float, speed: float, dt: float, top_margin: float = 230, face: bool = True, inset: float = 96) -> bool:
        self._did_step = True
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        kind = "run" if speed >= 190 * self.scale else "walk"
        # 跑过来时减速有下限，不一定能慢到下面的停步速度；这一步能够到目标就算到了。
        if dist < 3 or dist <= self.speed * dt:
            self._note_move(dist, kind)
            self.x, self.y = tx, ty
            self.speed = 0.0
            self.planted = True
            return True
        if dist < 28 * self.scale and self.speed < 22 * self.scale:
            self._ease(0.0, dt, speed)
            self.planted = True
            if self.speed < 12 * self.scale or dist < 3:
                self.speed = 0.0
                self.x, self.y = tx, ty
                return True
            return False
        want = self.facing
        if face and abs(dx) > 8:
            want = 1 if dx > 0 else -1
        if face and want != self.facing and self.speed > 34 * self.scale:
            # 先沿原来的朝向把速度收掉，再掉头，避免滑着转身。
            self._ease(0.0, dt, speed)
            self.planted = self.speed < 20 * self.scale
            if self.speed < 1:
                return False
            ox = self.x
            self.x += self.facing * self.speed * dt
            intended = abs(self.x - ox)
            self._clamp(goal_x=tx, top_margin=top_margin, inset=inset)
            self._note_move(min(intended, abs(self.x - ox)), kind)
            return False
        if face and abs(dx) > 8:
            self.facing = want
        slow = 110 * self.scale
        desired = speed if dist > slow else speed * max(0.12, dist / slow)
        self._ease(desired, dt, speed)
        self.planted = self.speed < 16 * self.scale
        # 刚起步的几帧先站着把重心坐回去，速度起来了再迈步。
        if self.speed < 8 * self.scale:
            return False
        step = min(self.speed * dt, dist)
        ox, oy = self.x, self.y
        self.x += dx / dist * step
        self.y += dy / dist * step
        intended = math.hypot(self.x - ox, self.y - oy)
        self._clamp(goal_x=tx, top_margin=top_margin, inset=inset)
        self._note_move(min(intended, math.hypot(self.x - ox, self.y - oy)), kind)
        return False

    def _clamp_point(self, x: float, y: float, top_margin: float = 230, inset: float = 100) -> tuple[float, float]:
        left, top, right, bottom = work_area(x, y)
        pad = inset * self.scale
        y = min(max(y, top + top_margin * self.scale), bottom - 18 * self.scale)
        x = min(max(x, left + pad), right - pad)
        return x, y

    def _clamp(self, goal_x: float | None = None, top_margin: float = 230, inset: float = 96) -> None:
        left, top, right, bottom = work_area(self.x, self.y)
        pad = inset * self.scale
        self.y = min(max(self.y, top + top_margin * self.scale), bottom - 16 * self.scale)
        if goal_x is not None and (goal_x < left + 8 or goal_x > right - 8):
            virtual_left = win32api.GetSystemMetrics(76)
            virtual_width = win32api.GetSystemMetrics(78)
            self.x = min(max(self.x, virtual_left + pad), virtual_left + virtual_width - pad)
        else:
            self.x = min(max(self.x, left + pad), right - pad)

    def _random_point(self, near: bool = False) -> tuple[float, float]:
        left, top, right, bottom = work_area(self.x, self.y)

        def span(lo: float, hi: float, fallback: float) -> float:
            return fallback if hi <= lo else random.uniform(lo, hi)

        if near:
            x = self.x + random.uniform(-180, 180) * self.scale
            y = self.y + random.uniform(-70, 70) * self.scale
        else:
            x = span(left + 110 * self.scale, right - 110 * self.scale, (left + right) / 2)
            y = span(top + 250 * self.scale, bottom - 36 * self.scale, (top + bottom) / 2)
        return self._clamp_point(x, y)

    def _enter_sit(self, duration: float | None = None) -> None:
        self.state = "sit"
        self.state_t = 0
        self.sit_for = duration if duration is not None else random.uniform(2.6, 6.2)
        self.roll = 0
        self.target = None
        self._pooping = False
        self.expression = "normal"

    def _enter_wander(self) -> None:
        self.state = "wander"
        self.state_t = 0
        self.roll = 0
        self.target = self._random_point()
        self.expression = "normal"

    def _enter_sleep(self, duration: float | None = None) -> None:
        self.state = "sleep"
        self.state_t = 0
        self.sleep_for = duration if duration is not None else random.uniform(10, 18)
        self.roll = 0
        self.expression = "closed"

    def _enter_play(self) -> None:
        self.state = "play"
        self.state_t = 0
        self.play_kind = random.choice(["roll", "dig", "spin", "pounce"])
        self.play_for = random.uniform(2.0, 2.8)
        self.roll = 0
        self.say({"roll": "翻一个", "dig": "挖挖", "spin": "追尾巴", "pounce": "嘿！"}[self.play_kind], 1.6)
        if self.play_kind == "pounce":
            self.target = self._random_point(near=True)

    # ------------------------------------------------------------ 摸头、零食

    def _check_rub(self, world: World) -> None:
        """鼠标在头上来回蹭几下，也算摸头。"""
        if self.state in ("held", "eat"):
            self._rub_x = None
            return
        cx, cy = world.cursor
        hx, hy = self.head_point()
        inside = math.hypot(cx - hx, cy - hy) < 54 * self.scale
        if self.clock - self._rub_last > 0.9:
            self._rub_hits = 0
        if not inside:
            self._rub_x = None
            self._rub_dir = 0
            return
        if self._rub_x is not None:
            dx = cx - self._rub_x
            if abs(dx) > 1.5:
                d = 1 if dx > 0 else -1
                if d != self._rub_dir:
                    if self._rub_dir != 0 and self._rub_travel > 10 * self.scale:
                        self._rub_hits += 1
                        self._rub_last = self.clock
                    self._rub_dir = d
                    self._rub_travel = 0.0
                self._rub_travel += abs(dx)
        self._rub_x = cx
        if self._rub_hits >= 3:
            self._rub_hits = 0
            if self.state == "headpat":
                self.state_t = min(self.state_t, 1.0)
            else:
                self.pat_head(hand=False)

    def _tick_headpat(self, dt: float, world: World) -> None:
        self.expression = "joy"
        self.phase += dt * 7
        self.pupil = (0.0, -0.3)
        line = int(self.state_t / 1.3)
        if line > 0 and self.bubble_t <= 0.1:
            self._pat_line = (self._pat_line + 1) % len(PAT_LINES)
            self.say(PAT_LINES[self._pat_line], 1.3)
        if int(self.state_t / 0.9) != int((self.state_t - dt) / 0.9):
            self.hearts = 1
        if self.state_t > 3.6:
            self.state = "joy"
            self.state_t = 0
            self.say(random.choice(["汪汪！", f"{self.name}最喜欢你了！", "开心到转圈圈！"]), 2.0)

    def _tick_joy(self, dt: float, world: World) -> None:
        self.expression = "joy"
        self.phase += dt * 7.5
        if self.state_t > 2.4:
            self._enter_sit(3.0)
            self.expression = "happy"
            self.hearts = 0.8

    def _tick_eat(self, dt: float) -> None:
        self.phase += dt * 4
        if self.state_t < 0.5:
            self.expression = "happy"
            return
        self.expression = "happy"
        self.treat_left = max(0.0, 1 - (self.state_t - 0.5) / 2.4)
        if self.treat_left <= 0:
            self.treat_left = -1
            self.affection += 2
            self.state = "joy"
            self.state_t = 0
            self.hearts = 1
            self.say(random.choice(["好吃！", "还有吗？", "谢谢你~"]), 2.0)

    # ------------------------------------------------------------ 文件、文件夹

    def _begin_carry(self, drop: dict) -> None:
        files = list(drop.get("files") or [])
        self.files = files
        self.label = label_of(files, drop.get("label") or "文件")
        self.file_kind = "folder" if files and all(Path(f).is_dir() for f in files[:3]) else "file"
        origin = drop.get("origin") or drop.get("point") or (self.x, self.y)
        self.return_to = (float(origin[0]), float(origin[1]))
        self.file_fly = 0
        self.state = "carry"
        self.state_t = 0
        self.expression = "happy"
        self.treat_left = -1
        left, top, right, bottom = work_area(self.x, self.y)
        ceiling = top + 240 * self.scale
        floor = bottom - 24 * self.scale
        self.cx = (left + right) / 2
        self.cy = (ceiling + floor) / 2
        self.rx = max(80 * self.scale, min((right - left) * 0.26, 300 * self.scale))
        self.ry = max(56 * self.scale, min((floor - ceiling) * 0.32, 180 * self.scale))
        self.angle = math.atan2(self.y - self.cy, self.x - self.cx)
        self.lap_left = math.tau
        self.bubble = self.label
        self.bubble_t = 30

    def _tick_carry(self, dt: float) -> None:
        self.expression = "happy"
        self.bubble = self.label
        self.bubble_t = 30
        speed = 220 * self.scale
        radius = max(1.0, (self.rx + self.ry) / 2)
        delta = speed / radius * dt
        self.angle += delta
        self.lap_left -= delta
        ox, oy = self.x, self.y
        self.x = self.cx + math.cos(self.angle) * self.rx
        self.y = self.cy + math.sin(self.angle) * self.ry
        self.facing = 1 if -math.sin(self.angle) >= 0 else -1
        self._did_step = True
        self.speed = 300 * self.scale
        self.planted = False
        self.step_scale = 1.0
        self._note_move(math.hypot(self.x - ox, self.y - oy), "run")
        self.lean += (0.0 - self.lean) * min(1.0, dt * 4)
        self.pupil = (0.55, -0.05)
        self._clamp(goal_x=self.x)
        if self.lap_left <= 0:
            self.state = "return"
            self.state_t = 0
            self.say("还给你", 2.4)

    def _tick_return(self, dt: float) -> None:
        self.expression = "happy"
        tx, ty = self._clamp_point(*self.return_to)
        self._look_at((tx, ty))
        if self._step(tx, ty, 250 * self.scale, dt):
            self.state = "toss"
            self.state_t = 0
            self.file_fly = 0
            self.say("还给你", 1.6)

    def _tick_toss(self, dt: float) -> None:
        self.expression = "happy"
        self.phase += dt * 4
        self.file_fly = min(1.0, self.state_t / 0.8)
        if self.state_t >= 1.05:
            self.files = []
            self.label = None
            self.file_fly = 0
            self._enter_sit(2.2)
            self.expression = "happy"
            self.hearts = 0.7

    def _tick_hover(self, dt: float, world: World) -> None:
        self.state = "sniff"
        self.hovering = True
        self.label = label_of(world.hover_files)
        self.file_kind = "folder" if world.hover_files and Path(world.hover_files[0]).is_dir() else "file"
        self.bubble = self.label
        self.bubble_t = 6
        point = world.hover_point or world.cursor
        if abs(point[0] - self.x) > 8:
            self.facing = 1 if point[0] > self.x else -1
        self.phase += dt * 7
        self.expression = "curious"
        self._look_at(point)

    def _tick_chase(self, dt: float, world: World) -> None:
        """有人在拖文件/文件夹：跑过去，凑近了就歪着头闻。"""
        self.calm = 0
        pos = world.drag_pos
        self._look_at(pos)
        if self.state == "sleep" and self._forced_sleep:
            return
        if self.mode == "stay":
            if abs(pos[0] - self.x) > 12:
                self.facing = 1 if pos[0] > self.x else -1
            self.state = "watch"
            self.expression = "curious"
            self.tilt_to = 12
            self.phase += dt * 4
            return
        if self.state in ("headpat", "joy", "eat"):
            self.treat_left = -1
        tx, ty, facing = self._nose_spot(pos)
        dist = math.hypot(tx - self.x, ty - self.y)
        if dist < 40 * self.scale:
            self.state = "sniff"
            self.facing = facing
            self.expression = "curious"
            self.phase += dt * 8
            self._step(tx, ty, 160 * self.scale, dt, top_margin=110)
            self.facing = facing
            if not self._sniff_said:
                label = world.drag_label
                self.say(f"「{label}」？" if label else "让我闻闻", 2.4)
                self._sniff_said = True
            return
        self.state = "run"
        self.expression = "curious" if dist > 200 * self.scale else "happy"
        speed = (420 if dist > 500 * self.scale else 300) * self.scale
        self._step(tx, ty, speed, dt, top_margin=110)

    def _begin_investigate(self, end: dict) -> None:
        if self.mode == "stay" or (self.state == "sleep" and self._forced_sleep) or self.busy_with_file:
            return
        self.inspect_at = (float(end["point"][0]), float(end["point"][1]))
        self.inspect_label = end.get("label")
        self.inspect_kind = end.get("kind") or "file"
        self.state = "investigate"
        self.state_t = 0
        self.expression = "curious"
        self.treat_left = -1
        self._inspect_said = False
        if self._dist(self.inspect_at) > 260 * self.scale:
            self.say("那是什么？", 1.6)

    def _tick_investigate(self, dt: float) -> None:
        if self.inspect_at is None:
            self._enter_sit()
            return
        tx, ty, facing = self._nose_spot(self.inspect_at)
        self._inspect_facing = facing
        self._look_at(self.inspect_at)
        self.expression = "curious"
        dist = math.hypot(tx - self.x, ty - self.y)
        speed = (420 if dist > 500 * self.scale else 300) * self.scale
        if self._step(tx, ty, speed, dt, top_margin=110) or self.state_t > 8:
            self.facing = facing
            self.state = "inspect"
            self.state_t = 0
            label = self.inspect_label
            self.say(f"嗅嗅…「{label}」？" if label else "嗅嗅…", 1.8)

    def _tick_inspect(self, dt: float) -> None:
        self.facing = self._inspect_facing
        if self.inspect_at:
            self._look_at(self.inspect_at)
        if self.state_t < 1.9:
            self.expression = "curious"
            self.phase += dt * 9
            return
        if not self._inspect_said:
            self._inspect_said = True
            lines = SNIFF_FOLDER if self.inspect_kind == "folder" else SNIFF_FILE
            self.say(random.choice(lines), 2.2)
            self.hearts = 1
            self.affection += 1
        self.expression = "happy"
        self.phase += dt * 5
        if self.state_t > 3.4:
            self._enter_sit(2.6)
            self.expression = "happy"
            self.inspect_at = None

    # ------------------------------------------------------------ 标记

    def _mark_amount(self) -> float:
        t = self.state_t
        rise, hold, fall = 0.42, 1.45, 0.38
        if t < rise:
            u = t / rise
            return u * u * (3 - 2 * u)
        if t < rise + hold:
            return 1.0
        if t < rise + hold + fall:
            u = (t - rise - hold) / fall
            u = u * u * (3 - 2 * u)
            return 1.0 - u
        return 0.0

    def _short_name(self, name: str) -> str:
        text = name.strip()
        if len(text) > 8:
            text = text[:7] + "…"
        return text

    def _mark_stand(self, icon_x: float, icon_y: float) -> tuple[float, float, int]:
        left, _top, right, _bottom = work_area(icon_x, icon_y)
        facing = 1 if (right - icon_x) >= (icon_x - left) else -1
        dx, dy = mark_anchor(facing)
        return icon_x - dx * self.scale, icon_y - dy * self.scale, facing

    def _begin_mark(self) -> bool:
        self._pooping = False
        icons = [(name, x, y) for name, x, y in self._icons if name and name != self._mark_name]
        if not icons:
            icons = [(name, x, y) for name, x, y in self._icons if name]
        if not icons:
            return False
        left, top, right, bottom = work_area(self.x, self.y)
        nearby = [
            item for item in icons
            if left - 12 <= item[1] <= right + 12 and top - 12 <= item[2] <= bottom + 12
        ]
        pool = nearby or icons
        pool.sort(key=lambda item: math.hypot(item[1] - self.x, item[2] - self.y))
        if len(pool) > 4 and random.random() < 0.75:
            pool = pool[: max(4, len(pool) // 3)]
        valid = []
        for name, ix, iy in pool:
            sx, sy, face = self._mark_stand(ix, iy)
            cx, cy = self._clamp_point(sx, sy, top_margin=48, inset=64)
            if math.hypot(sx - cx, sy - cy) > 80 * self.scale:
                continue
            valid.append(((name, ix, iy), (cx, cy), face))
            if len(valid) >= 6:
                break
        if valid:
            choice, stand, facing = random.choice(valid)
        else:
            name, ix, iy = pool[0]
            sx, sy, face = self._mark_stand(ix, iy)
            stand = self._clamp_point(sx, sy, top_margin=48, inset=64)
            facing = face
            choice = (name, ix, iy)
        self._mark_name = choice[0]
        self._mark_point = (choice[1], choice[2])
        self._mark_facing = facing
        self._mark_at = self.clock
        self.target = stand
        self.state = "mark_go"
        self.state_t = 0
        self.expression = "curious"
        self.treat_left = -1
        self.roll = 0
        self.say(f"「{self._short_name(choice[0])}」？", 1.6)
        return True

    def _tick_mark(self, dt: float, world: World) -> None:
        if self._mark_point is not None:
            self._look_at(self._mark_point)
        if self.state in ("mark_go", "poop_go"):
            self.expression = "curious"
            if self.target is None:
                self._enter_sit()
                return
            if self.state == "poop_go" and not self.bubble:
                self.say("去回收站！", 1.6)
            dist = math.hypot(self.target[0] - self.x, self.target[1] - self.y)
            if self.state == "poop_go":
                speed = (420 if dist > 500 * self.scale else 300) * self.scale
            else:
                speed = 78 * self.scale
            close = dist < 46 * self.scale
            if close:
                self.facing = self._mark_facing
            arrived = self._step(self.target[0], self.target[1], speed, dt, top_margin=48, face=not close, inset=64)
            if arrived or self.state_t > 12:
                self.x, self.y = self.target
                self.facing = self._mark_facing
                self._clamp(top_margin=48, inset=64)
                self.state = "mark"
                self.state_t = 0
                if self._pooping:
                    self.say("嗯……拉好啦", 2.2)
                else:
                    line = random.choice(MARK_LINES)
                    if random.random() < 0.55:
                        line = f"「{self._short_name(self._mark_name)}」是我的！"
                    self.say(line, 2.2)
            return
        self.facing = self._mark_facing
        self.expression = "happy"
        self.phase += dt * 7.2
        if self.state_t > 2.45:
            self._enter_sit(2.2)
            self.expression = "happy"

    def _tick_find(self, dt: float) -> None:
        if self._find_point is not None:
            self._look_at(self._find_point)
        if self.state == "find_go":
            self.expression = "curious"
            if self.target is None:
                self._enter_sit()
                return
            if not self.bubble:
                self.say(f"去找「{self._short_name(self._find_name)}」", 1.6)
            tx, ty = self.target
            dist = math.hypot(tx - self.x, ty - self.y)
            speed = (420 if dist > 500 * self.scale else 300) * self.scale
            close = dist < 48 * self.scale
            if close:
                self.facing = self._find_facing
            arrived = self._step(tx, ty, speed, dt, top_margin=48, face=not close, inset=100)
            if arrived:
                self.facing = self._find_facing
                self.state = "found"
                self.state_t = 0
                self._find_barks = 1
                self.expression = "joy"
                self.hearts = 1
                self.say("汪汪！", 1.3)
                return
            if self.state_t > 12:
                self.say("跑不过去…")
                self._enter_sit(2.0)
            return
        self.facing = self._find_facing
        self.expression = "joy"
        self.phase += dt * 8
        if self._find_barks < 2 and self.state_t > 0.95:
            self._find_barks = 2
            self.hearts = 1
            self.say("汪！在这儿！", 1.8)
        if self.state_t > 2.7:
            self._enter_sit(2.4)
            self.expression = "happy"

    # ------------------------------------------------------------ 平时

    def _social(self, dt: float, world: World) -> bool:
        dist = self._dist(world.cursor)
        self._look_at(world.cursor)
        if self.state == "sleep" and self._forced_sleep:
            if dist < 90 * self.scale:
                self._forced_sleep = False
                self._enter_sit(1.6)
                self.expression = "happy"
                self.say("嗯？")
                return True
            return False

        if self.mode == "follow":
            self.calm = 0
            if dist < 115 * self.scale:
                self.state = "watch"
                self.expression = "happy"
                self.phase += dt * 4.0
                if abs(world.cursor[0] - self.x) > 10:
                    self.facing = 1 if world.cursor[0] > self.x else -1
            else:
                self.state = "approach"
                self.expression = "normal"
                speed = 155 * self.scale
                self._step(*self._beside(world.cursor), speed, dt)
            return True

        if self.state == "sleep":
            if dist < 125 * self.scale:
                self._enter_sit(1.6)
                self.expression = "happy"
                self.say("嗯？")
                return True
            return False

        if self.state == "play" and self.state_t < self.play_for and dist > 95 * self.scale:
            return False
        if self.state == "petted":
            return False

        if dist < self.notice:
            self.calm = 0
            if self.mode == "stay" or dist < self.near:
                if self.state != "watch":
                    self.state = "watch"
                    self.state_t = 0
                self.expression = "happy"
                self.phase += dt * 4.0
                # 盯着不动的鼠标看久了，会好奇地歪歪头
                if self.state_t > 4 and int(self.state_t / 3) % 2 == 1:
                    self.tilt_to = 10
                if abs(world.cursor[0] - self.x) > 8:
                    self.facing = 1 if world.cursor[0] > self.x else -1
                if not self._greeted and dist < self.near:
                    self.say(random.choice(["汪", "汪", f"{self.name}在这儿！"]))
                    self._greeted = True
            else:
                self._greeted = False
                self.state = "approach"
                self.expression = "normal"
                speed = 125 * self.scale
                self._step(*self._beside(world.cursor), speed, dt)
            return True

        if dist > self.notice * 1.3:
            self._greeted = False
        return False

    def _idle(self, dt: float, world: World) -> None:
        self.calm += dt
        self._look_at(world.cursor)
        if self.state == "wander":
            self.expression = "normal"
            speed = 72 * self.scale
            if self.target is None:
                self.target = self._random_point()
            if self._step(self.target[0], self.target[1], speed, dt) or self.state_t > 14:
                self._enter_sit()
            return
        if self.state == "play":
            self._tick_play(dt)
            return
        if self.state == "petted":
            self.expression = "joy" if self.state_t < 1.2 else "happy"
            self.phase += dt * 4.0
            if self.state_t > 2.1:
                self._enter_sit(2.0)
                self.expression = "happy"
            return
        if self.state == "sleep":
            self.expression = "closed"
            self.phase += dt * 1.3
            if self.state_t > self.sleep_for:
                self._forced_sleep = False
                self._enter_sit()
                self.say("哈啊")
            return
        if self.state != "sit":
            self._enter_sit(random.uniform(1.2, 2.6))
            return
        if self.expression != "happy" or self.state_t > 2.5:
            self.expression = "normal"
        self.phase += dt * 4.2
        if self.state_t > self.sit_for:
            self._next_idle()

    def _tick_play(self, dt: float) -> None:
        self.expression = "happy"
        if self.play_kind == "roll":
            self.roll = min(360.0, self.state_t / max(0.2, self.play_for) * 360)
            self.phase += dt * 3
        elif self.play_kind == "dig":
            self.roll = 0
            self.phase += dt * 14
        elif self.play_kind == "spin":
            self.roll = 0
            self.phase += dt * 14
            if int(self.state_t * 7) != int((self.state_t - dt) * 7):
                self.facing *= -1
        elif self.play_kind == "pounce":
            self.roll = 0
            speed = 300 * self.scale
            if self.target and self._step(self.target[0], self.target[1], speed, dt):
                self._enter_sit(1.3)
                self.expression = "happy"
                return
        if self.play_kind != "pounce" and self.state_t > self.play_for:
            self.roll = 0
            self._enter_sit()

    def _next_idle(self) -> None:
        if self.mode == "stay":
            self._enter_sit(40)
            return
        if self.mode != "follow" and self.clock - self._mark_at > 26 and self._icons and random.random() < 0.36:
            if self._begin_mark():
                return
        roll = random.random()
        if self.calm > 18 and roll < 0.4:
            self._enter_sleep()
        elif roll < 0.72:
            self._enter_play()
        else:
            self._enter_wander()
