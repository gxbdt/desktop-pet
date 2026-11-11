"""问资源管理器（或桌面）当前选中了什么，用来知道正被拖动的是哪个文件夹。只读名字。"""

from __future__ import annotations

import logging
import threading

import pythoncom
import win32com.client
import win32gui

log = logging.getLogger("pet")

DESKTOP_CLASSES = {"Progman", "WorkerW"}
SWC_DESKTOP = 8
SWFO_NEEDDISPATCH = 1
GA_ROOT = 2
ARCHIVES = (".zip", ".cab", ".7z", ".rar")


def _query(hwnd: int) -> list[tuple[str, bool]]:
    windows = win32com.client.Dispatch("Shell.Application").Windows()
    try:
        cls = win32gui.GetClassName(hwnd) if hwnd else ""
    except Exception:
        cls = ""
    view = None
    if not hwnd or cls in DESKTOP_CLASSES:
        view = windows.FindWindowSW(0, None, SWC_DESKTOP, 0, SWFO_NEEDDISPATCH)
    else:
        root = win32gui.GetAncestor(hwnd, GA_ROOT)
        for window in windows:
            try:
                if int(window.HWND) == root:
                    view = window
                    break
            except Exception:
                continue
    if view is None:
        return []
    items = view.Document.SelectedItems()
    found = []
    for index in range(min(items.Count, 30)):
        item = items.Item(index)
        name = str(item.Name)
        folder = bool(item.IsFolder) and not name.lower().endswith(ARCHIVES)
        found.append((name, folder))
    return found


def describe(items: list[tuple[str, bool]]) -> tuple[str | None, str]:
    """返回 (气泡里显示的名字, "folder" 或 "file")。"""
    if not items:
        return None, "file"
    name = items[0][0]
    if len(name) > 12:
        name = name[:11] + "…"
    if len(items) > 1:
        name = f"{name}等{len(items)}个"
    kind = "folder" if all(folder for _, folder in items) else "file"
    return name, kind


class SelectionProbe:
    """在后台线程里查询，跨进程 COM 调用不会卡住小狗的动画。"""

    def __init__(self):
        self.result: list[tuple[str, bool]] | None = None
        self._token = 0

    def start(self, hwnd: int) -> None:
        self._token += 1
        token = self._token
        self.result = None

        def work():
            pythoncom.CoInitialize()
            try:
                items = _query(hwnd)
            except Exception:
                log.info("读取选中项失败", exc_info=True)
                items = []
            finally:
                pythoncom.CoUninitialize()
            if token == self._token:
                self.result = items

        threading.Thread(target=work, name="shell-selection", daemon=True).start()
