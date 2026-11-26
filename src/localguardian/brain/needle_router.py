"""Tier-1.5 On-Device Cactus Needle Router (CPU, ~70-130 ms, ~131 MB RAM, 0 VRAM).

Upgrades in v0.3.0:
- Hard per-call timeout (`config.needle.timeout_seconds`, default 5s) via a
  dedicated worker thread so a stalled native call can NEVER freeze the CLI.
- Optional background pre-warming (`prewarm_async()`) so interactive sessions
  don't stall on the first unrecognized command.
- Suppresses noisy HuggingFace Hub unauthenticated warnings cleanly.
"""

from __future__ import annotations

import concurrent.futures
import json
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from localguardian.brain.fast_grammar import PlannedAction
from localguardian.config import LocalGuardianConfig


NEEDLE_SYSTEM_PROMPT = (
    "Map a single Windows desktop or Chrome command into one exact tool call. "
    "Never invent numbers or arguments that the user did not state."
)

# Compact, non-overlapping schemas tailored to Cactus Needle 3's grounded validator.
NEEDLE_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "set_brightness",
        "description": "Set Windows display brightness to a specific percentage (0 to 100).",
        "parameters": {
            "type": "object",
            "properties": {"level": {"type": "integer", "description": "Brightness 0-100."}},
            "required": ["level"],
        },
    },
    {
        "name": "set_volume",
        "description": "Set Windows audio volume to a specific percentage (0 to 100).",
        "parameters": {
            "type": "object",
            "properties": {"level": {"type": "integer", "description": "Volume 0-100."}},
            "required": ["level"],
        },
    },
    {
        "name": "chrome_search",
        "description": "Search Google in Google Chrome for a person, topic, or question.",
        "parameters": {
            "type": "object",
            "properties": {"query": {"type": "string", "description": "Search query."}},
            "required": ["query"],
        },
    },
    {
        "name": "chrome_open_url",
        "description": "Open a specific website domain or URL in Google Chrome.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string", "description": "Website URL, e.g. github.com."}},
            "required": ["url"],
        },
    },
    {
        "name": "open_app",
        "description": "Launch an allowlisted app: chrome, notepad, calculator, paint, edge, or vscode.",
        "parameters": {
            "type": "object",
            "properties": {"app_name": {"type": "string", "description": "Application name."}},
            "required": ["app_name"],
        },
    },
    {
        "name": "media_control",
        "description": "Control media playback: play_pause, next, or previous.",
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["play_pause", "next", "previous"],
                    "description": "Media playback action.",
                }
            },
            "required": ["action"],
        },
    },
]


def _quiet_hf_warnings() -> None:
    os.environ.setdefault("HF_HUB_VERBOSITY", "error")
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    for name in ("huggingface_hub", "huggingface_hub.utils._http", "huggingface_hub.utils._headers"):
        logging.getLogger(name).setLevel(logging.ERROR)


def cactus_status() -> Dict[str, Any]:
    """Check whether `cactus-compute` (Needle, Whistle, Mirage) is installed."""
    info: Dict[str, Any] = {
        "installed": False,
        "version": None,
        "needle": False,
        "whistle": False,
        "mirage": False,
    }
    try:
        _quiet_hf_warnings()
        import cactus  # type: ignore

        info["installed"] = True
        info["version"] = getattr(cactus, "__version__", "unknown")
        info["needle"] = hasattr(cactus, "Needle")
        info["whistle"] = hasattr(cactus, "Whistle")
        info["mirage"] = hasattr(cactus, "Mirage")
    except Exception as exc:
        info["error"] = f"{exc.__class__.__name__}: {exc}"
    return info


class CactusNeedleRouter:
    """Lazy, thread-safe, timeout-protected Tier-1.5 Cactus Needle 3 router."""

    def __init__(
        self,
        config: LocalGuardianConfig,
        *,
        needle_factory: Optional[Any] = None,
    ) -> None:
        self.config = config
        self._needle_factory = needle_factory
        self._lock = threading.Lock()
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="cactus-needle"
        )
        self._needle: Any = None
        self._init_error: Optional[str] = None
        self.last_trace: Dict[str, Any] = {}

    @property
    def enabled(self) -> bool:
        return bool(self.config.needle.enabled)

    @property
    def init_error(self) -> Optional[str]:
        return self._init_error

    def prewarm_async(self) -> None:
        """Warm up Cactus Needle in the background so interactive sessions don't stall."""
        if not self.enabled or self._needle is not None:
            return
        try:
            self._executor.submit(self._get_needle)
        except Exception:
            pass

    def _get_needle(self) -> Any:
        if not self.enabled:
            return None
        with self._lock:
            if self._needle is not None or self._init_error is not None:
                return self._needle
            try:
                _quiet_hf_warnings()
                if self.config.needle.disable_telemetry:
                    os.environ.setdefault("CACTUS_TELEMETRY", "0")
                if self._needle_factory is not None:
                    self._needle = self._needle_factory(
                        tools=NEEDLE_TOOL_SCHEMAS,
                        system=NEEDLE_SYSTEM_PROMPT,
                        stateless=True,
                    )
                else:
                    import cactus  # type: ignore

                    self._needle = cactus.Needle(
                        tools=NEEDLE_TOOL_SCHEMAS,
                        system=NEEDLE_SYSTEM_PROMPT,
                        stateless=True,
                    )
            except Exception as exc:
                self._init_error = f"{exc.__class__.__name__}: {exc}"
                self._needle = None
            return self._needle

    def _complete_sync(self, user_text: str) -> Any:
        needle = self._get_needle()
        if needle is None:
            return None
        with self._lock:
            return needle.complete(
                text=user_text,
                max_new_tokens=self.config.needle.max_new_tokens,
            )

    def route(self, user_text: str) -> Tuple[Optional[List[PlannedAction]], Dict[str, Any]]:
        """Attempt confident single-step tool routing via Cactus Needle 3 on CPU.

        Enforces a strict timeout (`config.needle.timeout_seconds`) and confidence
        threshold (`config.needle.min_confidence`). Returns `(None, trace)` on any
        timeout, error, or low confidence so the orchestrator can escalate cleanly.
        """
        if not self.enabled:
            trace = {"status": "disabled"}
            self.last_trace = trace
            return None, trace

        # Give extra headroom only on cold first-time init; once loaded use strict timeout
        timeout_s = max(
            float(self.config.needle.timeout_seconds),
            12.0 if self._needle is None and self._needle_factory is None else 0.0,
        )

        t0 = time.perf_counter()
        future = self._executor.submit(self._complete_sync, user_text)
        try:
            raw = future.result(timeout=timeout_s)
        except concurrent.futures.TimeoutError:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            trace = {
                "status": "timeout",
                "timeout_seconds": timeout_s,
                "latency_ms": latency_ms,
                "accepted": False,
            }
            self.last_trace = trace
            return None, trace
        except Exception as exc:
            latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)
            trace = {
                "status": "error",
                "error": str(exc),
                "latency_ms": latency_ms,
                "accepted": False,
            }
            self.last_trace = trace
            return None, trace

        latency_ms = round((time.perf_counter() - t0) * 1000.0, 1)

        if raw is None:
            trace = {
                "status": "unavailable",
                "error": self._init_error,
                "latency_ms": latency_ms,
                "accepted": False,
            }
            self.last_trace = trace
            return None, trace

        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError:
                trace = {"status": "parse_error", "latency_ms": latency_ms, "accepted": False}
                self.last_trace = trace
                return None, trace

        if not isinstance(raw, dict):
            trace = {"status": "invalid_response", "latency_ms": latency_ms, "accepted": False}
            self.last_trace = trace
            return None, trace

        confidence = float(raw.get("confidence") or 0.0)
        calls = raw.get("function_calls") or []
        threshold = float(self.config.needle.min_confidence)

        trace = {
            "status": "evaluated",
            "confidence": round(confidence, 4),
            "threshold": threshold,
            "latency_ms": latency_ms,
            "reasoning": str(raw.get("reasoning") or ""),
            "proposed_calls": calls,
            "suppressed_calls": raw.get("suppressed_calls") or [],
            "peak_ram_mb": raw.get("peak_ram_mb"),
        }

        if not calls or confidence < threshold:
            trace["accepted"] = False
            self.last_trace = trace
            return None, trace

        actions: List[PlannedAction] = []
        for call in calls:
            if not isinstance(call, dict):
                continue
            name = call.get("name")
            args = call.get("arguments") or {}
            if isinstance(name, str) and name.strip() and isinstance(args, dict):
                actions.append(
                    PlannedAction(
                        tool_name=name.strip(),
                        args=args,
                        confidence=confidence,
                        route_tier="tier1_5_cactus_needle",
                    )
                )

        if not actions:
            trace["accepted"] = False
            self.last_trace = trace
            return None, trace

        trace["accepted"] = True
        self.last_trace = trace
        return actions, trace

    def close(self) -> None:
        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except Exception:
            pass
