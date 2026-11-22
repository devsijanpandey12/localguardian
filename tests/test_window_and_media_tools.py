"""Tests for window management, media controls, screenshots, and workspace modes."""

from __future__ import annotations

import pytest

from localguardian.brain.fast_grammar import FastGrammarParser
from localguardian.config import load_config
from localguardian.safety.policy import RiskLevel, SafetyPolicy


@pytest.fixture()
def policy() -> SafetyPolicy:
    return SafetyPolicy(load_config())


@pytest.fixture()
def parser() -> FastGrammarParser:
    return FastGrammarParser()


@pytest.mark.parametrize(
    ("utterance", "expected_tool", "expected_args"),
    [
        ("pause music", "media_control", {"action": "play_pause"}),
        ("next track", "media_control", {"action": "next"}),
        ("previous song", "media_control", {"action": "previous"}),
        ("list open windows", "list_open_windows", {}),
        ("put chrome on the left", "snap_window", {"window_name": "chrome", "position": "left"}),
        ("snap notepad right", "snap_window", {"window_name": "notepad", "position": "right"}),
        ("maximize chrome", "snap_window", {"window_name": "chrome", "position": "maximize"}),
        ("focus chrome", "focus_window", {"window_name": "chrome"}),
        ("switch to study mode", "activate_workspace_mode", {"mode": "study"}),
        ("coding mode", "activate_workspace_mode", {"mode": "coding"}),
        ("take a screenshot", "take_screenshot", {}),
        ("take screenshot named demo.png", "take_screenshot", {"filename": "demo.png"}),
    ],
)
def test_fast_grammar_new_tools(
    parser: FastGrammarParser,
    utterance: str,
    expected_tool: str,
    expected_args: dict,
) -> None:
    actions = parser.parse(utterance)
    assert actions is not None and len(actions) == 1
    assert actions[0].tool_name == expected_tool
    assert actions[0].args == expected_args


def test_screenshot_policy_blocks_path_traversal_and_executables(policy: SafetyPolicy) -> None:
    for bad in (r"..\..\Windows\evil.png", r"C:\Windows\a.png", "sub/a.png", "evil.exe", "script.ps1"):
        v = policy.evaluate("take_screenshot", {"filename": bad})
        assert not v.allowed
        assert v.risk == RiskLevel.FORBIDDEN

    ok = policy.evaluate("take_screenshot", {"filename": "demo_01.png"})
    assert ok.allowed
    assert ok.risk == RiskLevel.SAFE


def test_media_snap_and_workspace_validation(policy: SafetyPolicy) -> None:
    assert policy.evaluate("media_control", {"action": "play_pause"}).allowed
    assert not policy.evaluate("media_control", {"action": "delete_all"}).allowed

    assert policy.evaluate("snap_window", {"window_name": "chrome", "position": "left"}).allowed
    assert not policy.evaluate("snap_window", {"window_name": "chrome", "position": "kill"}).allowed

    assert policy.evaluate("activate_workspace_mode", {"mode": "coding"}).allowed
    assert not policy.evaluate("activate_workspace_mode", {"mode": "admin_mode"}).allowed
