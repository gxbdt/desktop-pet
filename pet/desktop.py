"""读取桌面上图标的名字和位置，好让小狗走过去做标记。只读，不改图标。"""

from __future__ import annotations

import ctypes
import logging
import math
import os
import threading
from ctypes import wintypes
from pathlib import Path

log = logging.getLogger("pet")

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowExW.restype = wintypes.HWND
user32.EnumWindows.argtypes = [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM), wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
user32.SendMessageTimeoutW.argtypes = [
    wintypes.HWND,
    wintypes.UINT,
    wintypes.WPARAM,
    wintypes.LPARAM,
    wintypes.UINT,
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_size_t),
]
user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t

kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualFreeEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD]
kernel32.VirtualFreeEx.restype = wintypes.BOOL
kernel32.ReadProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
]
kernel32.ReadProcessMemory.restype = wintypes.BOOL
kernel32.WriteProcessMemory.argtypes = [
    wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)
]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

LVM_GETITEMCOUNT = 0x1004
LVM_GETITEMRECT = 0x100E
LVM_GETITEMTEXTW = 0x1073
LVIR_ICON = 1
SMTO_ABORTIFHUNG = 0x0002

PROCESS_VM = 0x0008 | 0x0010 | 0x0020 | 0x0400
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
MEM_RELEASE = 0x8000
PAGE_READWRITE = 0x04


class _LVITEMW(ctypes.Structure):
    _fields_ = [
        ("mask", wintypes.UINT),
        ("iItem", ctypes.c_int),
        ("iSubItem", ctypes.c_int),
        ("state", wintypes.UINT),
        ("stateMask", wintypes.UINT),
        ("pszText", ctypes.c_void_p),
        ("cchTextMax", ctypes.c_int),
        ("iImage", ctypes.c_int),
        ("lParam", ctypes.c_void_p),
        ("iIndent", ctypes.c_int),
        ("iGroupId", ctypes.c_int),
        ("cColumns", wintypes.UINT),
        ("puColumns", ctypes.c_void_p),
        ("piColFmt", ctypes.c_void_p),
        ("iGroup", ctypes.c_int),
    ]


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def _desktop_listview() -> int:
    prog = user32.FindWindowW("Progman", None)
    shell = user32.FindWindowExW(prog, None, "SHELLDLL_DefView", None)
    if shell:
        listed = user32.FindWindowExW(shell, None, "SysListView32", "FolderView")
        if listed:
            return listed
    found: list[int] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _lparam):
        view = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
        if not view:
            return True
        listed = user32.FindWindowExW(view, None, "SysListView32", "FolderView")
        if not listed:
            listed = user32.FindWindowExW(view, None, "SysListView32", None)
        if listed:
            found.append(listed)
            return False
        return True

    user32.EnumWindows(visit, 0)
    return found[0] if found else 0


def _send(hwnd, msg, wparam, lparam, timeout=120) -> bool:
    result = ctypes.c_size_t()
    return bool(user32.SendMessageTimeoutW(hwnd, msg, wparam, lparam, SMTO_ABORTIFHUNG, timeout, ctypes.byref(result)))


def list_icons() -> list[tuple[str, float, float]]:
    """返回 (名字, 图标中心屏幕 x, 图标中心屏幕 y)。失败时给空列表。"""
    hwnd = _desktop_listview()
    if not hwnd:
        return []
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    if not pid.value:
        return []
    process = kernel32.OpenProcess(PROCESS_VM, False, pid.value)
    if not process:
        return []
    remote = kernel32.VirtualAllocEx(process, None, 8192, MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not remote:
        kernel32.CloseHandle(process)
        return []
    text_addr = remote
    item_addr = remote + 2048
    rect_addr = remote + 4096
    icons: list[tuple[str, float, float]] = []
    try:
        count_slot = ctypes.c_size_t()
        if not user32.SendMessageTimeoutW(
            hwnd, LVM_GETITEMCOUNT, 0, 0, SMTO_ABORTIFHUNG, 200, ctypes.byref(count_slot)
        ):
            return []
        count = int(count_slot.value)
        written = ctypes.c_size_t()
        read = ctypes.c_size_t()
        for index in range(max(0, min(count, 240))):
            item = _LVITEMW()
            item.mask = 0x0001
            item.pszText = text_addr
            item.cchTextMax = 260
            kernel32.WriteProcessMemory(process, item_addr, ctypes.byref(item), ctypes.sizeof(item), ctypes.byref(written))
            if not _send(hwnd, LVM_GETITEMTEXTW, index, item_addr):
                continue
            buf = ctypes.create_unicode_buffer(260)
            kernel32.ReadProcessMemory(process, text_addr, buf, 520, ctypes.byref(read))
            name = buf.value.strip()
            if not name:
                continue
            rect = _RECT(LVIR_ICON, 0, 0, 0)
            kernel32.WriteProcessMemory(process, rect_addr, ctypes.byref(rect), ctypes.sizeof(rect), ctypes.byref(written))
            if not _send(hwnd, LVM_GETITEMRECT, index, rect_addr):
                continue
            kernel32.ReadProcessMemory(process, rect_addr, ctypes.byref(rect), ctypes.sizeof(rect), ctypes.byref(read))
            if rect.right <= rect.left or rect.bottom <= rect.top:
                continue
            point = wintypes.POINT((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
            if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
                continue
            icons.append((name, float(point.x), float(point.y)))
    except Exception:
        log.info("读取桌面图标失败", exc_info=True)
        return []
    finally:
        kernel32.VirtualFreeEx(process, remote, 0, MEM_RELEASE)
        kernel32.CloseHandle(process)
    return icons


class IconWatch:
    """后台刷新。赋值整个列表，动画线程读到的永远是完整的一版。"""

    def __init__(self):
        self._icons: list[tuple[str, float, float]] = []
        self._stop = False
        threading.Thread(target=self._loop, name="desktop-icons", daemon=True).start()

    def snapshot(self) -> list[tuple[str, float, float]]:
        return self._icons

    def refresh_now(self) -> list[tuple[str, float, float]]:
        icons = list_icons()
        if icons:
            self._icons = icons
        return self._icons

    def _loop(self) -> None:
        while not self._stop:
            try:
                icons = list_icons()
                if icons:
                    self._icons = icons
            except Exception:
                log.info("刷新桌面图标失败", exc_info=True)
            for _ in range(12):
                if self._stop:
                    return
                threading.Event().wait(0.5)


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", wintypes.BYTE * 8),
    ]


# FOLDERID_Desktop。用户把桌面改到别的盘时，这里仍然是资源管理器用的那个文件夹。
_DESKTOP_GUID = _GUID(
    0xB4BFCC3A,
    0xDB2C,
    0x424C,
    (wintypes.BYTE * 8)(0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41),
)
_SKIP_NAMES = {"desktop.ini", "thumbs.db"}


def desktop_folder() -> Path:
    """当前用户的桌面文件夹，不含公共桌面，也不进子文件夹。"""
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    ole32 = ctypes.WinDLL("ole32", use_last_error=True)
    shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID),
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    buf = ctypes.c_wchar_p()
    try:
        hr = shell32.SHGetKnownFolderPath(ctypes.byref(_DESKTOP_GUID), 0, None, ctypes.byref(buf))
        if hr == 0 and buf.value:
            return Path(buf.value)
    except Exception:
        log.info("读取桌面文件夹路径失败", exc_info=True)
    finally:
        addr = ctypes.cast(buf, ctypes.c_void_p).value
        if addr:
            ole32.CoTaskMemFree(addr)
    return Path.home() / "Desktop"


def _same_path(a: Path, b: Path) -> bool:
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def _is_dir(path: Path) -> bool:
    try:
        return path.is_dir()
    except OSError:
        return False


def _match_rank(query: str, path: Path) -> int | None:
    """0 全名，1 去掉扩展名，2 开头吻合，3 名字里包含。文件夹不拆扩展名。"""
    name = path.name.casefold()
    options = [name]
    if not _is_dir(path) and path.suffix:
        options.append(path.stem.casefold())
    if query == name:
        return 0
    if query in options:
        return 1
    if any(item.startswith(query) for item in options):
        return 2
    if any(query in item for item in options):
        return 3
    return None


def _icon_for(
    path: Path,
    icons: list[tuple[str, float, float]],
    near: tuple[float, float] | None,
) -> tuple[str, float, float] | None:
    """图标上显示的字可能带着扩展名，也可能被系统藏掉。"""
    keys = [path.name.casefold()]
    if not _is_dir(path) and path.suffix:
        keys.append(path.stem.casefold())
    grouped: dict[str, list[tuple[str, float, float]]] = {key: [] for key in keys}
    for name, x, y in icons:
        folded = name.casefold()
        if folded in grouped:
            grouped[folded].append((name, float(x), float(y)))
    for key in keys:
        hits = grouped[key]
        if not hits:
            continue
        if near is None or len(hits) == 1:
            return hits[0]
        return min(hits, key=lambda item: math.hypot(item[1] - near[0], item[2] - near[1]))
    return None


def locate_on_desktop(
    query: str,
    icons: list[tuple[str, float, float]],
    near: tuple[float, float] | None = None,
    root: Path | None = None,
) -> tuple[str, float, float] | None:
    """在桌面文件夹的直接子项里找。返回图标上的名字和屏幕坐标。"""
    text = query.strip().strip('"')
    if not text:
        return None
    folder = root if root is not None else desktop_folder()
    if not folder.is_dir():
        log.info("桌面文件夹不存在：%s", folder)
        return None
    forced: Path | None = None
    if "\\" in text or "/" in text or (len(text) > 2 and text[1] == ":"):
        try:
            target = Path(text).expanduser().resolve()
        except OSError:
            return None
        if not _same_path(target.parent, folder) or not target.exists():
            return None
        forced = target
        text = target.name
    needle = text.casefold()
    try:
        entries = [item for item in folder.iterdir() if item.name.casefold() not in _SKIP_NAMES]
    except OSError:
        log.info("读取桌面文件夹失败：%s", folder, exc_info=True)
        return None
    if forced is not None:
        entries = [item for item in entries if _same_path(item, forced)]
    ranked: list[tuple[int, int, float, str, float, float]] = []
    for path in entries:
        rank = _match_rank(needle, path)
        if rank is None:
            continue
        icon = _icon_for(path, icons, near)
        if icon is None:
            continue
        name, x, y = icon
        dist = math.hypot(x - near[0], y - near[1]) if near is not None else 0.0
        ranked.append((rank, len(path.name), dist, name, x, y))
    if not ranked:
        log.info("桌面上没有找到 %r（%s）", query, folder)
        return None
    ranked.sort()
    _rank, _length, _dist, name, x, y = ranked[0]
    log.info("在桌面找到 %s @ (%.0f, %.0f)", name, x, y)
    return name, x, y


_RECYCLE_ALIASES = {"回收站", "回收筒", "資源回收筒", "资源回收筒", "recycle bin"}


def recycle_bin_name() -> str:
    """系统当前语言下回收站在桌面上显示的名字。"""
    try:
        from win32com.shell import shell, shellcon

        pidl = shell.SHGetSpecialFolderLocation(0, shellcon.CSIDL_BITBUCKET)
        name = shell.SHGetNameFromIDList(pidl, shellcon.SHGDN_NORMAL)
        if name:
            return str(name)
    except Exception:
        log.info("读取回收站名字失败", exc_info=True)
    return "回收站"


def find_recycle_bin(icons: list[tuple[str, float, float]]) -> tuple[str, float, float] | None:
    """在桌面图标里找出回收站的位置。"""
    wanted = {recycle_bin_name().casefold(), *_RECYCLE_ALIASES}
    for name, x, y in icons:
        if name.casefold() in wanted:
            log.info("回收站在 %s @ (%.0f, %.0f)", name, x, y)
            return name, float(x), float(y)
    log.info("桌面上没有看到回收站")
    return None
