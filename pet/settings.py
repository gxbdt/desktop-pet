"""记住小狗的模式、大小和亲密度；管理开机自启。"""

from __future__ import annotations

import json
import logging
import sys
import winreg
from pathlib import Path

log = logging.getLogger("pet")

ROOT = Path(__file__).resolve().parent.parent
PATH = ROOT / "settings.json"
DEFAULTS = {"name": "小金", "mode": "free", "size": 1.0, "affection": 0}

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "GoldenPuppyDesktopPet"


def load() -> dict:
    data = dict(DEFAULTS)
    try:
        data.update(json.loads(PATH.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except Exception:
        log.exception("读取设置失败，使用默认值")
    name = " ".join(str(data.get("name") or "").split())[:8]
    data["name"] = name or DEFAULTS["name"]
    if data.get("mode") not in ("free", "follow", "stay"):
        data["mode"] = "free"
    try:
        data["size"] = min(1.6, max(0.6, float(data.get("size", 1.0))))
        data["affection"] = max(0, int(data.get("affection", 0)))
    except (TypeError, ValueError):
        data["size"], data["affection"] = 1.0, 0
    return data


def save(data: dict) -> None:
    try:
        tmp = PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(PATH)
    except Exception:
        log.exception("保存设置失败")


def level(affection: int) -> int:
    return min(10, 1 + affection // 30)


def _command() -> str:
    exe = Path(sys.executable)
    pythonw = exe.with_name("pythonw.exe")
    if pythonw.exists():
        exe = pythonw
    return f'"{exe}" "{ROOT / "main.py"}"'


def autostart_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            winreg.QueryValueEx(key, RUN_NAME)
            return True
    except OSError:
        return False


def set_autostart(enabled: bool) -> None:
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, RUN_NAME, 0, winreg.REG_SZ, _command())
        else:
            try:
                winreg.DeleteValue(key, RUN_NAME)
            except FileNotFoundError:
                pass
