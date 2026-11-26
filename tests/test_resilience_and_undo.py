"""Tests for freeze prevention: pre-flight guard, typo recovery, Needle timeout, and Undo."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Dict

import pytest

from localguardian.brain.fast_grammar import FastGrammarParser, check_preflight, normalize_typos
from localguardian.brain.needle_router import CactusNeedleRouter
from localguardian.brain.orchestrator import LocalGuardianOrchestrator
from localguardian.config import load_config
from localguardian.safety.audit import AuditLogger
from localguardian.safety.confirm import ConfirmationChannel, ConfirmationManager
from localguardian.safety.policy import SafetyPolicy
from localguardian.tools.os_controls import OSControls
from localguardian.tools.registry import ToolRegistry


class _HangingNeedle:
    def complete(self, text: str, max_new_tokens: int = 96) -> Dict[str, Any]:
        time.sleep(2.0)
        return {"function_calls": [], "confidence": 0.0}


class _FakeOSControls(OSControls):
    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._brightness = 60
        self._volume = 50
        self._muted = False

    def set_brightness(self, level: int) -> Dict[str, Any]:
        before = self._brightness
        self._brightness = level
        return {"before": before, "level": level, "message": f"Display brightness set to {level}%."}

    def adjust_brightness(self, delta: int) -> Dict[str, Any]:
        before = self._brightness
        self._brightness = max(0, min(100, before + delta))
        return {"before": before, "level": self._brightness, "delta": delta, "message": f"Brightness {before}->{self._brightness}"}

    def set_volume(self, level: int) -> Dict[str, Any]:
        before = self._volume
        self._volume = level
        return {"before": before, "level": level, "message": f"Volume set to {level}%."}

    def toggle_mute(self, mute=None) -> Dict[str, Any]:
        before = self._muted
        self._muted = (not before) if mute is None else bool(mute)
        return {"before_muted": before, "muted": self._muted, "message": "toggled"}


@pytest.mark.parametrize("bad_input", ["asdfghjkl", "qwerty", "zzzzzz", "!", "x", "bcdfghjkl"])
def test_preflight_blocks_gibberish_instantly(bad_input: str) -> None:
    res = check_preflight(bad_input)
    assert res is not None
    assert res[0] == "invalid_input"
    assert "Try:" in res[1]


@pytest.mark.parametrize("greeting", ["hi", "hello", "thanks", "thank you", "okay"])
def test_preflight_handles_small_talk_instantly(greeting: str) -> None:
    res = check_preflight(greeting)
    assert res is not None
    assert res[0] == "small_talk"


def test_preflight_handles_help_and_undo() -> None:
    h = check_preflight("help")
    assert h is not None and h[0] == "help" and "Available LocalGuardian Commands" in h[1]
    u = check_preflight("undo that")
    assert u is not None and u[0] == "undo"


@pytest.mark.parametrize(
    ("typo_cmd", "expected_tool", "expected_args"),
    [
        ("open chorme", "open_app", {"app_name": "chrome"}),
        ("opne notpad", "open_app", {"app_name": "notepad"}),
        ("incrase brigtness", "adjust_brightness", {"delta": 20}),
        ("decrase volum", "adjust_volume", {"delta": -15}),
        ("puse music", "media_control", {"action": "play_pause"}),
        ("go to chorme and serch Elon Musk", "chrome_search", {"query": "Elon Musk"}),
    ],
)
def test_typo_normalizer_recovers_common_typos_without_mangling_queries(
    typo_cmd: str, expected_tool: str, expected_args: dict
) -> None:
    parser = FastGrammarParser()
    actions = parser.parse(typo_cmd)
    assert actions is not None and len(actions) == 1
    assert actions[0].tool_name == expected_tool
    assert actions[0].args == expected_args


def test_typo_normalizer_never_mangles_search_query() -> None:
    assert normalize_typos("search zzzabc in chrome").startswith("search zzzabc")


def test_needle_router_enforces_hard_timeout_without_freezing() -> None:
    cfg = load_config()
    cfg.needle.timeout_seconds = 0.15
    router = CactusNeedleRouter(cfg, needle_factory=lambda **_: _HangingNeedle())
    try:
        t0 = time.perf_counter()
        actions, trace = router.route("some slow command")
        elapsed = time.perf_counter() - t0
        assert actions is None
        assert trace["status"] == "timeout"
        assert elapsed < 0.8
    finally:
        router.close()


def test_undo_reverts_brightness_volume_and_mute(tmp_path: Path) -> None:
    cfg = load_config()
    cfg.safety.dry_run = False
    cfg.needle.enabled = False
    fake_os = _FakeOSControls(cfg)
    policy = SafetyPolicy(cfg)
    audit = AuditLogger(tmp_path / "undo_audit.db")
    registry = ToolRegistry(
        cfg,
        policy,
        audit,
        ConfirmationManager(ConfirmationChannel.DENY),
        os_controls=fake_os,
    )
    orch = LocalGuardianOrchestrator(cfg, registry)
    try:
        # 1. Increase brightness 60 -> 80, then undo -> 60
        orch.handle("increase brightness")
        assert fake_os._brightness == 80
        u1 = orch.handle("undo")
        assert u1.route_tier == "undo"
        assert fake_os._brightness == 60
        assert "restored brightness to 60%" in u1.message

        # 2. Set volume 50 -> 25, then undo -> 50
        orch.handle("set volume to 25")
        assert fake_os._volume == 25
        u2 = orch.handle("undo last action")
        assert fake_os._volume == 50
        assert "restored volume to 50%" in u2.message

        # 3. Mute False -> True, then undo -> False
        orch.handle("mute")
        assert fake_os._muted is True
        orch.handle("undo")
        assert fake_os._muted is False

        # 4. Empty stack message
        u4 = orch.handle("undo")
        assert "Nothing to undo" in u4.message
    finally:
        orch.close()
        registry.close()
