"""把带透明通道的图像贴到一个分层窗口上，并按不透明区域接收点击。"""

from __future__ import annotations

import ctypes
import re
from ctypes import wintypes

from PIL import Image

from pet.sprite import to_bgra_premul

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

BI_RGB = 0
DIB_RGB_COLORS = 0
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
ULW_ALPHA = 2
RDH_RECTANGLES = 1


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", wintypes.BYTE),
        ("BlendFlags", wintypes.BYTE),
        ("SourceConstantAlpha", wintypes.BYTE),
        ("AlphaFormat", wintypes.BYTE),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class RGNDATAHEADER(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("iType", wintypes.DWORD),
        ("nCount", wintypes.DWORD),
        ("nRgnSize", wintypes.DWORD),
        ("rcBound", RECT),
    ]


user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]
user32.UpdateLayeredWindow.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
user32.SetWindowRgn.restype = ctypes.c_int

gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC,
    ctypes.POINTER(BITMAPINFO),
    wintypes.UINT,
    ctypes.POINTER(ctypes.c_void_p),
    wintypes.HANDLE,
    wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = wintypes.HBITMAP
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.ExtCreateRegion.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p]
gdi32.ExtCreateRegion.restype = wintypes.HRGN


def update_layered(hwnd, image: Image.Image, x: int, y: int) -> None:
    image = image.convert("RGBA")
    width, height = image.size
    pixels = to_bgra_premul(image)

    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB

    screen = user32.GetDC(0)
    mem = gdi32.CreateCompatibleDC(screen)
    bits = ctypes.c_void_p()
    bitmap = gdi32.CreateDIBSection(mem, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits), None, 0)
    if not bitmap or not bits:
        gdi32.DeleteDC(mem)
        user32.ReleaseDC(0, screen)
        raise RuntimeError("创建分层位图失败")
    ctypes.memmove(bits, pixels, len(pixels))
    old = gdi32.SelectObject(mem, bitmap)

    dst = POINT(int(x), int(y))
    size = SIZE(width, height)
    src = POINT(0, 0)
    blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
    ok = user32.UpdateLayeredWindow(
        hwnd, screen, ctypes.byref(dst), ctypes.byref(size), mem, ctypes.byref(src), 0, ctypes.byref(blend), ULW_ALPHA
    )
    gdi32.SelectObject(mem, old)
    gdi32.DeleteObject(bitmap)
    gdi32.DeleteDC(mem)
    user32.ReleaseDC(0, screen)
    if not ok:
        raise ctypes.WinError()


_RUN = re.compile(rb"\x01+")


def _spans(image: Image.Image, threshold: int = 28) -> list[tuple[int, int, int, int]]:
    # 先把透明度二值化成 0/1，再用正则找每行的连续不透明段，比逐像素循环快几十倍。
    mask = image.getchannel("A").point(lambda a: 1 if a >= threshold else 0)
    width, height = mask.size
    raw = mask.tobytes()
    rects: list[list[int]] = []
    active: dict[tuple[int, int], int] = {}
    for y in range(height):
        row = raw[y * width:(y + 1) * width]
        nxt: dict[tuple[int, int], int] = {}
        for run in _RUN.finditer(row):
            key = run.span()
            if key in active:
                rects[active[key]][3] = y + 1
                nxt[key] = active[key]
            else:
                rects.append([key[0], y, key[1], y + 1])
                nxt[key] = len(rects) - 1
        active = nxt
    return [tuple(item) for item in rects]


def set_hit_region(hwnd, image: Image.Image) -> None:
    rects = _spans(image)
    if not rects:
        region = gdi32.CreateRectRgn(0, 0, 0, 0) if hasattr(gdi32, "CreateRectRgn") else None
        if region:
            user32.SetWindowRgn(hwnd, region, True)
        return
    header_size = ctypes.sizeof(RGNDATAHEADER)
    rect_size = ctypes.sizeof(RECT)
    count = len(rects)
    buf = ctypes.create_string_buffer(header_size + count * rect_size)
    header = RGNDATAHEADER.from_buffer(buf)
    header.dwSize = header_size
    header.iType = RDH_RECTANGLES
    header.nCount = count
    header.nRgnSize = count * rect_size
    header.rcBound.left = min(item[0] for item in rects)
    header.rcBound.top = min(item[1] for item in rects)
    header.rcBound.right = max(item[2] for item in rects)
    header.rcBound.bottom = max(item[3] for item in rects)
    array = (RECT * count).from_buffer(buf, header_size)
    for index, (left, top, right, bottom) in enumerate(rects):
        array[index].left = left
        array[index].top = top
        array[index].right = right
        array[index].bottom = bottom
    region = gdi32.ExtCreateRegion(None, len(buf), buf)
    if region:
        # 系统接管 region，不能再 DeleteObject。
        user32.SetWindowRgn(hwnd, region, True)


gdi32.CreateRectRgn.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
gdi32.CreateRectRgn.restype = wintypes.HRGN
