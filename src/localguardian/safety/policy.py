"""Hard-coded deterministic Safety Policy Engine for LocalGuardian.

SECURITY INVARIANT:
    Protected Windows system directories, Program Files, Registry hives,
    credential stores, raw shell execution, and dangerous OS hotkeys are
    HARD-CODED here in Python and CANNOT be overridden by an LLM prompt
    or user YAML config.
"""

from __future__ import annotations

import ctypes
import os
import re
import sys
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import urlparse

from pydantic import BaseModel, Field

from localguardian.config import LocalGuardianConfig


class RiskLevel(str, Enum):
    SAFE = "SAFE"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    FORBIDDEN = "FORBIDDEN"


class PolicyVerdict(BaseModel):
    allowed: bool
    risk: RiskLevel
    rule_id: str
    reason: str
    requires_confirmation: bool = False
    details: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# IMMUTABLE HARD-CODED SECURITY BOUNDARIES
# ---------------------------------------------------------------------------

# Raw shell / arbitrary code execution tools are permanently forbidden.
FORBIDDEN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "run_command",
        "run_powershell",
        "run_cmd",
        "powershell",
        "cmd",
        "bash",
        "shell",
        "exec",
        "eval",
        "system",
        "regedit",
        "edit_registry",
        "delete_system_file",
        "format_drive",
    }
)

# Executables that are NEVER allowed to be launched even if added to config.
FORBIDDEN_APPS: frozenset[str] = frozenset(
    {
        "powershell",
        "powershell.exe",
        "pwsh",
        "pwsh.exe",
        "cmd",
        "cmd.exe",
        "regedit",
        "regedit.exe",
        "reg",
        "reg.exe",
        "diskpart",
        "diskpart.exe",
        "format",
        "format.com",
        "bcdedit",
        "bcdedit.exe",
        "sc",
        "sc.exe",
        "netsh",
        "wmic",
        "mshta",
        "cscript",
        "wscript",
        "rundll32",
        "msiexec",
        "taskkill",
        "shutdown",
        "certutil",
    }
)

# Hard-coded Windows system & program directories that must NEVER be touched.
HARD_BLOCKED_SYSTEM_PREFIXES: Tuple[str, ...] = (
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\programdata",
    r"c:\$recycle.bin",
    r"c:\system volume information",
    r"c:\recovery",
    r"c:\boot",
    r"c:\perflogs",
)

# Registry hive patterns (never touch Windows Registry).
REGISTRY_PATTERN = re.compile(
    r"^(?:hklm|hkcu|hkcr|hku|hkcc|hkey_local_machine|hkey_current_user|hkey_classes_root)[:\\]",
    re.IGNORECASE,
)

# Credential / secret directories and files.
SECRET_PATH_PARTS: Tuple[str, ...] = (
    ".ssh",
    ".aws",
    ".azure",
    ".gnupg",
    ".kube",
    ".docker",
    ".git-credentials",
    ".netrc",
    ".localguardian",
    "login data",
    "cookies",
    "web data",
    "local state",
    "microsoft\\protect",
    "microsoft\\credentials",
    "microsoft\\vault",
    "start menu\\programs\\startup",
)

SECRET_EXTENSIONS: frozenset[str] = frozenset(
    {".pem", ".key", ".pfx", ".p12", ".kdbx", ".ppk", ".env"}
)

EXECUTABLE_EXTENSIONS: frozenset[str] = frozenset(
    {
        ".exe",
        ".bat",
        ".cmd",
        ".ps1",
        ".psm1",
        ".vbs",
        ".vbe",
        ".js",
        ".jse",
        ".wsf",
        ".wsh",
        ".com",
        ".scr",
        ".msi",
        ".dll",
        ".sys",
        ".drv",
        ".reg",
        ".hta",
        ".cpl",
        ".lnk",
    }
)

# Allowed URL schemes for browser navigation.
ALLOWED_URL_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Hotkey normalization & blacklist (matches Servo's conservative rule: subset match).
KEY_ALIASES: Dict[str, str] = {
    "control": "ctrl",
    "ctl": "ctrl",
    "lctrl": "ctrl",
    "rctrl": "ctrl",
    "menu": "alt",
    "lalt": "alt",
    "ralt": "alt",
    "lshift": "shift",
    "rshift": "shift",
    "windows": "win",
    "lwin": "win",
    "rwin": "win",
    "meta": "win",
    "super": "win",
    "delete": "del",
    "escape": "esc",
    "return": "enter",
}

HOTKEY_BLACKLIST: Tuple[frozenset[str], ...] = (
    frozenset({"win"}),
    frozenset({"alt", "f4"}),
    frozenset({"alt", "tab"}),
    frozenset({"alt", "esc"}),
    frozenset({"ctrl", "esc"}),
    frozenset({"ctrl", "alt", "del"}),
    frozenset({"ctrl", "shift", "esc"}),
)

# Explicit risk classification for registered prototype tools.
TOOL_BASE_RISK: Dict[str, RiskLevel] = {
    "get_brightness": RiskLevel.SAFE,
    "set_brightness": RiskLevel.SAFE,
    "adjust_brightness": RiskLevel.SAFE,
    "get_volume": RiskLevel.SAFE,
    "set_volume": RiskLevel.SAFE,
    "adjust_volume": RiskLevel.SAFE,
    "toggle_mute": RiskLevel.SAFE,
    "media_control": RiskLevel.SAFE,
    "open_app": RiskLevel.SAFE,
    "chrome_open_url": RiskLevel.SAFE,
    "chrome_search": RiskLevel.SAFE,
    "chrome_get_page_info": RiskLevel.SAFE,
    "get_system_status": RiskLevel.SAFE,
    "list_open_windows": RiskLevel.SAFE,
    "focus_window": RiskLevel.SAFE,
    "snap_window": RiskLevel.SAFE,
    "take_screenshot": RiskLevel.SAFE,
    "activate_workspace_mode": RiskLevel.SAFE,
    "read_user_file": RiskLevel.SAFE,
    "write_user_file": RiskLevel.MEDIUM,
    "send_hotkey": RiskLevel.MEDIUM,
}


def is_running_as_admin() -> bool:
    """Return True if the current Windows process has Administrator privileges."""
    if sys.platform != "win32":
        return os.geteuid() == 0 if hasattr(os, "geteuid") else False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def normalize_keys(keys: Iterable[str]) -> List[str]:
    return [KEY_ALIASES.get(k.strip().lower(), k.strip().lower()) for k in keys if k.strip()]


def is_hotkey_blacklisted(keys: Iterable[str]) -> bool:
    combo = set(normalize_keys(keys))
    return any(blocked <= combo for blocked in HOTKEY_BLACKLIST)


def _normalize_windows_str(path_str: str) -> str:
    return path_str.replace("/", "\\").rstrip("\\").lower()


def _is_under_prefix(normalized_path: str, normalized_prefix: str) -> bool:
    return normalized_path == normalized_prefix or normalized_path.startswith(
        normalized_prefix + "\\"
    )


class SafetyPolicy:
    """Deterministic policy gate evaluated before ANY tool executes."""

    def __init__(self, config: LocalGuardianConfig) -> None:
        self.config = config
        self._dynamic_blocked_prefixes = self._build_protected_prefixes()
        self._allowed_user_roots = self._build_allowed_user_roots()

    def _build_protected_prefixes(self) -> Tuple[str, ...]:
        prefixes: List[str] = list(HARD_BLOCKED_SYSTEM_PREFIXES)
        env_dirs = [
            os.environ.get("SystemRoot"),
            os.environ.get("WINDIR"),
            os.environ.get("ProgramFiles"),
            os.environ.get("ProgramFiles(x86)"),
            os.environ.get("ProgramW6432"),
            os.environ.get("ProgramData"),
            os.environ.get("APPDATA"),
            os.environ.get("LOCALAPPDATA"),
        ]
        for raw in env_dirs:
            if raw:
                try:
                    resolved = str(Path(raw).resolve(strict=False))
                except Exception:
                    resolved = raw
                norm = _normalize_windows_str(resolved)
                if norm and norm not in prefixes:
                    prefixes.append(norm)

        # Always protect LocalGuardian's own state directory
        lg_home = _normalize_windows_str(str(self.config.home_dir))
        if lg_home not in prefixes:
            prefixes.append(lg_home)

        return tuple(prefixes)

    def _build_allowed_user_roots(self) -> Tuple[Path, ...]:
        roots: List[Path] = []
        for raw in self.config.safety.allowed_user_folders:
            expanded = os.path.expandvars(os.path.expanduser(raw))
            resolved = Path(expanded).resolve(strict=False)
            roots.append(resolved)
        return tuple(roots)

    # ------------------------------------------------------------------
    # Specialized Validators
    # ------------------------------------------------------------------

    def check_path(self, raw_path: str, *, write: bool = False) -> PolicyVerdict:
        """Enforce hard-coded OS/Program Files/secret blocks and default-deny allowlist."""
        cleaned = raw_path.strip().strip("\"'")
        if not cleaned:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="PATH_EMPTY",
                reason="Path cannot be empty.",
            )

        # Block Registry paths immediately
        if REGISTRY_PATTERN.match(cleaned):
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_REGISTRY_PATH",
                reason=f"Access to Windows Registry path '{cleaned}' is permanently forbidden.",
            )

        # Block raw drive root or UNC network shares
        if cleaned.startswith("\\\\") or cleaned.startswith("//"):
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_UNC_PATH",
                reason="Network/UNC paths are forbidden for local safety.",
            )

        expanded = os.path.expandvars(os.path.expanduser(cleaned))
        resolved = Path(expanded).resolve(strict=False)
        norm = _normalize_windows_str(str(resolved))

        # 1. Hard-coded protected OS, Program Files, ProgramData, AppData, ~/.localguardian
        for prefix in self._dynamic_blocked_prefixes:
            if _is_under_prefix(norm, prefix):
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="BLOCKED_PROTECTED_SYSTEM_PATH",
                    reason=(
                        f"Blocked access to protected system/program directory: '{resolved}'. "
                        "LocalGuardian never touches Windows, Program Files, AppData, or internal state."
                    ),
                    details={"resolved_path": str(resolved), "matched_prefix": prefix},
                )

        # 2. Secret / credential paths & extensions
        suffix = resolved.suffix.lower()
        name_lower = resolved.name.lower()
        if (
            suffix in SECRET_EXTENSIONS
            or name_lower == ".env"
            or name_lower.startswith(".env.")
            or any(part in norm for part in SECRET_PATH_PARTS)
        ):
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_SECRET_PATH",
                reason=f"Blocked access to sensitive credential or secret path: '{resolved}'.",
                details={"resolved_path": str(resolved)},
            )

        # 3. Never allow writing executables or scripts
        if write and suffix in EXECUTABLE_EXTENSIONS:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_EXECUTABLE_WRITE",
                reason=f"Writing executable or script files ('{suffix}') is permanently forbidden.",
                details={"resolved_path": str(resolved)},
            )

        # 4. File tools must be explicitly opted in
        if not self.config.safety.allow_file_tools:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="FILE_TOOLS_DISABLED",
                reason="File tools are disabled by default for safety (enable safety.allow_file_tools explicitly).",
            )

        # 5. Default-deny allowlist: must be inside an explicitly approved user folder
        in_allowed_root = False
        for root in self._allowed_user_roots:
            if _is_under_prefix(norm, _normalize_windows_str(str(root))):
                in_allowed_root = True
                break

        if not in_allowed_root:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="OUTSIDE_ALLOWED_FOLDERS",
                reason=(
                    f"Path '{resolved}' is outside your allowlisted user folders: "
                    f"{[str(r) for r in self._allowed_user_roots]}."
                ),
                details={"resolved_path": str(resolved)},
            )

        risk = RiskLevel.MEDIUM if write else RiskLevel.SAFE
        return PolicyVerdict(
            allowed=True,
            risk=risk,
            rule_id="ALLOWED_USER_PATH",
            reason=f"Path '{resolved}' verified inside allowlisted workspace.",
            requires_confirmation=(risk != RiskLevel.SAFE and self.config.safety.confirm_medium_risk),
            details={"resolved_path": str(resolved)},
        )

    def check_app(self, app_name: str) -> PolicyVerdict:
        """Allow launching ONLY explicitly allowlisted, non-shell applications."""
        key = app_name.strip().lower()
        if not key:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="APP_EMPTY",
                reason="Application name cannot be empty.",
            )

        # Block raw path attempts or forbidden system/shell binaries
        if "\\" in key or "/" in key or ":" in key:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_ARBITRARY_APP_PATH",
                reason="Launching arbitrary executable paths is forbidden; use an allowlisted app name.",
            )

        base_key = key[:-4] if key.endswith(".exe") else key
        if key in FORBIDDEN_APPS or base_key in FORBIDDEN_APPS:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_SYSTEM_BINARY",
                reason=f"Launching system/shell utility '{app_name}' is permanently forbidden.",
            )

        if base_key not in self.config.safety.allowed_apps:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="APP_NOT_ALLOWLISTED",
                reason=(
                    f"Application '{app_name}' is not in the allowlist. "
                    f"Allowed apps: {sorted(self.config.safety.allowed_apps.keys())}"
                ),
            )

        return PolicyVerdict(
            allowed=True,
            risk=RiskLevel.SAFE,
            rule_id="APP_ALLOWLISTED",
            reason=f"Application '{base_key}' is allowlisted.",
            requires_confirmation=False,
            details={"app_key": base_key},
        )

    def check_url(self, url: str) -> PolicyVerdict:
        """Validate browser URLs: allow ONLY http:// and https://."""
        cleaned = url.strip()
        if not cleaned:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="URL_EMPTY",
                reason="URL cannot be empty.",
            )

        # Normalize bare domains like "wikipedia.org" to https://
        candidate = cleaned if "://" in cleaned else (
            cleaned if re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:", cleaned) else f"https://{cleaned}"
        )
        parsed = urlparse(candidate)
        scheme = (parsed.scheme or "").lower()

        if scheme not in ALLOWED_URL_SCHEMES:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_URL_SCHEME",
                reason=(
                    f"URL scheme '{scheme or 'unknown'}' is forbidden. "
                    "Only http:// and https:// URLs are permitted."
                ),
            )

        if not parsed.netloc:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="INVALID_URL_HOST",
                reason=f"URL '{cleaned}' does not contain a valid host.",
            )

        return PolicyVerdict(
            allowed=True,
            risk=RiskLevel.SAFE,
            rule_id="URL_SAFE",
            reason=f"Validated URL '{candidate}'.",
            details={"normalized_url": candidate},
        )

    def check_hotkey(self, keys: Iterable[str]) -> PolicyVerdict:
        normalized = normalize_keys(keys)
        if not normalized:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="HOTKEY_EMPTY",
                reason="Hotkey list cannot be empty.",
            )
        if is_hotkey_blacklisted(normalized):
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_OS_HOTKEY",
                reason=f"Hotkey combination {normalized} is blacklisted to protect the Windows OS shell.",
            )
        return PolicyVerdict(
            allowed=True,
            risk=RiskLevel.MEDIUM,
            rule_id="HOTKEY_ALLOWED_WITH_CONFIRM",
            reason=f"Hotkey {normalized} permitted with user confirmation.",
            requires_confirmation=self.config.safety.confirm_medium_risk,
        )

    # ------------------------------------------------------------------
    # Master Gate
    # ------------------------------------------------------------------

    def evaluate(self, tool_name: str, args: Dict[str, Any]) -> PolicyVerdict:
        """Evaluate any proposed tool call BEFORE execution."""
        name = tool_name.strip().lower()

        # 0. Permanently block raw shell / forbidden tools
        if name in FORBIDDEN_TOOL_NAMES:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="BLOCKED_FORBIDDEN_TOOL",
                reason=f"Tool '{tool_name}' is permanently forbidden (raw shell/system modification is disabled).",
            )

        # 1. Fail closed on unknown tools
        if name not in TOOL_BASE_RISK:
            return PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="UNKNOWN_TOOL",
                reason=f"Tool '{tool_name}' is not in LocalGuardian's registered safe tool list.",
            )

        # 2. Tool-specific deterministic guardrails
        if name in {"read_user_file", "write_user_file"}:
            return self.check_path(str(args.get("path", "")), write=(name == "write_user_file"))

        if name == "open_app":
            return self.check_app(str(args.get("app_name", "")))

        if name == "chrome_open_url":
            return self.check_url(str(args.get("url", "")))

        if name == "chrome_search":
            query = str(args.get("query", "")).strip()
            if not query:
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="SEARCH_QUERY_EMPTY",
                    reason="Search query cannot be empty.",
                )
            if len(query) > 500:
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="SEARCH_QUERY_TOO_LONG",
                    reason="Search query exceeds maximum length (500 chars).",
                )
            return PolicyVerdict(
                allowed=True,
                risk=RiskLevel.SAFE,
                rule_id="CHROME_SEARCH_SAFE",
                reason=f"Safe Chrome search query validated ({len(query)} chars).",
            )

        if name == "send_hotkey":
            return self.check_hotkey(args.get("keys", []))

        if name == "set_brightness":
            level = args.get("level")
            if not isinstance(level, int) or not (0 <= level <= 100):
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="INVALID_BRIGHTNESS_RANGE",
                    reason="Brightness level must be an integer between 0 and 100.",
                )

        if name == "adjust_brightness":
            delta = args.get("delta")
            if not isinstance(delta, int) or not (-100 <= delta <= 100):
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="INVALID_BRIGHTNESS_DELTA",
                    reason="Brightness delta must be an integer between -100 and +100.",
                )

        if name == "set_volume":
            level = args.get("level")
            if not isinstance(level, int) or not (0 <= level <= 100):
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="INVALID_VOLUME_RANGE",
                    reason="Volume level must be an integer between 0 and 100.",
                )

        if name == "adjust_volume":
            delta = args.get("delta")
            if not isinstance(delta, int) or not (-100 <= delta <= 100):
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="INVALID_VOLUME_DELTA",
                    reason="Volume delta must be an integer between -100 and +100.",
                )

        if name == "media_control":
            action = str(args.get("action", "")).strip().lower()
            if action not in {"play_pause", "next", "previous"}:
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="INVALID_MEDIA_ACTION",
                    reason="Media action must be one of: play_pause, next, previous.",
                )

        if name == "snap_window":
            pos = str(args.get("position", "")).strip().lower()
            if pos not in {"left", "right", "maximize", "minimize"}:
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="INVALID_SNAP_POSITION",
                    reason="Window snap position must be one of: left, right, maximize, minimize.",
                )

        if name == "take_screenshot":
            raw_fn = args.get("filename")
            if raw_fn is not None:
                fn = str(raw_fn).strip()
                if (
                    not fn
                    or "/" in fn
                    or "\\" in fn
                    or ".." in fn
                    or ":" in fn
                    or not re.match(r"^[a-zA-Z0-9._-]+$", fn)
                ):
                    return PolicyVerdict(
                        allowed=False,
                        risk=RiskLevel.FORBIDDEN,
                        rule_id="BLOCKED_SCREENSHOT_PATH",
                        reason=(
                            "Screenshot filename must be a simple name (no directory paths or '..'); "
                            "files are strictly sandboxed inside ~/LocalGuardian_Workspace/screenshots/."
                        ),
                    )
                if Path(fn).suffix.lower() in EXECUTABLE_EXTENSIONS:
                    return PolicyVerdict(
                        allowed=False,
                        risk=RiskLevel.FORBIDDEN,
                        rule_id="BLOCKED_EXECUTABLE_WRITE",
                        reason="Screenshots may only be saved as .png image files.",
                    )

        if name == "activate_workspace_mode":
            mode = str(args.get("mode", "")).strip().lower()
            if mode not in {"coding", "study", "focus", "relax"}:
                return PolicyVerdict(
                    allowed=False,
                    risk=RiskLevel.FORBIDDEN,
                    rule_id="INVALID_WORKSPACE_MODE",
                    reason="Workspace mode must be one of: coding, study, focus, relax.",
                )

        base_risk = TOOL_BASE_RISK[name]
        needs_confirm = (
            base_risk in {RiskLevel.MEDIUM, RiskLevel.HIGH}
            and self.config.safety.confirm_medium_risk
        )
        return PolicyVerdict(
            allowed=True,
            risk=base_risk,
            rule_id=f"TOOL_{base_risk.value}",
            reason=f"Tool '{name}' approved under risk tier {base_risk.value}.",
            requires_confirmation=needs_confirm,
        )
