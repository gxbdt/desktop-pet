"""桌面上的透明窗口、鼠标和文件拖放。"""

from __future__ import annotations

import ctypes
import logging
import math
import time

import pythoncom
import win32api
import win32con
import win32gui

from pet import settings
from pet.desktop import IconWatch, find_recycle_bin, locate_on_desktop
from pet.dog import Dog, World
from pet.drop import FileDropTarget
from pet.namedlg import ask_find, ask_name
from pet.shellsel import SelectionProbe, describe
from pet.sprite import render
from pet.winlayer import set_hit_region, update_layered

log = logging.getLogger("pet")

user32 = ctypes.windll.user32
user32.FindWindowW.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
user32.FindWindowW.restype = ctypes.c_void_p
user32.GetDpiForSystem.restype = ctypes.c_uint

SHELL_CLASSES = {"CabinetWClass", "ExploreWClass", "Progman", "WorkerW"}
SIZE_CURSORS = {
    win32con.IDC_SIZENWSE,
    win32con.IDC_SIZENESW,
    win32con.IDC_SIZEWE,
    win32con.IDC_SIZENS,
    win32con.IDC_SIZEALL,
    win32con.IDC_IBEAM,
    win32con.IDC_CROSS,
}

WM_NULL = 0
CMD_FREE, CMD_FOLLOW, CMD_STAY, CMD_SLEEP, CMD_PLAY, CMD_EXIT = 1, 2, 3, 4, 5, 6
CMD_PAT, CMD_TREAT, CMD_AUTOSTART, CMD_LEVEL, CMD_NAME = 7, 8, 9, 10, 11
CMD_MARK = 12
CMD_FIND = 13
CMD_POOP = 14
CMD_SIZE = {20: (0.8, "小只"), 21: (1.0, "正常"), 22: (1.25, "大只")}

_last_cursor = (0, 0)


def cursor_pos() -> tuple[int, int]:
    """锁屏、UAC 弹窗时 GetCursorPos 会拒绝访问，这时沿用上一次的位置。"""
    global _last_cursor
    try:
        _last_cursor = win32api.GetCursorPos()
    except Exception:
        pass
    return _last_cursor


def pixel_scale() -> float:
    try:
        return max(1.0, user32.GetDpiForSystem() / 96)
    except Exception:
        return 1.0


def spawn_point(scale: float) -> tuple[float, float]:
    width = win32api.GetSystemMetrics(0)
    height = win32api.GetSystemMetrics(1)
    monitor = win32api.MonitorFromPoint((width // 2, height // 2), win32con.MONITOR_DEFAULTTONEAREST)
    left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Work"]
    return (left + right) / 2, min(bottom - 40 * scale, (top + bottom) / 2 + 30 * scale)


class _CursorInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", ctypes.c_uint),
        ("flags", ctypes.c_uint),
        ("hCursor", ctypes.c_void_p),
        ("x", ctypes.c_long),
        ("y", ctypes.c_long),
    ]


user32.GetCursorInfo.argtypes = [ctypes.POINTER(_CursorInfo)]
user32.GetCursorInfo.restype = ctypes.c_int


class App:
    def __init__(self):
        self.prefs = settings.load()
        self.dpi_scale = pixel_scale()
        self.scale = self.dpi_scale * self.prefs["size"]
        x, y = spawn_point(self.scale)
        self.dog = Dog(x, y, self.scale, affection=self.prefs["affection"], name=self.prefs["name"])
        self.dog.mode = self.prefs["mode"]
        self.world = World(self.scale)
        self.icons = IconWatch()
        self.probe = SelectionProbe()
        self._saved_affection = self.dog.affection
        self._frame_tick = 0
        self._error_at: dict[str, float] = {}
        self.hwnd = 0
        self.pressing = False
        self.grabbed = False
        self.press_at = (0, 0)
        self.grab_offset = (0.0, 0.0)
        self.file_drag = False
        self.drag_origin: tuple[int, int] | None = None
        self.pending_drop: dict | None = None
        self.hover_files: list[str] = []
        self.hover_point: tuple[int, int] | None = None
        self._button_down_at: tuple[int, int] | None = None
        self._from_shell = False
        self._ole_drop = False
        self._last = time.perf_counter()
        self._region_tick = 0
        self._topmost_tick = 0
        self._size_cursors = {int(win32gui.LoadCursor(0, cursor)) for cursor in SIZE_CURSORS}
        self._drop_wrap = None
        self._closed = False

    def on_file_hover(self, files, point) -> None:
        self.hover_files = list(files)
        self.hover_point = point

    def on_file_hover_move(self, point) -> None:
        self.hover_point = point

    def on_file_hover_leave(self) -> None:
        self.hover_files = []
        self.hover_point = None

    def on_file_drop(self, files, point) -> None:
        self._ole_drop = True
        self.hover_files = []
        self.hover_point = None
        self.pending_drop = {
            "files": list(files),
            "point": point,
            "origin": self.drag_origin or point,
        }
        log.info("接住文件 %s", self.pending_drop["files"])

    def _sync_world(self) -> None:
        cursor = cursor_pos()
        self.world.cursor = cursor
        self.world.scale = self.scale
        self.world.file_drag = self.file_drag
        self.world.drag_pos = cursor
        self.world.drag_origin = self.drag_origin
        self.world.hover_files = self.hover_files
        self.world.hover_point = self.hover_point
        self.world.pending_drop = self.pending_drop
        self.world.grabbed = self.grabbed
        self.world.icons = self.icons.snapshot()
        if self.file_drag and self.probe.result is not None:
            self.world.drag_label, self.world.drag_kind = describe(self.probe.result)
        if self.grabbed:
            self.dog.x = cursor[0] + self.grab_offset[0]
            self.dog.y = cursor[1] + self.grab_offset[1]

    def _poll_drag(self) -> None:
        if self.grabbed or self.pressing:
            self.file_drag = False
            return
        image = user32.FindWindowW("SysDragImage", None)
        cursor = cursor_pos()
        if image:
            if not self.file_drag:
                self._start_drag(cursor)
            self.file_drag = True
            return

        down = bool(win32api.GetAsyncKeyState(win32con.VK_LBUTTON) & 0x8000)
        if down:
            if self._button_down_at is None:
                self._button_down_at = cursor
                foreground = win32gui.GetForegroundWindow()
                try:
                    self._from_shell = win32gui.GetClassName(foreground) in SHELL_CLASSES
                except Exception:
                    self._from_shell = False
            elif self._from_shell and not self._plain_cursor():
                if math.hypot(cursor[0] - self._button_down_at[0], cursor[1] - self._button_down_at[1]) > 30:
                    if not self.file_drag:
                        self._start_drag(self._button_down_at)
                    self.file_drag = True
            return

        was = self.file_drag
        self.file_drag = False
        self._button_down_at = None
        self._from_shell = False
        if was and not self._ole_drop and self.pending_drop is None:
            # 文件夹被放到了新位置：让小狗跑过去闻一闻
            self.world.drag_end = {"point": cursor, "label": self.world.drag_label, "kind": self.world.drag_kind}
            log.info("文件拖动结束于 %s：%s", cursor, self.world.drag_label)
        self._ole_drop = False

    def _start_drag(self, origin: tuple[int, int]) -> None:
        self.drag_origin = origin
        self._ole_drop = False
        self.world.drag_label = None
        self.world.drag_kind = "file"
        self.world.drag_end = None
        try:
            source = win32gui.GetForegroundWindow()
        except Exception:
            source = 0
        self.probe.start(source)
        log.info("发现文件拖动")

    def _plain_cursor(self) -> bool:
        info = _CursorInfo()
        info.cbSize = ctypes.sizeof(info)
        if not user32.GetCursorInfo(ctypes.byref(info)):
            return True
        return int(info.hCursor or 0) in self._size_cursors or int(info.hCursor or 0) == int(win32gui.LoadCursor(0, win32con.IDC_ARROW))

    def tick(self) -> None:
        now = time.perf_counter()
        dt = now - self._last
        self._last = now
        self._poll_drag()
        self._sync_world()
        self.dog.update(dt, self.world)
        self.pending_drop = self.world.pending_drop
        self._frame_tick += 1
        if self.dog.affection != self._saved_affection and self._frame_tick % 150 == 0:
            self.save_prefs()
        # 睡觉时动作很慢，降到 10 帧省电
        if self.dog.state == "sleep" and not self.dog.bubble and self._frame_tick % 3:
            return
        image = render(self.dog.make_frame(), self.scale)
        x, y = self.dog.window_origin(image.size)
        update_layered(self.hwnd, image, x, y)
        self._region_tick += 1
        if self._region_tick % 3 == 0:
            set_hit_region(self.hwnd, image)
        self._topmost_tick += 1
        if self._topmost_tick % 90 == 0:
            win32gui.SetWindowPos(
                self.hwnd,
                win32con.HWND_TOPMOST,
                0,
                0,
                0,
                0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOACTIVATE,
            )

    def save_prefs(self) -> None:
        self.prefs["name"] = self.dog.name
        self.prefs["mode"] = self.dog.mode
        self.prefs["affection"] = self.dog.affection
        self._saved_affection = self.dog.affection
        settings.save(self.prefs)

    def set_size(self, size: float) -> None:
        self.prefs["size"] = size
        self.scale = self.dpi_scale * size
        self.world.scale = self.scale
        self.dog.scale = self.scale
        self.dog._clamp()
        self.save_prefs()

    def _screen_from_message(self) -> tuple[int, int]:
        return cursor_pos()

    def on_left_down(self) -> None:
        x, y = self._screen_from_message()
        self.pressing = True
        self.press_at = (x, y)
        self.grab_offset = (self.dog.x - x, self.dog.y - y)
        self.grabbed = False
        win32gui.SetCapture(self.hwnd)

    def on_mouse_move(self) -> None:
        if not self.pressing:
            return
        x, y = self._screen_from_message()
        if math.hypot(x - self.press_at[0], y - self.press_at[1]) > 6:
            self.grabbed = True
        if self.grabbed:
            self.dog.x = x + self.grab_offset[0]
            self.dog.y = y + self.grab_offset[1]
            self.dog._clamp()

    def on_left_up(self) -> None:
        if self.pressing:
            try:
                win32gui.ReleaseCapture()
            except Exception:
                pass
        if self.pressing and not self.grabbed:
            self.dog.pet()
        elif self.grabbed:
            self.dog.release()
        self.pressing = False
        self.grabbed = False

    def show_menu(self) -> None:
        x, y = cursor_pos()
        menu = win32gui.CreatePopupMenu()
        sizes = win32gui.CreatePopupMenu()

        def add(cmd, text, checked=False, target=menu, disabled=False):
            flags = win32con.MF_STRING | (win32con.MF_CHECKED if checked else 0)
            if disabled:
                flags |= win32con.MF_GRAYED
            win32gui.AppendMenu(target, flags, cmd, text)

        def separator():
            win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")

        add(CMD_PAT, "摸摸头")
        add(CMD_TREAT, "喂零食")
        separator()
        add(CMD_FREE, "自己玩", self.dog.mode == "free")
        add(CMD_FOLLOW, "跟着我", self.dog.mode == "follow")
        add(CMD_STAY, "安静待着", self.dog.mode == "stay")
        separator()
        add(CMD_SLEEP, "去睡觉")
        add(CMD_PLAY, "起来玩")
        add(CMD_MARK, "去标记一下")
        add(CMD_POOP, "去拉臭臭")
        add(CMD_FIND, "查找文件…")
        separator()
        for cmd, (size, text) in CMD_SIZE.items():
            add(cmd, text, abs(self.prefs["size"] - size) < 0.01, target=sizes)
        win32gui.AppendMenu(menu, win32con.MF_POPUP, sizes, "大小")
        add(CMD_NAME, "给它起名字…")
        add(CMD_AUTOSTART, "开机自动出现", settings.autostart_enabled())
        lv = settings.level(self.dog.affection)
        add(CMD_LEVEL, f"{self.dog.name}  亲密度 Lv.{lv}  " + "♥" * min(lv, 5) + "♡" * max(0, 5 - lv), disabled=True)
        separator()
        add(CMD_EXIT, "退出")
        # 无焦点窗口弹不出菜单，弹出前临时允许激活。
        ex_style = win32gui.GetWindowLong(self.hwnd, win32con.GWL_EXSTYLE)
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style & ~win32con.WS_EX_NOACTIVATE)
        win32gui.SetForegroundWindow(self.hwnd)
        cmd = win32gui.TrackPopupMenu(
            menu,
            win32con.TPM_LEFTALIGN | win32con.TPM_RIGHTBUTTON | win32con.TPM_RETURNCMD | win32con.TPM_NONOTIFY,
            x,
            y,
            0,
            self.hwnd,
            None,
        )
        win32gui.SetWindowLong(self.hwnd, win32con.GWL_EXSTYLE, ex_style)
        win32gui.PostMessage(self.hwnd, WM_NULL, 0, 0)
        win32gui.DestroyMenu(menu)
        if cmd:
            self.on_command(cmd)

    def on_command(self, cmd: int) -> None:
        if cmd == CMD_PAT:
            self.dog.pat_head()
        elif cmd == CMD_TREAT:
            self.dog.give_treat()
        elif cmd in (CMD_FREE, CMD_FOLLOW, CMD_STAY):
            self.dog.set_mode({CMD_FREE: "free", CMD_FOLLOW: "follow", CMD_STAY: "stay"}[cmd])
            self.save_prefs()
        elif cmd in CMD_SIZE:
            self.set_size(CMD_SIZE[cmd][0])
        elif cmd == CMD_NAME:
            self.dog.say("要给我起名字吗？", 30)
            name = ask_name(self.hwnd, self.dog.name)
            if name:
                self.dog.rename(name)
                self.save_prefs()
                win32gui.SetWindowText(self.hwnd, f"桌面金毛 {name}")
            else:
                self.dog.say("那我还叫" + self.dog.name)
        elif cmd == CMD_AUTOSTART:
            try:
                enabled = not settings.autostart_enabled()
                settings.set_autostart(enabled)
                self.dog.say("开机就来陪你" if enabled else "好的，不自动出来了")
            except OSError:
                log.exception("设置开机自启失败")
                self.dog.say("没设置成功…")
        elif cmd == CMD_SLEEP:
            self.dog.command_sleep()
        elif cmd == CMD_PLAY:
            self.dog.command_play()
        elif cmd == CMD_MARK:
            if not self.icons.snapshot():
                self.icons.refresh_now()
            self.world.icons = self.icons.snapshot()
            self.dog._icons = self.world.icons
            self.dog.command_mark()
        elif cmd == CMD_POOP:
            if self.dog.busy_with_file:
                self.dog.say("等我放好")
                return
            self.icons.refresh_now()
            self.world.icons = self.icons.snapshot()
            self.dog._icons = self.world.icons
            hit = find_recycle_bin(self.icons.snapshot())
            if hit is None:
                self.dog.say("没看到回收站")
                return
            name, x, y = hit
            self.dog.command_poop(name, x, y)
        elif cmd == CMD_FIND:
            if self.dog.busy_with_file:
                self.dog.say("等我放好")
                return
            query = ask_find(self.hwnd)
            if not query:
                self.dog.say("那我就不找啦")
                return
            self.icons.refresh_now()
            hit = locate_on_desktop(query, self.icons.snapshot(), near=(self.dog.x, self.dog.y))
            if hit is None:
                self.dog.say("桌面上没有这个")
                return
            name, x, y = hit
            self.dog.command_find(name, x, y)
        elif cmd == CMD_EXIT:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.save_prefs()
        try:
            pythoncom.RevokeDragDrop(self.hwnd)
        except Exception:
            log.exception("取消拖放注册失败")
        win32gui.PostQuitMessage(0)

    def wnd_proc(self, hwnd, msg, wparam, lparam):
        try:
            if msg == win32con.WM_TIMER:
                self.tick()
                return 0
            if msg == win32con.WM_LBUTTONDOWN:
                self.on_left_down()
                return 0
            if msg == win32con.WM_MOUSEMOVE:
                self.on_mouse_move()
                return 0
            if msg == win32con.WM_LBUTTONUP:
                self.on_left_up()
                return 0
            if msg == win32con.WM_RBUTTONUP:
                self.show_menu()
                return 0
            if msg == win32con.WM_COMMAND:
                self.on_command(win32api.LOWORD(wparam))
                return 0
            if msg == win32con.WM_MOUSEACTIVATE:
                return win32con.MA_NOACTIVATE
            if msg == win32con.WM_CLOSE:
                self.close()
                return 0
            if msg == win32con.WM_DESTROY:
                self.close()
                return 0
        except Exception as exc:
            # 同一种错误每分钟只记一次，免得日志被每帧的计时器刷爆
            key = f"{msg}:{type(exc).__name__}:{exc}"
            now = time.monotonic()
            if now - self._error_at.get(key, -999.0) > 60:
                self._error_at[key] = now
                log.exception("窗口消息处理失败")
        return win32gui.DefWindowProc(hwnd, msg, wparam, lparam)


def run() -> None:
    pythoncom.OleInitialize()
    app = App()
    instance = win32api.GetModuleHandle(None)
    klass = win32gui.WNDCLASS()
    klass.hInstance = instance
    klass.lpszClassName = "GoldenPuppyDesktopPet"
    klass.lpfnWndProc = app.wnd_proc
    klass.hCursor = win32gui.LoadCursor(0, win32con.IDC_HAND)
    try:
        win32gui.RegisterClass(klass)
    except win32gui.error:
        pass
    ex = win32con.WS_EX_LAYERED | win32con.WS_EX_TOPMOST | win32con.WS_EX_TOOLWINDOW | win32con.WS_EX_NOACTIVATE
    app.hwnd = win32gui.CreateWindowEx(
        ex,
        klass.lpszClassName,
        "桌面金毛",
        win32con.WS_POPUP,
        0,
        0,
        10,
        10,
        0,
        0,
        instance,
        None,
    )
    app._drop_wrap = pythoncom.WrapObject(FileDropTarget(app), pythoncom.IID_IDropTarget)
    pythoncom.RegisterDragDrop(app.hwnd, app._drop_wrap)
    app.tick()
    set_hit_region(app.hwnd, render(app.dog.make_frame(), app.scale))
    win32gui.ShowWindow(app.hwnd, win32con.SW_SHOWNOACTIVATE)
    user32.SetTimer.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
    user32.SetTimer.restype = ctypes.c_uint
    user32.KillTimer.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    user32.KillTimer.restype = ctypes.c_int
    if not user32.SetTimer(app.hwnd, 1, 33, None):
        raise ctypes.WinError()
    log.info("小狗已出现 scale=%s", app.scale)
    pythoncom.PumpMessages()
    user32.KillTimer(app.hwnd, 1)
