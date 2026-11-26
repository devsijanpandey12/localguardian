"""Typed native Windows OS controls (zero raw shell execution).

Provides strictly bounded controls for:
- Display brightness (`screen-brightness-control` via WMI / DDC-CI)
- Master audio volume & mute (`pycaw` via Windows Core Audio API)
- Media playback keys (`play_pause`, `next`, `previous` via Win32 keybd_event)
- Launching explicitly allowlisted applications (`shell=False`)
- Sandboxed PNG screenshot capture strictly inside ~/LocalGuardian_Workspace/screenshots
- Read-only system health diagnostics (brightness, volume, battery, CPU, RAM, GPU)
- Safe 1-command workspace presets (coding, study, focus, relax)
"""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from localguardian.config import AppSpec, LocalGuardianConfig


VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002


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
            return {"before": target, "level": target, "note": "Simulated on non-Windows platform."}
        import screen_brightness_control as sbc  # type: ignore

        before_levels = sbc.get_brightness()
        before = int(before_levels[0]) if before_levels else target
        sbc.set_brightness(target)
        levels = sbc.get_brightness()
        actual = int(levels[0]) if levels else target
        return {"before": before, "level": actual, "message": f"Display brightness set to {actual}%."}

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
            return {"before": target, "level": target}
        vol = self._get_volume_interface()
        before = round(float(vol.GetMasterVolumeLevelScalar()) * 100)
        vol.SetMasterVolumeLevelScalar(target / 100.0, None)
        if target > 0 and vol.GetMute():
            vol.SetMute(0, None)
        actual = round(float(vol.GetMasterVolumeLevelScalar()) * 100)
        return {"before": before, "level": actual, "message": f"System volume set to {actual}%."}

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
            return {"before_muted": False, "muted": bool(mute)}
        vol = self._get_volume_interface()
        current_mute = bool(vol.GetMute())
        new_mute = (not current_mute) if mute is None else bool(mute)
        vol.SetMute(1 if new_mute else 0, None)
        state = "muted" if new_mute else "unmuted"
        return {"before_muted": current_mute, "muted": new_mute, "message": f"System audio {state}."}

    # ------------------------------------------------------------------
    # Media Playback Keys (Win32 VK_MEDIA_*)
    # ------------------------------------------------------------------

    def media_control(self, action: str) -> Dict[str, Any]:
        act = action.strip().lower()
        vk_map = {
            "play_pause": (VK_MEDIA_PLAY_PAUSE, "Toggled media play/pause."),
            "next": (VK_MEDIA_NEXT_TRACK, "Skipped to next track."),
            "previous": (VK_MEDIA_PREV_TRACK, "Returned to previous track."),
        }
        if act not in vk_map:
            raise ValueError("action must be one of: play_pause, next, previous")

        vk, msg = vk_map[act]
        if sys.platform == "win32":
            user32 = ctypes.windll.user32
            user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, 0)
            user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, 0)
        return {"action": act, "message": msg}

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
    # Sandboxed Screenshot Capture (workspace/screenshots ONLY)
    # ------------------------------------------------------------------

    def take_screenshot(self, filename: Optional[str] = None) -> Dict[str, Any]:
        from PIL import ImageGrab  # type: ignore

        root = (Path.home() / "LocalGuardian_Workspace" / "screenshots").resolve()
        root.mkdir(parents=True, exist_ok=True)

        if filename:
            base = Path(filename.strip()).name
            if not base.lower().endswith(".png"):
                base = f"{Path(base).stem}.png"
        else:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            base = f"screenshot_{stamp}.png"

        out_path = (root / base).resolve()
        # Extra defense-in-depth: guarantee output stays strictly inside screenshots root
        out_path.relative_to(root)

        img = ImageGrab.grab(all_screens=False)
        img.save(str(out_path), format="PNG")
        return {
            "path": str(out_path),
            "size": list(img.size),
            "message": f"Saved screenshot ({img.size[0]}x{img.size[1]}) to {out_path}.",
        }

    # ------------------------------------------------------------------
    # Safe 1-Command Workspace Presets
    # ------------------------------------------------------------------

    def activate_workspace_mode(self, mode: str) -> Dict[str, Any]:
        m = mode.strip().lower()
        presets: Dict[str, Dict[str, Any]] = {
            "coding": {"brightness": 75, "volume": 25, "mute": False, "label": "Coding Mode"},
            "study": {"brightness": 70, "volume": 0, "mute": True, "label": "Study Mode"},
            "focus": {"brightness": 65, "volume": 0, "mute": True, "label": "Focus Mode"},
            "relax": {"brightness": 50, "volume": 45, "mute": False, "label": "Relax Mode"},
        }
        if m not in presets:
            raise ValueError("mode must be one of: coding, study, focus, relax")

        preset = presets[m]
        actions_done: List[str] = []
        try:
            b = self.set_brightness(preset["brightness"])
            actions_done.append(f"brightness={b['level']}%")
        except Exception:
            pass
        try:
            if preset["mute"]:
                self.toggle_mute(True)
                actions_done.append("audio=muted")
            else:
                v = self.set_volume(preset["volume"])
                actions_done.append(f"volume={v['level']}%")
        except Exception:
            pass

        summary = ", ".join(actions_done) if actions_done else "applied"
        return {
            "mode": m,
            "summary": summary,
            "message": f"Activated {preset['label']} ({summary}).",
        }

    # ------------------------------------------------------------------
    # Read-Only System Health & Hardware Diagnostics
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

        if sys.platform == "win32":
            try:
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

        # Read-only CPU / RAM / top processes via psutil
        try:
            import psutil  # type: ignore

            cpu_pct = psutil.cpu_percent(interval=0.1)
            vm = psutil.virtual_memory()
            info["cpu_percent"] = round(cpu_pct, 1)
            info["ram"] = {
                "used_gb": round(vm.used / (1024**3), 1),
                "total_gb": round(vm.total / (1024**3), 1),
                "percent": round(vm.percent, 1),
            }
            procs = []
            for p in psutil.process_iter(["name", "memory_info"]):
                try:
                    mem_mb = (p.info["memory_info"].rss if p.info.get("memory_info") else 0) / (1024 * 1024)
                    if p.info.get("name"):
                        procs.append((mem_mb, p.info["name"]))
                except Exception:
                    continue
            procs.sort(reverse=True)
            info["top_ram_processes"] = [
                {"name": name, "ram_mb": round(mb)} for mb, name in procs[:3]
            ]
        except Exception:
            pass

        # Read-only NVIDIA GPU telemetry (shell=False, fixed hardcoded args)
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            try:
                res = subprocess.run(
                    [
                        nvidia_smi,
                        "--query-gpu=name,temperature.gpu,utilization.gpu,memory.used,memory.total",
                        "--format=csv,noheader,nounits",
                    ],
                    shell=False,
                    capture_output=True,
                    text=True,
                    timeout=3,
                    check=False,
                )
                line = res.stdout.strip().splitlines()[0] if res.stdout.strip() else ""
                cols = [c.strip() for c in line.split(",")]
                if len(cols) >= 5:
                    info["gpu"] = {
                        "name": cols[0],
                        "temp_c": int(cols[1]),
                        "util_percent": int(cols[2]),
                        "vram_used_mb": int(cols[3]),
                        "vram_total_mb": int(cols[4]),
                    }
            except Exception:
                pass

        parts = []
        if "level" in info.get("brightness", {}):
            parts.append(f"Brightness: {info['brightness']['level']}%")
        if "level" in info.get("volume", {}):
            muted = " (muted)" if info["volume"].get("muted") else ""
            parts.append(f"Volume: {info['volume']['level']}%{muted}")
        if info.get("battery", {}).get("percent") is not None:
            plug = "charging/AC" if info["battery"].get("plugged_in") else "on battery"
            parts.append(f"Battery: {info['battery']['percent']}% ({plug})")
        if "cpu_percent" in info and "ram" in info:
            ram = info["ram"]
            parts.append(f"CPU: {info['cpu_percent']}% | RAM: {ram['used_gb']}/{ram['total_gb']} GB ({ram['percent']}%)")
        if "gpu" in info:
            g = info["gpu"]
            parts.append(f"GPU: {g['temp_c']}C, {g['vram_used_mb']}/{g['vram_total_mb']} MB VRAM")

        info["message"] = " | ".join(parts) if parts else "System status checked."
        return info
