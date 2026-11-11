"""小狗用的小对话框，用系统原生控件，不额外依赖界面库。"""

from __future__ import annotations

import win32con
import win32gui

MAX_NAME = 8
ID_EDIT = 1001
DS_SETFOREGROUND = 0x0200
DS_CENTER = 0x0800
EM_SETLIMITTEXT = 0x00C5
BUTTON, EDIT, STATIC = 0x80, 0x81, 0x82


def ask_name(owner: int, current: str) -> str | None:
    """弹出模态对话框；返回新名字，取消或没填返回 None。"""
    style = (
        win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_SYSMENU
        | win32con.DS_MODALFRAME | DS_SETFOREGROUND | DS_CENTER | win32con.DS_SETFONT
    )
    child = win32con.WS_CHILD | win32con.WS_VISIBLE
    template = [
        ["给小狗起名字", (0, 0, 196, 76), style, win32con.WS_EX_TOPMOST, (9, "Microsoft YaHei UI")],
        [STATIC, f"它叫什么名字呢？（最多 {MAX_NAME} 个字）", -1, (10, 9, 176, 12), child],
        [EDIT, "", ID_EDIT, (10, 24, 176, 14), child | win32con.WS_TABSTOP | win32con.WS_BORDER | win32con.ES_AUTOHSCROLL],
        [BUTTON, "好", win32con.IDOK, (82, 50, 50, 16), child | win32con.WS_TABSTOP | win32con.BS_DEFPUSHBUTTON],
        [BUTTON, "取消", win32con.IDCANCEL, (136, 50, 50, 16), child | win32con.WS_TABSTOP | win32con.BS_PUSHBUTTON],
    ]
    result: dict[str, str | None] = {"name": None}

    def proc(hwnd, msg, wparam, lparam):
        if msg == win32con.WM_INITDIALOG:
            edit = win32gui.GetDlgItem(hwnd, ID_EDIT)
            win32gui.SendMessage(edit, EM_SETLIMITTEXT, MAX_NAME, 0)
            win32gui.SetWindowText(edit, current)
            win32gui.SendMessage(edit, win32con.EM_SETSEL, 0, -1)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.SetFocus(edit)
            return False  # 已手动设置焦点
        if msg == win32con.WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == win32con.IDOK:
                text = win32gui.GetWindowText(win32gui.GetDlgItem(hwnd, ID_EDIT))
                result["name"] = " ".join(text.split())[:MAX_NAME] or None
                win32gui.EndDialog(hwnd, win32con.IDOK)
                return True
            if cmd == win32con.IDCANCEL:
                win32gui.EndDialog(hwnd, win32con.IDCANCEL)
                return True
        return False

    win32gui.DialogBoxIndirect(win32gui.GetModuleHandle(None), template, owner, proc)
    return result["name"]


MAX_QUERY = 80


def ask_find(owner: int) -> str | None:
    """问要在桌面上找的名字；取消或空白返回 None。"""
    style = (
        win32con.WS_POPUP | win32con.WS_CAPTION | win32con.WS_SYSMENU
        | win32con.DS_MODALFRAME | DS_SETFOREGROUND | DS_CENTER | win32con.DS_SETFONT
    )
    child = win32con.WS_CHILD | win32con.WS_VISIBLE
    template = [
        ["在桌面上查找", (0, 0, 248, 78), style, win32con.WS_EX_TOPMOST, (9, "Microsoft YaHei UI")],
        [STATIC, "要找哪个文件或文件夹？（只看桌面）", -1, (12, 10, 224, 12), child],
        [EDIT, "", ID_EDIT, (12, 26, 224, 14), child | win32con.WS_TABSTOP | win32con.WS_BORDER | win32con.ES_AUTOHSCROLL],
        [BUTTON, "去找", win32con.IDOK, (132, 52, 50, 16), child | win32con.WS_TABSTOP | win32con.BS_DEFPUSHBUTTON],
        [BUTTON, "取消", win32con.IDCANCEL, (186, 52, 50, 16), child | win32con.WS_TABSTOP | win32con.BS_PUSHBUTTON],
    ]
    result: dict[str, str | None] = {"query": None}

    def proc(hwnd, msg, wparam, lparam):
        if msg == win32con.WM_INITDIALOG:
            edit = win32gui.GetDlgItem(hwnd, ID_EDIT)
            win32gui.SendMessage(edit, EM_SETLIMITTEXT, MAX_QUERY, 0)
            win32gui.SetForegroundWindow(hwnd)
            win32gui.SetFocus(edit)
            return False
        if msg == win32con.WM_COMMAND:
            cmd = wparam & 0xFFFF
            if cmd == win32con.IDOK:
                text = win32gui.GetWindowText(win32gui.GetDlgItem(hwnd, ID_EDIT)).strip()
                result["query"] = text[:MAX_QUERY] or None
                win32gui.EndDialog(hwnd, win32con.IDOK)
                return True
            if cmd == win32con.IDCANCEL:
                win32gui.EndDialog(hwnd, win32con.IDCANCEL)
                return True
        return False

    win32gui.DialogBoxIndirect(win32gui.GetModuleHandle(None), template, owner, proc)
    return result["query"]
