"""Tier-1 deterministic fast grammar parser, pre-flight guard, and typo normalizer (CPU, <1 ms).

Upgrades in v0.3.0:
- Pre-flight input guard (`check_preflight`): instantly handles `help`, `undo`,
  greetings/small-talk, and obvious keyboard mash/gibberish in <1 ms instead of
  wasting 5-25s escalating nonsense to Cactus Needle and Ollama Qwen3.
- Conservative typo normalizer (`normalize_typos`): fixes common command/app
  misspellings ("open chorme", "incrase brigtness", "volum down") in <1 ms
  without altering search queries.
- Smart command suggestions (`suggest_examples`) for unrecognized input.
"""

from __future__ import annotations

import difflib
import re
from typing import Any, Dict, List, Optional, Tuple

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

HELP_TEXT = """Available LocalGuardian Commands:
  Display  : increase/decrease brightness [by N] | set brightness to 70 | check brightness
  Audio    : increase/decrease volume [by N] | set volume to 40 | mute | unmute
  Media    : pause music | next track | previous song
  Chrome   : go to Chrome and type <query> | search <query> | open <site.com> in chrome
  Apps     : open chrome | open notepad | open calculator | open paint | open vscode
  Windows  : list open windows | put chrome on the left | maximize chrome | focus notepad
  Extras   : take a screenshot | switch to coding/study/focus/relax mode | check system status
  Session  : undo | help | models | audit | dry-run on/off | exit"""

EXAMPLE_COMMANDS: Tuple[str, ...] = (
    "increase the brightness",
    "decrease the brightness",
    "set brightness to 70",
    "increase volume",
    "decrease volume",
    "set volume to 40",
    "mute",
    "unmute",
    "pause music",
    "next track",
    "go to Chrome and type Elon Musk",
    "open github.com in chrome",
    "open chrome",
    "open notepad",
    "open calculator",
    "list open windows",
    "put chrome on the left",
    "maximize chrome",
    "take a screenshot",
    "switch to study mode",
    "check system status",
    "undo",
    "help",
)

# Strictly curated command/app keywords eligible for conservative typo repair.
_COMMAND_VOCAB: Tuple[str, ...] = (
    "brightness",
    "brighter",
    "dimmer",
    "increase",
    "decrease",
    "volume",
    "mute",
    "unmute",
    "chrome",
    "notepad",
    "calculator",
    "vscode",
    "spotify",
    "search",
    "google",
    "screenshot",
    "windows",
    "maximize",
    "minimize",
    "pause",
    "resume",
    "previous",
    "status",
    "battery",
    "coding",
    "study",
    "focus",
    "relax",
    "launch",
    "open",
)

_TYPO_OVERRIDES: Dict[str, str] = {
    "chorme": "chrome",
    "crome": "chrome",
    "chrom": "chrome",
    "brigtness": "brightness",
    "brightnes": "brightness",
    "britness": "brightness",
    "incrase": "increase",
    "increse": "increase",
    "decrase": "decrease",
    "decrese": "decrease",
    "volum": "volume",
    "voluem": "volume",
    "volme": "volume",
    "opne": "open",
    "opn": "open",
    "notpad": "notepad",
    "notepd": "notepad",
    "puse": "pause",
    "serch": "search",
    "screnshot": "screenshot",
    "screensht": "screenshot",
    "windws": "windows",
}

_SMALL_TALK_RE = re.compile(
    r"^(?:hi|hello|hey|yo|sup|good\s+(?:morning|afternoon|evening)|"
    r"thanks|thank\s+you|thx|ok|okay|cool|nice|great|awesome|bye|goodbye|test|testing)$",
    re.IGNORECASE,
)

_HELP_RE = re.compile(
    r"^(?:help|\?|commands|list\s+commands|what\s+can\s+you\s+do|show\s+help)$",
    re.IGNORECASE,
)

_UNDO_RE = re.compile(
    r"^(?:undo(?:\s+(?:that|last(?:\s+action)?))?|revert(?:\s+last(?:\s+action)?)?)$",
    re.IGNORECASE,
)

_QUERY_STOP_WORDS = frozenset({"search", "type", "google", "find", "named", "as"})
_VOWELS = frozenset("aeiouy")


def _strip_prefixes(text: str) -> str:
    cleaned = text.strip().rstrip(".!?")
    for _ in range(3):
        updated = _WAKE_PREFIX.sub("", cleaned).strip()
        updated = _POLITE_PREFIX.sub("", updated).strip()
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned


def _looks_like_gibberish(text: str) -> bool:
    """Detect obvious keyboard mash or non-command noise so we fail fast in <1 ms."""
    stripped = text.strip()
    if not stripped:
        return True

    letters = [ch for ch in stripped.lower() if ch.isalpha()]
    if len(letters) < 2:
        return True

    # Single repeated character like "aaaaaa" or "zzzz"
    if len(set(letters)) == 1 and len(letters) >= 2:
        return True

    tokens = re.findall(r"[a-zA-Z]+", stripped.lower())
    if not tokens:
        return True

    # Don't flag URLs, paths, or known short commands
    if "." in stripped or "\\" in stripped or "/" in stripped:
        return False

    # Single-word keyboard mash: >=6 letters with almost no vowels (e.g. "asdfghjkl", "zxcvbn")
    # or obvious QWERTY home-row mash
    if len(tokens) == 1:
        tok = tokens[0]
        if tok in {"asdf", "asdfg", "asdfgh", "asdfghj", "asdfghjk", "asdfghjkl", "qwerty", "qwert", "zxcv", "zxcvb", "zxcvbn", "hjkl", "jkl"}:
            return True
        vowel_count = sum(1 for c in tok if c in _VOWELS)
        if len(tok) >= 6 and vowel_count == 0:
            return True
        if len(tok) >= 8 and (vowel_count / len(tok)) < 0.15:
            return True

    return False


def normalize_typos(text: str) -> str:
    """Conservatively fix obvious typos in command/app keywords without touching search queries."""
    words = text.split()
    out: List[str] = []
    freeze_rest = False

    for w in words:
        if freeze_rest:
            out.append(w)
            continue

        # Preserve URLs, file paths, flags, and numbers untouched
        if any(ch in w for ch in (".", "\\", "/", ":", "@", "0", "1", "2", "3", "4", "5", "6", "7", "8", "9")):
            out.append(w)
            continue

        low = w.lower()
        fixed = _TYPO_OVERRIDES.get(low)
        if fixed is None and len(low) >= 4 and low not in _COMMAND_VOCAB:
            # Never distort real short words or distant words (high 0.80 cutoff)
            matches = difflib.get_close_matches(low, _COMMAND_VOCAB, n=1, cutoff=0.80)
            if matches and matches[0][0] == low[0]:
                fixed = matches[0]

        chosen = fixed if fixed is not None else w
        out.append(chosen)
        if chosen.lower() in _QUERY_STOP_WORDS:
            freeze_rest = True

    return " ".join(out)


def suggest_examples(user_text: str, limit: int = 3) -> List[str]:
    """Return the closest valid example commands for helpful unrecognized-command feedback."""
    cleaned = _strip_prefixes(user_text).lower()
    if not cleaned:
        return list(EXAMPLE_COMMANDS[:limit])
    matches = difflib.get_close_matches(cleaned, EXAMPLE_COMMANDS, n=limit, cutoff=0.35)
    if matches:
        return matches
    # Keyword overlap fallback
    words = set(re.findall(r"[a-z]+", cleaned))
    scored = []
    for ex in EXAMPLE_COMMANDS:
        overlap = len(words & set(re.findall(r"[a-z]+", ex.lower())))
        if overlap > 0:
            scored.append((overlap, ex))
    scored.sort(reverse=True)
    if scored:
        return [ex for _, ex in scored[:limit]]
    return [
        "increase the brightness",
        "go to Chrome and type Elon Musk",
        "check system status",
    ]


def check_preflight(raw_text: str) -> Optional[Tuple[str, str]]:
    """Instant (<1 ms) guard for help, undo, small talk, and obvious gibberish.

    Returns `(kind, message)` where kind is one of:
    - `"help"`
    - `"undo"`
    - `"small_talk"`
    - `"invalid_input"`
    or `None` if the input should proceed to the command cascade.
    """
    stripped = raw_text.strip()
    if not stripped:
        return ("invalid_input", "Empty instruction. Type 'help' to see available commands.")

    text = _strip_prefixes(stripped)
    if not text:
        # Only treat as polite wake greeting if actual letters existed (e.g. "hey windows")
        if any(ch.isalpha() for ch in stripped):
            return (
                "small_talk",
                "Listening! Try saying 'increase the brightness', 'go to Chrome and type Elon Musk', or 'help'.",
            )
        suggestions = " | ".join(f"'{s}'" for s in suggest_examples(stripped))
        return (
            "invalid_input",
            f"Unrecognized command {raw_text.strip()!r}. Try: {suggestions} (or type 'help').",
        )

    if _HELP_RE.match(text):
        return ("help", HELP_TEXT)

    if _UNDO_RE.match(text):
        return ("undo", "")

    if _SMALL_TALK_RE.match(text):
        return (
            "small_talk",
            "Ready to help! Try a command like 'increase the brightness', 'go to Chrome and type Elon Musk', or type 'help'.",
        )

    if _looks_like_gibberish(text):
        suggestions = " | ".join(f"'{s}'" for s in suggest_examples(text))
        return (
            "invalid_input",
            f"Unrecognized command {raw_text.strip()!r}. Try: {suggestions} (or type 'help').",
        )

    return None


class FastGrammarParser:
    """Zero-latency deterministic command matcher for single-step Windows & Chrome tasks."""

    def parse(self, raw_text: str) -> Optional[List[PlannedAction]]:
        text = _strip_prefixes(raw_text)
        if not text:
            return None

        # Conservatively repair known command/app typos first (preserves search queries & paths)
        normalized = normalize_typos(text)
        result = self._parse_clean(normalized)
        if result is not None:
            return result
        if normalized.lower() != text.lower():
            return self._parse_clean(text)
        return None

    def _parse_clean(self, text: str) -> Optional[List[PlannedAction]]:
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
