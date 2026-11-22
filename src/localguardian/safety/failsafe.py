"""Emergency kill-switch and mouse corner-slam failsafe."""

from __future__ import annotations

import ctypes
import sys
import threading


class FailsafeTriggeredError(RuntimeError):
    """Raised when the operator triggers the emergency abort failsafe."""


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class FailsafeController:
    """Thread-safe emergency abort controller with optional corner-slam detection."""

    def __init__(self, corner_threshold_px: int = 4, enable_corner_slam: bool = True) -> None:
        self._aborted = threading.Event()
        self.corner_threshold_px = corner_threshold_px
        self.enable_corner_slam = enable_corner_slam

    def trigger_abort(self) -> None:
        self._aborted.set()

    def reset(self) -> None:
        self._aborted.clear()

    def _mouse_in_top_left_corner(self) -> bool:
        if not self.enable_corner_slam or sys.platform != "win32":
            return False
        try:
            pt = _POINT()
            if ctypes.windll.user32.GetCursorPos(ctypes.byref(pt)):
                return pt.x <= self.corner_threshold_px and pt.y <= self.corner_threshold_px
        except Exception:
            return False
        return False

    def check(self) -> None:
        """Raise FailsafeTriggeredError if kill switch or corner-slam is active."""
        if self._aborted.is_set():
            raise FailsafeTriggeredError("Emergency kill switch activated by user.")
        if self._mouse_in_top_left_corner():
            self._aborted.set()
            raise FailsafeTriggeredError(
                "Mouse corner-slam failsafe triggered (cursor at top-left corner)."
            )
