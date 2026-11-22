"""Unit tests for Tier-1 deterministic fast grammar parser."""

from __future__ import annotations

import pytest

from localguardian.brain.fast_grammar import FastGrammarParser


@pytest.fixture()
def parser() -> FastGrammarParser:
    return FastGrammarParser()


@pytest.mark.parametrize(
    ("utterance", "expected_tool", "expected_args"),
    [
        ("Windows, increase the brightness", "adjust_brightness", {"delta": 20}),
        ("increase brightness by 30", "adjust_brightness", {"delta": 30}),
        ("decrease screen brightness by 15%", "adjust_brightness", {"delta": -15}),
        ("set brightness to 70", "set_brightness", {"level": 70}),
        ("make screen dimmer", "adjust_brightness", {"delta": -20}),
        ("increase volume", "adjust_volume", {"delta": 15}),
        ("set volume to 40%", "set_volume", {"level": 40}),
        ("mute", "toggle_mute", {"mute": True}),
        ("unmute audio", "toggle_mute", {"mute": False}),
        ("go to Chrome and type Elon Musk", "chrome_search", {"query": "Elon Musk"}),
        ("open chrome and search for Python tutorials", "chrome_search", {"query": "Python tutorials"}),
        ("search weather in Kathmandu on chrome", "chrome_search", {"query": "weather in Kathmandu"}),
        ("open github.com in chrome", "chrome_open_url", {"url": "github.com"}),
        ("open chrome", "open_app", {"app_name": "chrome"}),
        ("open notepad", "open_app", {"app_name": "notepad"}),
        ("check system status", "get_system_status", {}),
    ],
)
def test_fast_grammar_matches_expected_tool(
    parser: FastGrammarParser,
    utterance: str,
    expected_tool: str,
    expected_args: dict,
) -> None:
    actions = parser.parse(utterance)
    assert actions is not None and len(actions) == 1
    assert actions[0].tool_name == expected_tool
    assert actions[0].args == expected_args


def test_unsafe_utterances_route_to_policy_for_explicit_block(parser: FastGrammarParser) -> None:
    a1 = parser.parse("run powershell and list files")
    assert a1 is not None and a1[0].tool_name == "run_powershell"

    a2 = parser.parse("delete files in C:\\Windows\\System32")
    assert a2 is not None and a2[0].tool_name == "write_user_file"
    assert "Windows" in a2[0].args["path"]

    a3 = parser.parse("modify C:\\Program Files")
    assert a3 is not None and a3[0].tool_name == "write_user_file"
    assert "Program Files" in a3[0].args["path"]


def test_complex_natural_phrase_escalates_to_tier2(parser: FastGrammarParser) -> None:
    assert parser.parse("it feels way too dark in this room, help me out") is None
