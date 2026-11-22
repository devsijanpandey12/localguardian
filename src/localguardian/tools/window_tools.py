"""Safe Win32 window inspection, focusing, and monitor-aware snapping tools.

Runs strictly under the current standard-user privilege level (Windows UIPI
prevents interacting with elevated/UAC windows). Never closes or kills apps.
"""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


SW_RESTORE = 9
SW_MAXIMIZE = 3
SW_MINIMIZE = 6
SPI_GETWORKAREA = 48
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


class _RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32

    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.MoveWindow.argtypes = [
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.BOOL,
    ]
    _user32.MoveWindow.restype = wintypes.BOOL

    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL


def _get_work_area() -> Tuple[int, int, int, int]:
    """Return usable desktop rectangle excluding the Windows taskbar."""
    if sys.platform != "win32":
        return (0, 0, 1920, 1040)
    rect = _RECT()
    if _user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(rect), 0):
        return (rect.left, rect.top, rect.right, rect.bottom)
    w = _user32.GetSystemMetrics(0)
    h = _user32.GetSystemMetrics(1)
    return (0, 0, w, h)


def _get_process_name(hwnd: int) -> str:
    if sys.platform != "win32" or not hwnd:
        return ""
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(wintypes.HWND(hwnd), ctypes.byref(pid))
    if not pid.value:
        return ""
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(1024)
        buf = ctypes.create_unicode_buffer(size.value)
        if _kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
            return Path(buf.value).name.lower()
        return ""
    finally:
        _kernel32.CloseHandle(handle)


def list_visible_windows() -> List[Dict[str, Any]]:
    """Enumerate visible titled top-level windows on the Windows desktop."""
    if sys.platform != "win32":
        return []
    results: List[Dict[str, Any]] = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, _lparam):
        if _user32.IsWindowVisible(hwnd):
            length = _user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                _user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()
                if title and title not in {"Program Manager", "Settings"}:
                    results.append(
                        {
                            "hwnd": int(hwnd),
                            "title": title,
                            "process": _get_process_name(int(hwnd)),
                        }
                    )
        return True

    _user32.EnumWindows(_cb, 0)
    return results


def _find_matching_window(query: str, windows: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    q = query.strip().lower()
    if not q:
        return None
    aliases = {
        "chrome": ("chrome.exe", "google chrome"),
        "google chrome": ("chrome.exe", "google chrome"),
        "edge": ("msedge.exe", "microsoft edge"),
        "vscode": ("code.exe", "visual studio code"),
        "vs code": ("code.exe", "visual studio code"),
        "notepad": ("notepad.exe", "notepad"),
        "calculator": ("calculatorapp.exe", "calculator"),
        "spotify": ("spotify.exe", "spotify"),
        "explorer": ("explorer.exe", "file explorer"),
    }
    terms = aliases.get(q, (q,))

    for w in windows:
        proc = str(w.get("process", "")).lower()
        if any(t == proc or t in proc for t in terms):
            return w
    for w in windows:
        title = str(w.get("title", "")).lower()
        if any(t in title for t in terms):
            return w
    return None


class WindowController:
    """Safe, read/focus/snap Win32 window controls."""

    def list_open_windows(self) -> Dict[str, Any]:
        windows = list_visible_windows()
        titles = [f"{w['title']} ({w['process'] or 'unknown'})" for w in windows[:15]]
        msg = (
            f"Open windows ({len(windows)}): " + "; ".join(titles)
            if titles
            else "No titled desktop windows found."
        )
        return {"count": len(windows), "windows": windows[:20], "message": msg}

    def focus_window(self, window_name: str) -> Dict[str, Any]:
        windows = list_visible_windows()
        match = _find_matching_window(window_name, windows)
        if not match:
            raise LookupError(f"No open window matched '{window_name}'.")

        hwnd = int(match["hwnd"])
        if sys.platform == "win32":
            _user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
            _user32.BringWindowToTop(wintypes.HWND(hwnd))
            _user32.SetForegroundWindow(wintypes.HWND(hwnd))

        return {
            "hwnd": hwnd,
            "title": match["title"],
            "process": match["process"],
            "message": f"Focused window '{match['title']}'.",
        }

    def snap_window(self, window_name: str, position: str) -> Dict[str, Any]:
        pos = position.strip().lower()
        if pos not in {"left", "right", "maximize", "minimize"}:
            raise ValueError("position must be one of: left, right, maximize, minimize")

        windows = list_visible_windows()
        match = _find_matching_window(window_name, windows)
        if not match:
            raise LookupError(f"No open window matched '{window_name}'.")

        hwnd = int(match["hwnd"])
        if sys.platform == "win32":
            if pos == "maximize":
                _user32.ShowWindow(wintypes.HWND(hwnd), SW_MAXIMIZE)
                _user32.SetForegroundWindow(wintypes.HWND(hwnd))
            elif pos == "minimize":
                _user32.ShowWindow(wintypes.HWND(hwnd), SW_MINIMIZE)
            else:
                left, top, right, bottom = _get_work_area()
                width = (right - left) // 2
                height = bottom - top
                x = left if pos == "left" else left + width
                _user32.ShowWindow(wintypes.HWND(hwnd), SW_RESTORE)
                _user32.MoveWindow(wintypes.HWND(hwnd), x, top, width, height, True)
                _user32.SetForegroundWindow(wintypes.HWND(hwnd))

        return {
            "hwnd": hwnd,
            "title": match["title"],
            "position": pos,
            "message": f"Snapped '{match['title']}' ({pos}).",
        }
