"""Typed native Windows OS controls (zero raw shell execution).

Provides strictly bounded controls for:
- Display brightness (`screen-brightness-control` via WMI / DDC-CI)
- Master audio volume & mute (`pycaw` via Windows Core Audio API)
- Launching explicitly allowlisted applications (`shell=False`)
- Read-only system health diagnostics (battery, brightness, volume)
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Optional

from localguardian.config import AppSpec, LocalGuardianConfig


def _clamp(value: int, low: int = 0, high: int = 100) -> int:
    return max(low, min(high, int(value)))


def resolve_app_executable(spec: AppSpec) -> Optional[str]:
    """Resolve an allowlisted AppSpec to a verified executable path."""
    for candidate in spec.candidates:
        expanded = Path(os.path.expandvars(os.path.expanduser(candidate)))
        if expanded.is_file():
            return str(expanded)
    if spec.command:
        found = shutil.which(spec.command)
        return found or spec.command
    return None


class OSControls:
    """Safe, typed Windows OS control bindings."""

    def __init__(self, config: LocalGuardianConfig) -> None:
        self.config = config

    # ------------------------------------------------------------------
    # Brightness (WMI / DDC-CI)
    # ------------------------------------------------------------------

    def get_brightness(self) -> Dict[str, Any]:
        if sys.platform != "win32":
            return {"levels": [], "note": "Brightness API requires Windows."}
        import screen_brightness_control as sbc  # type: ignore

        levels = sbc.get_brightness()
        current = int(levels[0]) if levels else 0
        return {"level": current, "levels": [int(x) for x in levels]}

    def set_brightness(self, level: int) -> Dict[str, Any]:
        target = _clamp(level, 0, 100)
        if sys.platform != "win32":
            return {"level": target, "note": "Simulated on non-Windows platform."}
        import screen_brightness_control as sbc  # type: ignore

        sbc.set_brightness(target)
        levels = sbc.get_brightness()
        actual = int(levels[0]) if levels else target
        return {"level": actual, "message": f"Display brightness set to {actual}%."}

    def adjust_brightness(self, delta: int) -> Dict[str, Any]:
        if sys.platform != "win32":
            return {"delta": delta, "note": "Simulated on non-Windows platform."}
        import screen_brightness_control as sbc  # type: ignore

        levels = sbc.get_brightness()
        before = int(levels[0]) if levels else 50
        target = _clamp(before + int(delta), 0, 100)
        sbc.set_brightness(target)
        after_levels = sbc.get_brightness()
        after = int(after_levels[0]) if after_levels else target
        direction = "increased" if delta >= 0 else "decreased"
        return {
            "before": before,
            "level": after,
            "delta": delta,
            "message": f"Display brightness {direction} from {before}% to {after}%.",
        }

    # ------------------------------------------------------------------
    # Audio Volume (Windows Core Audio via pycaw)
    # ------------------------------------------------------------------

    def _get_volume_interface(self):
        from comtypes import CLSCTX_ALL  # type: ignore
        from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume  # type: ignore

        devices = AudioUtilities.GetSpeakers()
        # Handle both newer pycaw (EndpointVolume property) and classic Activate()
        if hasattr(devices, "EndpointVolume"):
            return devices.EndpointVolume
        interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
        return interface.QueryInterface(IAudioEndpointVolume)

    def get_volume(self) -> Dict[str, Any]:
        if sys.platform != "win32":
            return {"level": 50, "muted": False}
        vol = self._get_volume_interface()
        level = round(float(vol.GetMasterVolumeLevelScalar()) * 100)
        muted = bool(vol.GetMute())
        return {"level": level, "muted": muted}

    def set_volume(self, level: int) -> Dict[str, Any]:
        target = _clamp(level, 0, 100)
        if sys.platform != "win32":
            return {"level": target}
        vol = self._get_volume_interface()
        vol.SetMasterVolumeLevelScalar(target / 100.0, None)
        if target > 0 and vol.GetMute():
            vol.SetMute(0, None)
        actual = round(float(vol.GetMasterVolumeLevelScalar()) * 100)
        return {"level": actual, "message": f"System volume set to {actual}%."}

    def adjust_volume(self, delta: int) -> Dict[str, Any]:
        current = self.get_volume()["level"]
        target = _clamp(current + int(delta), 0, 100)
        res = self.set_volume(target)
        direction = "increased" if delta >= 0 else "decreased"
        res["before"] = current
        res["delta"] = delta
        res["message"] = f"System volume {direction} from {current}% to {res['level']}%."
        return res

    def toggle_mute(self, mute: Optional[bool] = None) -> Dict[str, Any]:
        if sys.platform != "win32":
            return {"muted": bool(mute)}
        vol = self._get_volume_interface()
        current_mute = bool(vol.GetMute())
        new_mute = (not current_mute) if mute is None else bool(mute)
        vol.SetMute(1 if new_mute else 0, None)
        state = "muted" if new_mute else "unmuted"
        return {"muted": new_mute, "message": f"System audio {state}."}

    # ------------------------------------------------------------------
    # Allowlisted Application Launcher (shell=False ONLY)
    # ------------------------------------------------------------------

    def open_app(self, app_name: str) -> Dict[str, Any]:
        key = app_name.strip().lower()
        spec = self.config.safety.allowed_apps.get(key)
        if spec is None:
            raise ValueError(f"App '{app_name}' is not in the allowlist.")

        executable = resolve_app_executable(spec)
        if not executable:
            raise FileNotFoundError(
                f"Could not find executable for allowlisted app '{spec.display_name}'."
            )

        # Strictly shell=False — never passes through cmd.exe or PowerShell
        proc = subprocess.Popen(
            [executable],
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return {
            "app": key,
            "display_name": spec.display_name,
            "pid": proc.pid,
            "message": f"Launched {spec.display_name}.",
        }

    # ------------------------------------------------------------------
    # Read-Only System Diagnostics
    # ------------------------------------------------------------------

    def get_system_status(self) -> Dict[str, Any]:
        info: Dict[str, Any] = {}
        try:
            info["brightness"] = self.get_brightness()
        except Exception as exc:
            info["brightness"] = {"error": str(exc)}

        try:
            info["volume"] = self.get_volume()
        except Exception as exc:
            info["volume"] = {"error": str(exc)}

        # Read-only Windows battery status via Win32 GetSystemPowerStatus
        if sys.platform == "win32":
            try:
                import ctypes

                class SYSTEM_POWER_STATUS(ctypes.Structure):
                    _fields_ = [
                        ("ACLineStatus", ctypes.c_byte),
                        ("BatteryFlag", ctypes.c_byte),
                        ("BatteryLifePercent", ctypes.c_byte),
                        ("SystemStatusFlag", ctypes.c_byte),
                        ("BatteryLifeTime", ctypes.c_ulong),
                        ("BatteryFullLifeTime", ctypes.c_ulong),
                    ]

                status = SYSTEM_POWER_STATUS()
                if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
                    pct = int(status.BatteryLifePercent)
                    info["battery"] = {
                        "percent": pct if pct <= 100 else None,
                        "plugged_in": status.ACLineStatus == 1,
                    }
            except Exception as exc:
                info["battery"] = {"error": str(exc)}

        parts = []
        if "level" in info.get("brightness", {}):
            parts.append(f"Brightness: {info['brightness']['level']}%")
        if "level" in info.get("volume", {}):
            muted = " (muted)" if info["volume"].get("muted") else ""
            parts.append(f"Volume: {info['volume']['level']}%{muted}")
        if info.get("battery", {}).get("percent") is not None:
            plug = "charging/AC" if info["battery"].get("plugged_in") else "on battery"
            parts.append(f"Battery: {info['battery']['percent']}% ({plug})")

        info["message"] = " | ".join(parts) if parts else "System status checked."
        return info
