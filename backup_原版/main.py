"""启动桌面上的幼年金毛。"""

from __future__ import annotations

import ctypes
import logging
import sys
import traceback
from pathlib import Path

import win32api
import win32con
import win32event
import winerror


def _dpi() -> None:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _logger() -> logging.Logger:
    path = Path(__file__).resolve().parent / "pet.log"
    logging.basicConfig(
        filename=path,
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        encoding="utf-8",
    )
    return logging.getLogger("pet")


def main() -> None:
    _dpi()
    log = _logger()
    mutex = win32event.CreateMutex(None, False, "Local\\GoldenPuppyDesktopPet.v1")
    if win32api.GetLastError() == winerror.ERROR_ALREADY_EXISTS:
        win32api.MessageBox(0, "小狗已经在桌面上啦。", "桌面宠物", win32con.MB_ICONINFORMATION)
        return
    # 句柄必须留着，进程结束前互斥量才不会被释放。
    globals()["_PET_MUTEX"] = mutex
    try:
        from pet.app import run

        run()
    except Exception:
        log.exception("小狗启动失败")
        win32api.MessageBox(0, "小狗没能跑起来，详情写在 pet.log。\n\n" + traceback.format_exc()[-800:], "桌面宠物", win32con.MB_ICONERROR)
        sys.exit(1)


if __name__ == "__main__":
    main()
