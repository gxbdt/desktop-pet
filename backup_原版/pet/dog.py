"""小狗的位置、心情和要做的事。"""

from __future__ import annotations

import math
import random
from pathlib import Path

import win32api
import win32con

from pet.sprite import GROUND, LH, Frame

SHELL_DRAG = "SysDragImage"


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


class World:
    def __init__(self, scale: float):
        self.scale = scale
        self.cursor = (0, 0)
        self.file_drag = False
        self.drag_pos = (0, 0)
        self.drag_origin: tuple[float, float] | None = None
        self.hover_files: list[str] = []
        self.hover_point: tuple[int, int] | None = None
        self.pending_drop: dict | None = None
        self.grabbed = False


class Dog:
    def __init__(self, x: float, y: float, scale: float):
        self.x = x
        self.y = y
        self.scale = scale
        self.facing = 1
        self.state = "sit"
        self.state_t = 0.0
        self.sit_for = 2.2
        self.sleep_for = 12.0
        self.phase = 0.0
        self.mode = "free"
        self.expression = "happy"
        self.pupil = (0.0, 0.0)
        self.bubble: str | None = "汪"
        self.bubble_t = 2.0
        self.hearts = 0.0
        self.files: list[str] = []
        self.label: str | None = None
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

    def update(self, dt: float, world: World) -> None:
        dt = max(0.0, min(0.05, dt))
        self.scale = world.scale
        self.notice = 270 * self.scale
        self.near = 145 * self.scale
        self.state_t += dt
        self.hovering = False
        self._tick_bubble(dt)
        self._tick_blink(dt)
        if self.hearts > 0:
            self.hearts = max(0.0, self.hearts - dt / 1.5)

        if world.grabbed:
            self.state = "held"
            self.expression = "happy"
            self.roll = 0
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

        if world.hover_files:
            self._tick_hover(dt, world)
            return

        if world.file_drag:
            self._tick_chase(dt, world)
            return
        self._sniff_said = False

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
        expression = "closed" if self.state == "sleep" or self.blinking else self.expression
        roll = self.roll if self.state == "play" and self.play_kind == "roll" else 0.0
        return Frame(
            facing=self.facing,
            pose=self._pose(),
            phase=self.phase,
            pupil=self.pupil,
            expression=expression,
            bubble=self.bubble,
            file_mode=file_mode,
            file_label=self.label,
            file_fly=self.file_fly if self.state == "toss" else 0.0,
            hearts=self.hearts,
            zzz=self.state == "sleep",
            roll=roll,
        )

    def window_origin(self, size: tuple[int, int]) -> tuple[int, int]:
        width, height = size
        ground = GROUND / LH * height
        return int(self.x - width / 2), int(self.y - ground)

    def pet(self) -> None:
        if self.state in ("carry", "return", "toss"):
            self.say("等我放好")
            return
        self.state = "petted"
        self.state_t = 0
        self.expression = "happy"
        self.hearts = 1
        self.calm = 0
        self.roll = 0
        self.say(random.choice(["嘿嘿", "汪", "舒服"]))

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
        self._enter_play()

    def say(self, text: str, duration: float = 2.2) -> None:
        self.bubble = text
        self.bubble_t = duration

    def _pose(self) -> str:
        if self.state == "held":
            return "held"
        if self.state == "sleep":
            return "sleep"
        if self.state == "sniff":
            return "sniff"
        if self.state == "play" and self.play_kind == "dig":
            return "dig"
        if self.state in ("wander", "approach"):
            return "walk"
        if self.state in ("run", "carry", "return") or (self.state == "play" and self.play_kind == "pounce"):
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

    def _look_at(self, pos: tuple[float, float]) -> None:
        dx = pos[0] - self.x
        dy = pos[1] - (self.y - 140 * self.scale)
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

    def _step(self, tx: float, ty: float, speed: float, dt: float) -> bool:
        dx, dy = tx - self.x, ty - self.y
        dist = math.hypot(dx, dy)
        if dist < 3:
            self.x, self.y = tx, ty
            return True
        step = min(speed * dt, dist)
        self.x += dx / dist * step
        self.y += dy / dist * step
        if abs(dx) > 6:
            self.facing = 1 if dx > 0 else -1
        self._clamp(goal_x=tx)
        return False

    def _clamp_point(self, x: float, y: float) -> tuple[float, float]:
        left, top, right, bottom = work_area(x, y)
        inset = 100 * self.scale
        y = min(max(y, top + 230 * self.scale), bottom - 18 * self.scale)
        x = min(max(x, left + inset), right - inset)
        return x, y

    def _clamp(self, goal_x: float | None = None) -> None:
        left, top, right, bottom = work_area(self.x, self.y)
        inset = 96 * self.scale
        self.y = min(max(self.y, top + 230 * self.scale), bottom - 16 * self.scale)
        if goal_x is not None and (goal_x < left + 8 or goal_x > right - 8):
            virtual_left = win32api.GetSystemMetrics(76)
            virtual_width = win32api.GetSystemMetrics(78)
            self.x = min(max(self.x, virtual_left + inset), virtual_left + virtual_width - inset)
        else:
            self.x = min(max(self.x, left + inset), right - inset)

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

    def _begin_carry(self, drop: dict) -> None:
        files = list(drop.get("files") or [])
        self.files = files
        self.label = label_of(files, drop.get("label") or "文件")
        origin = drop.get("origin") or drop.get("point") or (self.x, self.y)
        self.return_to = (float(origin[0]), float(origin[1]))
        self.file_fly = 0
        self.state = "carry"
        self.state_t = 0
        self.expression = "happy"
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
        self.x = self.cx + math.cos(self.angle) * self.rx
        self.y = self.cy + math.sin(self.angle) * self.ry
        self.facing = 1 if -math.sin(self.angle) >= 0 else -1
        self.phase += dt * 12
        self.pupil = (0.55, -0.05)
        self._clamp(goal_x=self.x)
        if self.lap_left <= 0:
            self.state = "return"
            self.state_t = 0
            self.say("还给你", 2.4)

    def _tick_return(self, dt: float) -> None:
        self.expression = "happy"
        self.phase += dt * 12
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
        self.bubble = self.label
        self.bubble_t = 6
        point = world.hover_point or world.cursor
        if abs(point[0] - self.x) > 8:
            self.facing = 1 if point[0] > self.x else -1
        self.phase += dt * 7
        self.expression = "normal"
        self._look_at(point)

    def _tick_chase(self, dt: float, world: World) -> None:
        self.calm = 0
        pos = world.drag_pos
        self._look_at(pos)
        if abs(pos[0] - self.x) > 12:
            self.facing = 1 if pos[0] > self.x else -1
        if self._dist(pos) < 135 * self.scale:
            self.state = "sniff"
            self.phase += dt * 8
            if not self._sniff_said:
                self.say("让我闻闻", 1.8)
                self._sniff_said = True
            return
        self.state = "run"
        self.phase += dt * 12
        self._step(*self._beside(pos), 270 * self.scale, dt)

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
                self.phase += dt * 6
                if abs(world.cursor[0] - self.x) > 10:
                    self.facing = 1 if world.cursor[0] > self.x else -1
            else:
                self.state = "approach"
                self.expression = "normal"
                self.phase += dt * 7.5
                self._step(*self._beside(world.cursor), 155 * self.scale, dt)
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
                self.phase += dt * 6
                if abs(world.cursor[0] - self.x) > 8:
                    self.facing = 1 if world.cursor[0] > self.x else -1
                if not self._greeted and dist < self.near:
                    self.say("汪")
                    self._greeted = True
            else:
                self._greeted = False
                self.state = "approach"
                self.expression = "normal"
                self.phase += dt * 7
                self._step(*self._beside(world.cursor), 125 * self.scale, dt)
            return True

        if dist > self.notice * 1.3:
            self._greeted = False
        return False

    def _idle(self, dt: float, world: World) -> None:
        self.calm += dt
        self._look_at(world.cursor)
        if self.state == "wander":
            self.expression = "normal"
            self.phase += dt * 6.5
            if self.target is None:
                self.target = self._random_point()
            if self._step(self.target[0], self.target[1], 76 * self.scale, dt) or self.state_t > 14:
                self._enter_sit()
            return
        if self.state == "play":
            self._tick_play(dt)
            return
        if self.state == "petted":
            self.expression = "happy"
            self.phase += dt * 6
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
        self.expression = "normal"
        self.phase += dt * 3.2
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
            self.phase += dt * 13
            if self.target and self._step(self.target[0], self.target[1], 300 * self.scale, dt):
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
        roll = random.random()
        if self.calm > 18 and roll < 0.4:
            self._enter_sleep()
        elif roll < 0.72:
            self._enter_play()
        else:
            self._enter_wander()
