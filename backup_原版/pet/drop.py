"""接收拖到小狗身上的文件。只读取文件名，不移动、不复制。"""

from __future__ import annotations

import logging

import pythoncom
import win32con
from win32com.shell import shell, shellcon

log = logging.getLogger("pet")

_FORMAT = (win32con.CF_HDROP, None, pythoncom.DVASPECT_CONTENT, -1, pythoncom.TYMED_HGLOBAL)


def _point(value) -> tuple[int, int]:
    try:
        return int(value[0]), int(value[1])
    except Exception:
        return int(value.x), int(value.y)


def _files_from(data_object) -> list[str]:
    medium = data_object.GetData(_FORMAT)
    handle = getattr(medium, "data_handle", None)
    if not handle:
        handle = getattr(medium, "data", None)
    count = shell.DragQueryFile(handle, -1)
    return [shell.DragQueryFile(handle, index) for index in range(count)]


class FileDropTarget:
    _public_methods_ = ["DragEnter", "DragOver", "DragLeave", "Drop"]
    _com_interfaces_ = [pythoncom.IID_IDropTarget]

    def __init__(self, owner):
        self.owner = owner
        self._accept = False

    def _contains_files(self, data_object) -> bool:
        try:
            data_object.QueryGetData(_FORMAT)
            return True
        except pythoncom.com_error:
            return False

    def DragEnter(self, data_object, key_state, point, effect):
        self._accept = self._contains_files(data_object)
        files: list[str] = []
        if self._accept:
            try:
                files = _files_from(data_object)
            except Exception:
                log.exception("读取拖放文件名失败")
                self._accept = False
        if self._accept:
            self.owner.on_file_hover(files, _point(point))
            # 用复制光标表示“可以松手”，真正落下时返回 NONE，文件留在原地。
            return shellcon.DROPEFFECT_COPY
        return shellcon.DROPEFFECT_NONE

    def DragOver(self, key_state, point, effect):
        if self._accept:
            self.owner.on_file_hover_move(_point(point))
            return shellcon.DROPEFFECT_COPY
        return shellcon.DROPEFFECT_NONE

    def DragLeave(self):
        self._accept = False
        self.owner.on_file_hover_leave()

    def Drop(self, data_object, key_state, point, effect):
        files: list[str] = []
        if self._accept:
            try:
                files = _files_from(data_object)
            except Exception:
                log.exception("放下文件时读取失败")
        self._accept = False
        if files:
            self.owner.on_file_drop(files, _point(point))
        # NONE：取消移动/复制。返回 MOVE 会让资源管理器把原文件删掉。
        return shellcon.DROPEFFECT_NONE
