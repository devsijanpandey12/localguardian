"""Tier-1 deterministic fast grammar parser (CPU, <1 ms, zero VRAM).

Handles common direct voice/text commands immediately without waking the GPU LLM:
- "Windows, increase the brightness" / "set brightness to 70"
- "decrease volume by 15" / "mute" / "unmute"
- "go to Chrome and type Elon Musk" / "open Chrome and search Elon Musk"
- "open youtube.com in Chrome" / "open Chrome" / "open notepad"
- "check system status" / "check battery"
- Adversarial unsafe phrases (e.g., "delete C:\\Windows", "run powershell") ->
  mapped cleanly into forbidden tool calls so SafetyPolicy blocks and audits them.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PlannedAction(BaseModel):
    tool_name: str
    args: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 0.95
    route_tier: str = "tier1_grammar"


_WAKE_PREFIX = re.compile(
    r"^(?:(?:hey|ok|okay|hi)\s+)?(?:windows|local\s*guardian|guardian|computer|jarvis)[,\s:]+",
    re.IGNORECASE,
)

_POLITE_PREFIX = re.compile(
    r"^(?:please|can\s+you|could\s+you|would\s+you|just)\s+",
    re.IGNORECASE,
)

# Matches explicit unsafe/adversarial intent so SafetyPolicy can deterministically block & log it
_UNSAFE_SHELL_RE = re.compile(
    r"\b(?:run|open|launch|execute|start)\s+(?:powershell|pwsh|cmd|command\s+prompt|terminal|regedit|diskpart)\b",
    re.IGNORECASE,
)
_UNSAFE_SYSFILE_RE = re.compile(
    r"\b(?:delete|remove|edit|modify|wipe|corrupt|overwrite|touch|write)\b.*?(c:\\windows|c:/windows|program\s*files|system32|registry|hklm|hkcu)",
    re.IGNORECASE,
)


def _strip_prefixes(text: str) -> str:
    cleaned = text.strip().rstrip(".!?")
    for _ in range(3):
        updated = _WAKE_PREFIX.sub("", cleaned).strip()
        updated = _POLITE_PREFIX.sub("", updated).strip()
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned


class FastGrammarParser:
    """Zero-latency deterministic command matcher for single-step Windows & Chrome tasks."""

    def parse(self, raw_text: str) -> Optional[List[PlannedAction]]:
        text = _strip_prefixes(raw_text)
        if not text:
            return None

        # 0. Adversarial safety catches -> explicitly route into SafetyPolicy so rule_id is logged
        if _UNSAFE_SHELL_RE.search(text):
            return [
                PlannedAction(
                    tool_name="run_powershell",
                    args={"command": text},
                    confidence=1.0,
                )
            ]

        m_sys = _UNSAFE_SYSFILE_RE.search(text)
        if m_sys:
            target_hint = m_sys.group(1).lower()
            if "program" in target_hint:
                path = r"C:\Program Files"
            elif "reg" in target_hint or "hk" in target_hint:
                path = r"HKLM\SOFTWARE\Microsoft\Windows"
            else:
                path = r"C:\Windows\System32"
            return [
                PlannedAction(
                    tool_name="write_user_file",
                    args={"path": path, "content": ""},
                    confidence=1.0,
                )
            ]

        # 1. Chrome search / type in Chrome (Priority #1 browser!)
        # Examples:
        #   "go to chrome and type elon musk"
        #   "open chrome and search for elon musk"
        #   "search elon musk on chrome"
        #   "google elon musk"
        m = re.match(
            r"^(?:go\s+to|open|launch|in|on)\s+(?:google\s+)?chrome\s+(?:and\s+)?(?:type|search(?:\s+for)?|look\s+up|google|find)\s+(.+)$",
            text,
            re.IGNORECASE,
        )
        if m:
            query = m.group(1).strip().strip("\"'")
            if query:
                return [PlannedAction(tool_name="chrome_search", args={"query": query})]

        m = re.match(
            r"^(?:search(?:\s+the\s+web)?(?:\s+for)?|google|look\s+up)\s+(.+?)(?:\s+(?:in|on)\s+(?:google\s+)?chrome)?$",
            text,
            re.IGNORECASE,
        )
        if m:
            query = m.group(1).strip().strip("\"'")
            if query:
                return [PlannedAction(tool_name="chrome_search", args={"query": query})]

        # 2. Chrome open URL
        # Examples: "open youtube.com in chrome", "go to chrome and open github.com", "go to github.com"
        m = re.match(
            r"^(?:(?:go\s+to|open)\s+(?:google\s+)?chrome\s+(?:and\s+)?)?(?:open|go\s+to|visit|navigate\s+to)\s+((?:https?://|file://|chrome://|javascript:)?[\w.-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?|file://[^\s]+|chrome://[^\s]+|javascript:[^\s]+)(?:\s+in\s+(?:google\s+)?chrome)?$",
            text,
            re.IGNORECASE,
        )
        if m:
            url = m.group(1).strip()
            return [PlannedAction(tool_name="chrome_open_url", args={"url": url})]

        # 3. Brightness controls
        m = re.match(
            r"^(?:set|change)\s+(?:the\s+)?(?:screen\s+)?brightness\s+(?:to\s+)?(\d{1,3})\s*%?$",
            text,
            re.IGNORECASE,
        )
        if m:
            return [PlannedAction(tool_name="set_brightness", args={"level": int(m.group(1))})]

        m = re.match(
            r"^(?:increase|raise|turn\s+up|boost|brighten)\s+(?:the\s+)?(?:screen\s+)?brightness(?:\s+by\s+(\d{1,3})\s*%?)?$",
            text,
            re.IGNORECASE,
        )
        if m:
            delta = int(m.group(1)) if m.group(1) else 20
            return [PlannedAction(tool_name="adjust_brightness", args={"delta": delta})]

        m = re.match(
            r"^(?:decrease|lower|reduce|turn\s+down|dim)\s+(?:the\s+)?(?:screen\s+)?brightness(?:\s+by\s+(\d{1,3})\s*%?)?$",
            text,
            re.IGNORECASE,
        )
        if m:
            delta = int(m.group(1)) if m.group(1) else 20
            return [PlannedAction(tool_name="adjust_brightness", args={"delta": -delta})]

        if re.match(r"^(?:make\s+(?:the\s+)?screen\s+)?brighter$", text, re.IGNORECASE):
            return [PlannedAction(tool_name="adjust_brightness", args={"delta": 20})]
        if re.match(r"^(?:make\s+(?:the\s+)?screen\s+)?(?:dimmer|darker)$", text, re.IGNORECASE):
            return [PlannedAction(tool_name="adjust_brightness", args={"delta": -20})]
        if re.match(r"^(?:what(?:'s|\s+is)\s+(?:the\s+)?|check\s+|get\s+)brightness$", text, re.IGNORECASE):
            return [PlannedAction(tool_name="get_brightness", args={})]

        # 4. Volume & mute controls
        m = re.match(
            r"^(?:set|change)\s+(?:the\s+)?(?:system\s+|audio\s+)?volume\s+(?:to\s+)?(\d{1,3})\s*%?$",
            text,
            re.IGNORECASE,
        )
        if m:
            return [PlannedAction(tool_name="set_volume", args={"level": int(m.group(1))})]

        m = re.match(
            r"^(?:increase|raise|turn\s+up|boost)\s+(?:the\s+)?(?:system\s+|audio\s+)?volume(?:\s+by\s+(\d{1,3})\s*%?)?$",
            text,
            re.IGNORECASE,
        )
        if m:
            delta = int(m.group(1)) if m.group(1) else 15
            return [PlannedAction(tool_name="adjust_volume", args={"delta": delta})]

        m = re.match(
            r"^(?:decrease|lower|reduce|turn\s+down)\s+(?:the\s+)?(?:system\s+|audio\s+)?volume(?:\s+by\s+(\d{1,3})\s*%?)?$",
            text,
            re.IGNORECASE,
        )
        if m:
            delta = int(m.group(1)) if m.group(1) else 15
            return [PlannedAction(tool_name="adjust_volume", args={"delta": -delta})]

        if re.match(r"^volume\s+up$", text, re.IGNORECASE):
            return [PlannedAction(tool_name="adjust_volume", args={"delta": 15})]
        if re.match(r"^volume\s+down$", text, re.IGNORECASE):
            return [PlannedAction(tool_name="adjust_volume", args={"delta": -15})]
        if re.match(r"^(?:mute(?:\s+(?:the\s+)?(?:audio|sound|volume))?)$", text, re.IGNORECASE):
            return [PlannedAction(tool_name="toggle_mute", args={"mute": True})]
        if re.match(r"^(?:unmute(?:\s+(?:the\s+)?(?:audio|sound|volume))?)$", text, re.IGNORECASE):
            return [PlannedAction(tool_name="toggle_mute", args={"mute": False})]
        if re.match(r"^(?:what(?:'s|\s+is)\s+(?:the\s+)?|check\s+|get\s+)volume$", text, re.IGNORECASE):
            return [PlannedAction(tool_name="get_volume", args={})]

        # 5. Media playback controls
        if re.match(
            r"^(?:pause|play|resume|toggle)\s*(?:the\s+)?(?:music|media|song|video|playback)?$",
            text,
            re.IGNORECASE,
        ):
            return [PlannedAction(tool_name="media_control", args={"action": "play_pause"})]
        if re.match(
            r"^(?:next|skip(?:\s+to)?\s+(?:the\s+)?next)\s+(?:track|song|video)$",
            text,
            re.IGNORECASE,
        ):
            return [PlannedAction(tool_name="media_control", args={"action": "next"})]
        if re.match(
            r"^(?:previous|prev|last)\s+(?:track|song|video)$",
            text,
            re.IGNORECASE,
        ):
            return [PlannedAction(tool_name="media_control", args={"action": "previous"})]

        # 6. Window management (list / focus / snap)
        if re.match(
            r"^(?:list|show|what\s+are)\s+(?:the\s+)?(?:open\s+)?windows$",
            text,
            re.IGNORECASE,
        ):
            return [PlannedAction(tool_name="list_open_windows", args={})]

        m = re.match(
            r"^(?:snap|put|move)\s+(.+?)\s+(?:(?:to|on)\s+(?:the\s+)?)?(left|right)(?:\s+half|\s+side)?$",
            text,
            re.IGNORECASE,
        )
        if m:
            return [
                PlannedAction(
                    tool_name="snap_window",
                    args={"window_name": m.group(1).strip(), "position": m.group(2).lower()},
                )
            ]

        m = re.match(r"^(maximize|minimize)\s+(.+)$", text, re.IGNORECASE)
        if m:
            return [
                PlannedAction(
                    tool_name="snap_window",
                    args={"window_name": m.group(2).strip(), "position": m.group(1).lower()},
                )
            ]

        m = re.match(r"^(?:focus|switch\s+to)\s+(.+?)(?:\s+window)?$", text, re.IGNORECASE)
        if m:
            target = m.group(1).strip()
            mode_match = re.match(r"^(coding|study|focus|relax)\s+mode$", target, re.IGNORECASE)
            if mode_match:
                return [
                    PlannedAction(
                        tool_name="activate_workspace_mode",
                        args={"mode": mode_match.group(1).lower()},
                    )
                ]
            return [PlannedAction(tool_name="focus_window", args={"window_name": target})]

        # 7. Workspace modes ("activate study mode", "coding mode")
        m = re.match(
            r"^(?:(?:activate|enable|start|enter)\s+)?(coding|study|focus|relax)\s+mode$",
            text,
            re.IGNORECASE,
        )
        if m:
            return [
                PlannedAction(
                    tool_name="activate_workspace_mode",
                    args={"mode": m.group(1).lower()},
                )
            ]

        # 8. Sandboxed screenshot
        m = re.match(
            r"^(?:take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?screen)(?:\s+(?:as|named)\s+(.+))?$",
            text,
            re.IGNORECASE,
        )
        if m:
            args: Dict[str, Any] = {}
            if m.group(1):
                args["filename"] = m.group(1).strip().strip("\"'")
            return [PlannedAction(tool_name="take_screenshot", args=args)]

        # 9. Read-only system status / battery / GPU / CPU
        if re.match(
            r"^(?:check|get|show)\s+(?:the\s+)?(?:system\s+status|battery(?:\s+status)?|pc\s+status|gpu(?:\s+temp(?:erature)?)?|cpu|ram)$",
            text,
            re.IGNORECASE,
        ):
            return [PlannedAction(tool_name="get_system_status", args={})]

        # 10. Open allowlisted apps (e.g. "open chrome", "open notepad", "launch calculator")
        m = re.match(
            r"^(?:open|launch|start|go\s+to)\s+(?:google\s+)?([a-zA-Z0-9._-]+)$",
            text,
            re.IGNORECASE,
        )
        if m:
            app_name = m.group(1).strip().lower()
            if app_name == "calc":
                app_name = "calculator"
            if app_name == "code":
                app_name = "vscode"
            return [PlannedAction(tool_name="open_app", args={"app_name": app_name})]

        return None
