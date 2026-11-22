"""Tests for Tier-2 Ollama local LLM response parsing & JSON repair."""

from __future__ import annotations

from localguardian.brain.llm_planner import LocalLLMPlanner, repair_and_parse_json
from localguardian.config import load_config


def test_repairs_qwen3_think_block_and_trailing_comma() -> None:
    raw = """<think>The user wants to raise brightness.</think>
```json
{"name": "adjust_brightness", "arguments": {"delta": 20,},}
```
"""
    parsed = repair_and_parse_json(raw)
    assert parsed == {"name": "adjust_brightness", "arguments": {"delta": 20}}


def test_parses_native_openai_tool_calls() -> None:
    planner = LocalLLMPlanner(load_config())
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_1",
                            "type": "function",
                            "function": {
                                "name": "chrome_search",
                                "arguments": '{"query": "Elon Musk"}',
                            },
                        }
                    ],
                }
            }
        ]
    }
    actions, _reply = planner.parse_completion_response(body)
    assert len(actions) == 1
    assert actions[0].tool_name == "chrome_search"
    assert actions[0].args == {"query": "Elon Musk"}
    assert actions[0].route_tier == "tier2_ollama"


def test_parses_fallback_json_inside_content() -> None:
    planner = LocalLLMPlanner(load_config())
    body = {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": '<think>open chrome</think>[{"tool": "chrome_search", "args": {"query": "Elon Musk"}}]',
                }
            }
        ]
    }
    actions, _reply = planner.parse_completion_response(body)
    assert len(actions) == 1
    assert actions[0].tool_name == "chrome_search"
    assert actions[0].args == {"query": "Elon Musk"}
