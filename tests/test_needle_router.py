"""Tests for Tier-1.5 Cactus Needle router (confidence gating & escalation)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from localguardian.brain.needle_router import CactusNeedleRouter
from localguardian.brain.orchestrator import LocalGuardianOrchestrator
from localguardian.config import load_config
from localguardian.safety.audit import AuditLogger
from localguardian.safety.confirm import ConfirmationChannel, ConfirmationManager
from localguardian.safety.policy import SafetyPolicy
from localguardian.tools.registry import ToolRegistry


class _FakeNeedle:
    def __init__(self, response: Dict[str, Any]) -> None:
        self._response = response

    def complete(self, text: str, max_new_tokens: int = 96) -> Dict[str, Any]:
        return self._response


def test_needle_accepts_high_confidence_call() -> None:
    cfg = load_config()
    cfg.needle.min_confidence = 0.65
    fake = _FakeNeedle(
        {
            "function_calls": [{"name": "set_volume", "arguments": {"level": 40}}],
            "confidence": 0.91,
            "reasoning": "User wants volume at 40%",
            "peak_ram_mb": 131.0,
        }
    )
    router = CactusNeedleRouter(cfg, needle_factory=lambda **_: fake)
    actions, trace = router.route("put volume to 40")
    assert actions is not None and len(actions) == 1
    assert actions[0].tool_name == "set_volume"
    assert actions[0].args == {"level": 40}
    assert actions[0].route_tier == "tier1_5_cactus_needle"
    assert trace["accepted"] is True


def test_needle_rejects_low_confidence_and_escalates() -> None:
    cfg = load_config()
    cfg.needle.min_confidence = 0.65
    fake = _FakeNeedle(
        {
            "function_calls": [{"name": "open_app", "arguments": {"app_name": "Elon Musk"}}],
            "confidence": 0.41,
            "reasoning": "Uncertain match",
        }
    )
    router = CactusNeedleRouter(cfg, needle_factory=lambda **_: fake)
    actions, trace = router.route("pull up Elon Musk")
    assert actions is None
    assert trace["accepted"] is False
    assert trace["confidence"] == 0.41


def test_needle_disabled_returns_none() -> None:
    cfg = load_config()
    cfg.needle.enabled = False
    router = CactusNeedleRouter(cfg)
    actions, trace = router.route("put volume to 40")
    assert actions is None
    assert trace["status"] == "disabled"


def test_orchestrator_routes_through_tier1_5_needle_with_safety_gate(tmp_path: Path) -> None:
    cfg = load_config()
    cfg.safety.dry_run = True
    fake = _FakeNeedle(
        {
            "function_calls": [{"name": "set_volume", "arguments": {"level": 45}}],
            "confidence": 0.88,
        }
    )
    needle = CactusNeedleRouter(cfg, needle_factory=lambda **_: fake)
    policy = SafetyPolicy(cfg)
    audit = AuditLogger(tmp_path / "needle_audit.db")
    registry = ToolRegistry(cfg, policy, audit, ConfirmationManager(ConfirmationChannel.DENY))
    orch = LocalGuardianOrchestrator(cfg, registry, needle=needle)
    try:
        # "put audio at 45" misses Tier-1 regex -> hits Tier-1.5 Cactus Needle!
        res = orch.handle("put audio at 45")
        assert res.route_tier == "tier1_5_cactus_needle"
        assert res.results[0].tool_name == "set_volume"
        assert res.results[0].args == {"level": 45}
        assert res.results[0].status == "dry_run"
    finally:
        registry.close()


def test_safety_policy_still_blocks_forbidden_tool_from_needle(tmp_path: Path) -> None:
    cfg = load_config()
    cfg.safety.dry_run = False
    fake = _FakeNeedle(
        {
            "function_calls": [{"name": "open_app", "arguments": {"app_name": "powershell"}}],
            "confidence": 0.99,
        }
    )
    needle = CactusNeedleRouter(cfg, needle_factory=lambda **_: fake)
    policy = SafetyPolicy(cfg)
    audit = AuditLogger(tmp_path / "needle_block.db")
    registry = ToolRegistry(cfg, policy, audit, ConfirmationManager(ConfirmationChannel.DENY))
    orch = LocalGuardianOrchestrator(cfg, registry, needle=needle)
    try:
        res = orch.handle("please bring up my special shell")
        assert res.route_tier == "tier1_5_cactus_needle"
        assert res.results[0].status == "blocked"
        assert res.results[0].verdict.rule_id == "BLOCKED_SYSTEM_BINARY"
    finally:
        registry.close()
