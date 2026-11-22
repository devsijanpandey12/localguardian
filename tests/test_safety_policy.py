"""Adversarial & functional unit tests for LocalGuardian's hard-coded SafetyPolicy."""

from __future__ import annotations

from pathlib import Path

import pytest

from localguardian.config import load_config
from localguardian.safety.policy import RiskLevel, SafetyPolicy


@pytest.fixture()
def policy() -> SafetyPolicy:
    cfg = load_config()
    cfg.safety.allow_file_tools = True
    return SafetyPolicy(cfg)


@pytest.mark.parametrize(
    "dangerous_path",
    [
        r"C:\Windows\System32\cmd.exe",
        r"C:\Windows\win.ini",
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Common Files\test.dll",
        r"C:\ProgramData\Microsoft\test.dat",
        r"C:\Users\sijan\Desktop\..\..\..\..\Windows\System32\drivers\etc\hosts",
        r"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Run",
        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
        r"\\192.168.1.5\share\payload.exe",
    ],
)
def test_blocks_protected_system_and_program_paths(policy: SafetyPolicy, dangerous_path: str) -> None:
    verdict_read = policy.check_path(dangerous_path, write=False)
    verdict_write = policy.check_path(dangerous_path, write=True)
    assert not verdict_read.allowed
    assert verdict_read.risk == RiskLevel.FORBIDDEN
    assert not verdict_write.allowed
    assert verdict_write.risk == RiskLevel.FORBIDDEN


@pytest.mark.parametrize(
    "secret_path",
    [
        r"~/.ssh/id_rsa",
        r"~/.aws/credentials",
        r"~/LocalGuardian_Workspace/.env",
        r"~/LocalGuardian_Workspace/server.pem",
        r"~/LocalGuardian_Workspace/private.key",
        r"~/.localguardian/audit.db",
    ],
)
def test_blocks_secret_and_internal_paths(policy: SafetyPolicy, secret_path: str) -> None:
    verdict = policy.check_path(secret_path, write=False)
    assert not verdict.allowed
    assert verdict.risk == RiskLevel.FORBIDDEN


def test_blocks_writing_executables_even_inside_workspace(policy: SafetyPolicy) -> None:
    for ext in (".exe", ".ps1", ".bat", ".cmd", ".vbs", ".reg", ".msi"):
        verdict = policy.check_path(f"~/LocalGuardian_Workspace/test{ext}", write=True)
        assert not verdict.allowed
        assert verdict.risk == RiskLevel.FORBIDDEN
        assert verdict.rule_id == "BLOCKED_EXECUTABLE_WRITE"


def test_default_deny_outside_allowed_folders(policy: SafetyPolicy) -> None:
    verdict = policy.check_path("~/random_unapproved_folder/notes.txt", write=False)
    assert not verdict.allowed
    assert verdict.rule_id == "OUTSIDE_ALLOWED_FOLDERS"


def test_allows_safe_text_file_inside_allowed_workspace(policy: SafetyPolicy) -> None:
    verdict_read = policy.check_path("~/LocalGuardian_Workspace/notes.txt", write=False)
    assert verdict_read.allowed
    assert verdict_read.risk == RiskLevel.SAFE

    verdict_write = policy.check_path("~/LocalGuardian_Workspace/notes.txt", write=True)
    assert verdict_write.allowed
    assert verdict_write.risk == RiskLevel.MEDIUM
    assert verdict_write.requires_confirmation is True


def test_file_tools_disabled_by_default() -> None:
    cfg = load_config()
    cfg.safety.allow_file_tools = False
    pol = SafetyPolicy(cfg)
    verdict = pol.check_path("~/LocalGuardian_Workspace/notes.txt", write=False)
    assert not verdict.allowed
    assert verdict.rule_id == "FILE_TOOLS_DISABLED"


@pytest.mark.parametrize(
    "tool_name",
    ["run_powershell", "run_cmd", "run_command", "powershell", "cmd", "shell", "exec", "regedit"],
)
def test_blocks_raw_shell_and_forbidden_tools(policy: SafetyPolicy, tool_name: str) -> None:
    verdict = policy.evaluate(tool_name, {"command": "dir"})
    assert not verdict.allowed
    assert verdict.risk == RiskLevel.FORBIDDEN
    assert verdict.rule_id == "BLOCKED_FORBIDDEN_TOOL"


@pytest.mark.parametrize(
    "bad_app",
    [
        "powershell",
        "powershell.exe",
        "cmd",
        "cmd.exe",
        "regedit",
        "diskpart",
        r"C:\Windows\System32\cmd.exe",
        "unknown_random_app",
    ],
)
def test_blocks_forbidden_and_unlisted_apps(policy: SafetyPolicy, bad_app: str) -> None:
    verdict = policy.evaluate("open_app", {"app_name": bad_app})
    assert not verdict.allowed
    assert verdict.risk == RiskLevel.FORBIDDEN


def test_allows_chrome_and_notepad(policy: SafetyPolicy) -> None:
    for app in ("chrome", "notepad", "calculator"):
        verdict = policy.evaluate("open_app", {"app_name": app})
        assert verdict.allowed
        assert verdict.risk == RiskLevel.SAFE


@pytest.mark.parametrize(
    "bad_url",
    [
        "file:///C:/Windows/win.ini",
        "javascript:alert(1)",
        "chrome://settings",
        "edge://settings",
        "data:text/html,<script>alert(1)</script>",
    ],
)
def test_blocks_unsafe_url_schemes(policy: SafetyPolicy, bad_url: str) -> None:
    verdict = policy.evaluate("chrome_open_url", {"url": bad_url})
    assert not verdict.allowed
    assert verdict.rule_id == "BLOCKED_URL_SCHEME"


def test_allows_safe_urls_and_chrome_search(policy: SafetyPolicy) -> None:
    v1 = policy.evaluate("chrome_open_url", {"url": "https://en.wikipedia.org/wiki/Elon_Musk"})
    assert v1.allowed
    assert v1.risk == RiskLevel.SAFE

    v2 = policy.evaluate("chrome_open_url", {"url": "wikipedia.org"})
    assert v2.allowed
    assert v2.details["normalized_url"] == "https://wikipedia.org"

    v3 = policy.evaluate("chrome_search", {"query": "Elon Musk"})
    assert v3.allowed
    assert v3.risk == RiskLevel.SAFE


@pytest.mark.parametrize(
    "bad_hotkey",
    [
        ["win", "r"],
        ["windows", "d"],
        ["alt", "f4"],
        ["shift", "alt", "f4"],
        ["ctrl", "alt", "del"],
        ["ctrl", "shift", "esc"],
    ],
)
def test_blocks_blacklisted_os_hotkeys(policy: SafetyPolicy, bad_hotkey: list[str]) -> None:
    verdict = policy.evaluate("send_hotkey", {"keys": bad_hotkey})
    assert not verdict.allowed
    assert verdict.rule_id == "BLOCKED_OS_HOTKEY"


def test_brightness_and_volume_bounds(policy: SafetyPolicy) -> None:
    assert policy.evaluate("adjust_brightness", {"delta": 20}).allowed
    assert policy.evaluate("set_brightness", {"level": 75}).allowed
    assert not policy.evaluate("set_brightness", {"level": 150}).allowed
    assert policy.evaluate("adjust_volume", {"delta": -15}).allowed
    assert not policy.evaluate("set_volume", {"level": -5}).allowed
