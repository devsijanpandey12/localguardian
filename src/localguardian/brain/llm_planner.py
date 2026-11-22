"""Tier-2 Local LLM Planner (Ollama OpenAI-compatible API + resilient JSON repair).

Designed for small local models (Qwen3 4B/8B, Qwen2.5 7B, Gemma 4) running on
http://127.0.0.1:11434/v1. Strips `<think>...</think>` blocks and repairs common
small-model JSON formatting quirks.
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

from localguardian.brain.fast_grammar import PlannedAction
from localguardian.config import LocalGuardianConfig


SYSTEM_PROMPT = """You are LocalGuardian, a safe local Windows desktop assistant.
Your ONLY job is to map the user's request to one or more of the provided typed tools.
Rules:
1. Always prioritize Google Chrome tools (chrome_search, chrome_open_url) for any web/browser request.
2. NEVER attempt to run shell commands, PowerShell, cmd, Registry edits, or touch C:\\Windows or C:\\Program Files.
3. If the user asks something unsafe or unsupported, return no tool calls and briefly explain why.
4. Keep tool arguments minimal, exact, and strictly matching the tool schemas.
"""

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)


def repair_and_parse_json(raw_text: str) -> Optional[Any]:
    """Multi-stage resilient JSON extractor/repairer for small local LLMs."""
    cleaned = _THINK_BLOCK_RE.sub("", raw_text).strip()
    if not cleaned:
        return None

    # Stage 1: Prefer fenced JSON blocks if present
    fenced = _FENCE_RE.findall(cleaned)
    candidates = [block.strip() for block in fenced if block.strip()] + [cleaned]

    for candidate in candidates:
        # Stage 2: Direct parse
        try:
            return json.loads(candidate)
        except Exception:
            pass

        # Stage 3: Extract outermost [ ... ] or { ... }
        extracted = _extract_bracket_block(candidate)
        if extracted:
            for attempt in (extracted, _repair_json_syntax(extracted)):
                try:
                    return json.loads(attempt)
                except Exception:
                    pass
            try:
                val = ast.literal_eval(extracted)
                if isinstance(val, (dict, list)):
                    return val
            except Exception:
                pass

    return None


def _extract_bracket_block(text: str) -> Optional[str]:
    start_idx = None
    open_ch = ""
    close_ch = ""
    for i, ch in enumerate(text):
        if ch in "[{":
            start_idx = i
            open_ch = ch
            close_ch = "]" if ch == "[" else "}"
            break
    if start_idx is None:
        return None

    depth = 0
    in_str = False
    quote_ch = ""
    escape = False
    for i in range(start_idx, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\" and in_str:
            escape = True
            continue
        if in_str:
            if ch == quote_ch:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            quote_ch = ch
            continue
        if ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                return text[start_idx : i + 1]
    return None


def _repair_json_syntax(raw: str) -> str:
    s = re.sub(r",\s*([}\]])", r"\1", raw)  # trailing commas
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)
    return s


def _normalize_parsed_calls(parsed: Any) -> List[PlannedAction]:
    if isinstance(parsed, dict):
        if "tool_calls" in parsed and isinstance(parsed["tool_calls"], list):
            items = parsed["tool_calls"]
        elif "actions" in parsed and isinstance(parsed["actions"], list):
            items = parsed["actions"]
        elif "steps" in parsed and isinstance(parsed["steps"], list):
            items = parsed["steps"]
        else:
            items = [parsed]
    elif isinstance(parsed, list):
        items = parsed
    else:
        return []

    actions: List[PlannedAction] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("tool") or item.get("tool_name")
        if not name and isinstance(item.get("function"), dict):
            name = item["function"].get("name")
            args = item["function"].get("arguments", {})
        else:
            args = item.get("arguments") or item.get("args") or {}

        if isinstance(args, str):
            repaired = repair_and_parse_json(args)
            args = repaired if isinstance(repaired, dict) else {}

        if isinstance(name, str) and name.strip() and isinstance(args, dict):
            actions.append(
                PlannedAction(
                    tool_name=name.strip(),
                    args=args,
                    confidence=0.85,
                    route_tier="tier2_ollama",
                )
            )
    return actions


class LocalLLMPlanner:
    """Calls local Ollama OpenAI-compatible endpoint with native tool calling."""

    def __init__(self, config: LocalGuardianConfig) -> None:
        self.config = config

    def health_check(self) -> Tuple[bool, List[str], str]:
        """Check whether local Ollama server is reachable and list pulled models."""
        base = self.config.llm.base_url.rstrip("/")
        # Ollama native tags endpoint sits at root /api/tags
        root = base[:-3] if base.endswith("/v1") else base
        try:
            with httpx.Client(timeout=3.0) as client:
                resp = client.get(f"{root}/api/tags")
                resp.raise_for_status()
                data = resp.json()
                models = [m.get("name", "") for m in data.get("models", []) if m.get("name")]
                return True, models, f"Ollama online at {root} ({len(models)} model(s))."
        except Exception as exc:
            return False, [], f"Ollama unreachable at {root}: {exc}"

    def plan(
        self,
        user_text: str,
        tool_schemas: List[Dict[str, Any]],
    ) -> Tuple[List[PlannedAction], str]:
        """Ask local Ollama model for structured tool calls.

        Returns `(actions, assistant_reply_or_error)`.
        """
        url = f"{self.config.llm.base_url.rstrip('/')}/chat/completions"
        payload: Dict[str, Any] = {
            "model": self.config.llm.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            "tools": tool_schemas,
            "tool_choice": "auto",
        }

        try:
            with httpx.Client(timeout=self.config.llm.timeout_seconds) as client:
                resp = client.post(url, json=payload)
                resp.raise_for_status()
                body = resp.json()
        except httpx.ConnectError:
            return (
                [],
                (
                    f"Local LLM server ({self.config.llm.base_url}) is not running. "
                    f"Start Ollama and pull '{self.config.llm.model}' for natural/multi-step commands, "
                    "or use direct commands handled by Tier-1 fast grammar."
                ),
            )
        except Exception as exc:
            return [], f"Local LLM error: {exc}"

        return self.parse_completion_response(body)

    def parse_completion_response(self, body: Dict[str, Any]) -> Tuple[List[PlannedAction], str]:
        """Extract tool calls from an OpenAI-compatible response, with JSON repair fallback."""
        choices = body.get("choices") or []
        if not choices:
            return [], "Local LLM returned an empty response."

        message = choices[0].get("message") or {}
        raw_content = str(message.get("content") or "")
        clean_reply = _THINK_BLOCK_RE.sub("", raw_content).strip()

        # 1. Native structured tool_calls
        native_calls = message.get("tool_calls") or []
        actions: List[PlannedAction] = []
        for call in native_calls:
            fn = call.get("function") or {}
            name = fn.get("name")
            raw_args = fn.get("arguments", {})
            if isinstance(raw_args, str):
                parsed_args = repair_and_parse_json(raw_args)
                args = parsed_args if isinstance(parsed_args, dict) else {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            if name:
                actions.append(
                    PlannedAction(
                        tool_name=str(name),
                        args=args,
                        confidence=0.9,
                        route_tier="tier2_ollama",
                    )
                )

        if actions:
            return actions, clean_reply

        # 2. Fallback: repair JSON embedded in text output (common in smaller 3B-4B models)
        parsed = repair_and_parse_json(clean_reply)
        if parsed is not None:
            repaired_actions = _normalize_parsed_calls(parsed)
            if repaired_actions:
                return repaired_actions, ""

        return [], clean_reply or "No actionable tool call produced."
