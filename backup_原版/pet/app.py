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

from pet.dog import Dog, World
from pet.drop import FileDropTarget
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
        self.scale = pixel_scale()
        x, y = spawn_point(self.scale)
        self.dog = Dog(x, y, self.scale)
        self.world = World(self.scale)
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
        cursor = win32api.GetCursorPos()
        self.world.cursor = cursor
        self.world.scale = self.scale
        self.world.file_drag = self.file_drag
        self.world.drag_pos = cursor
        self.world.drag_origin = self.drag_origin
        self.world.hover_files = self.hover_files
        self.world.hover_point = self.hover_point
        self.world.pending_drop = self.pending_drop
        self.world.grabbed = self.grabbed
        if self.grabbed:
            self.dog.x = cursor[0] + self.grab_offset[0]
            self.dog.y = cursor[1] + self.grab_offset[1]

    def _poll_drag(self) -> None:
        if self.grabbed or self.pressing:
            self.file_drag = False
            return
        image = user32.FindWindowW("SysDragImage", None)
        cursor = win32api.GetCursorPos()
        if image:
            if not self.file_drag:
                self.drag_origin = cursor
                self._ole_drop = False
                log.info("发现文件拖动")
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
                        self.drag_origin = self._button_down_at
                        self._ole_drop = False
                    self.file_drag = True
            return

        was = self.file_drag
        origin = self.drag_origin
        self.file_drag = False
        self._button_down_at = None
        self._from_shell = False
        if was and not self._ole_drop and self.pending_drop is None:
            if self.dog.state in ("sniff", "run") and self.dog._dist(cursor) < 160 * self.scale:
                self.pending_drop = {"files": [], "point": cursor, "origin": origin or cursor, "label": "文件"}
        self._ole_drop = False

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

    def _screen_from_message(self) -> tuple[int, int]:
        return win32api.GetCursorPos()

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
        x, y = win32api.GetCursorPos()
        menu = win32gui.CreatePopupMenu()

        def add(cmd, text, checked=False):
            flags = win32con.MF_STRING | (win32con.MF_CHECKED if checked else 0)
            win32gui.AppendMenu(menu, flags, cmd, text)

        add(CMD_FREE, "自己玩", self.dog.mode == "free")
        add(CMD_FOLLOW, "跟着我", self.dog.mode == "follow")
        add(CMD_STAY, "安静待着", self.dog.mode == "stay")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
        add(CMD_SLEEP, "去睡觉")
        add(CMD_PLAY, "起来玩")
        win32gui.AppendMenu(menu, win32con.MF_SEPARATOR, 0, "")
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
        if cmd == CMD_FREE:
            self.dog.set_mode("free")
        elif cmd == CMD_FOLLOW:
            self.dog.set_mode("follow")
        elif cmd == CMD_STAY:
            self.dog.set_mode("stay")
        elif cmd == CMD_SLEEP:
            self.dog.command_sleep()
        elif cmd == CMD_PLAY:
            self.dog.command_play()
        elif cmd == CMD_EXIT:
            win32gui.PostMessage(self.hwnd, win32con.WM_CLOSE, 0, 0)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
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
        except Exception:
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
