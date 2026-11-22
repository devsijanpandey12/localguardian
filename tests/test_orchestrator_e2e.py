"""End-to-end prototype tests: Orchestrator -> SafetyPolicy -> Dry-Run Tools -> SQLite Audit."""

from __future__ import annotations

from pathlib import Path

from localguardian.brain.orchestrator import LocalGuardianOrchestrator
from localguardian.config import load_config
from localguardian.safety.audit import AuditLogger
from localguardian.safety.confirm import ConfirmationChannel, ConfirmationManager
from localguardian.safety.policy import RiskLevel, SafetyPolicy
from localguardian.tools.registry import ToolRegistry


def _make_orchestrator(tmp_path: Path, dry_run: bool = True):
    cfg = load_config()
    cfg.safety.dry_run = dry_run
    policy = SafetyPolicy(cfg)
    audit = AuditLogger(tmp_path / "test_audit.db")
    confirm = ConfirmationManager(ConfirmationChannel.DENY)
    registry = ToolRegistry(cfg, policy, audit, confirm)
    orch = LocalGuardianOrchestrator(cfg, registry)
    return orch, audit, registry


def test_e2e_brightness_and_chrome_dry_run(tmp_path: Path) -> None:
    orch, audit, registry = _make_orchestrator(tmp_path, dry_run=True)
    try:
        r1 = orch.handle("Windows, increase the brightness")
        assert r1.route_tier == "tier1_grammar"
        assert len(r1.results) == 1
        assert r1.results[0].status == "dry_run"
        assert r1.results[0].tool_name == "adjust_brightness"
        assert r1.results[0].args == {"delta": 20}

        r2 = orch.handle("go to Chrome and type Elon Musk")
        assert r2.route_tier == "tier1_grammar"
        assert len(r2.results) == 1
        assert r2.results[0].status == "dry_run"
        assert r2.results[0].tool_name == "chrome_search"
        assert r2.results[0].args == {"query": "Elon Musk"}

        entries = audit.recent(limit=10)
        assert len(entries) == 2
        assert entries[0].tool_name == "chrome_search"
        assert entries[1].tool_name == "adjust_brightness"
    finally:
        registry.close()


def test_e2e_adversarial_commands_are_hard_blocked_and_audited(tmp_path: Path) -> None:
    orch, audit, registry = _make_orchestrator(tmp_path, dry_run=False)
    try:
        r1 = orch.handle("delete files in C:\\Windows\\System32")
        assert r1.results[0].status == "blocked"
        assert r1.results[0].verdict.risk == RiskLevel.FORBIDDEN
        assert r1.results[0].verdict.rule_id == "BLOCKED_PROTECTED_SYSTEM_PATH"

        r2 = orch.handle("run powershell")
        assert r2.results[0].status == "blocked"
        assert r2.results[0].verdict.rule_id == "BLOCKED_FORBIDDEN_TOOL"

        r3 = orch.handle("open file:///C:/Windows/win.ini in chrome")
        assert r3.results[0].status == "blocked"
        assert r3.results[0].verdict.rule_id == "BLOCKED_URL_SCHEME"

        entries = audit.recent(limit=10)
        assert len(entries) == 3
        assert all(not e.allowed for e in entries)
    finally:
        registry.close()


def test_openai_tool_schemas_never_expose_shell_tools(tmp_path: Path) -> None:
    _orch, _audit, registry = _make_orchestrator(tmp_path, dry_run=True)
    try:
        names = {t["function"]["name"] for t in registry.openai_tool_schemas()}
        assert "adjust_brightness" in names
        assert "chrome_search" in names
        assert "run_powershell" not in names
        assert "run_command" not in names
    finally:
        registry.close()
