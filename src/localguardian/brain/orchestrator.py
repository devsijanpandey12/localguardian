"""3-Tier Cascade Orchestrator with Pre-Flight Guard, Live Progress, and Undo:
    Pre-Flight: Instant (<1 ms) help, undo, small talk, and gibberish filter
    Tier 1    : Deterministic Fast Grammar + conservative typo repair (CPU, <1 ms)
    Tier 1.5  : Timeout-protected Cactus Needle 3 (CPU, ~70-130 ms, confidence-gated)
    Tier 2    : Local Ollama LLM (qwen3:4b on RTX 4050 GPU, bounded timeout + tokens)
    -> SafetyPolicy -> Confirmation -> Typed Tools -> SQLite Audit
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from localguardian.brain.fast_grammar import (
    FastGrammarParser,
    check_preflight,
    suggest_examples,
)
from localguardian.brain.llm_planner import LocalLLMPlanner
from localguardian.brain.needle_router import CactusNeedleRouter
from localguardian.config import LocalGuardianConfig
from localguardian.tools.registry import ToolExecutionResult, ToolRegistry


class OrchestratorResult(BaseModel):
    transcript: str
    route_tier: str
    results: List[ToolExecutionResult] = Field(default_factory=list)
    message: str
    needle_trace: Dict[str, Any] = Field(default_factory=dict)


class LocalGuardianOrchestrator:
    """Routes user instructions through the non-freezing 3-tier local cascade."""

    def __init__(
        self,
        config: LocalGuardianConfig,
        registry: ToolRegistry,
        grammar: Optional[FastGrammarParser] = None,
        needle: Optional[CactusNeedleRouter] = None,
        planner: Optional[LocalLLMPlanner] = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.grammar = grammar or FastGrammarParser()
        self.needle = needle or CactusNeedleRouter(config)
        self.planner = planner or LocalLLMPlanner(config)

    def prewarm(self) -> None:
        """Asynchronously warm up Cactus Needle in the background."""
        self.needle.prewarm_async()

    def close(self) -> None:
        self.needle.close()

    def handle(
        self,
        user_text: str,
        *,
        dry_run: Optional[bool] = None,
        on_status: Optional[Callable[[str], None]] = None,
    ) -> OrchestratorResult:
        cleaned = user_text.strip()
        if not cleaned:
            return OrchestratorResult(
                transcript="",
                route_tier="none",
                message="Empty instruction. Type 'help' to see available commands.",
            )

        # 0. Pre-flight instant guard (<1 ms): help, undo, small talk, obvious gibberish
        preflight = check_preflight(cleaned)
        if preflight is not None:
            kind, msg = preflight
            if kind == "undo":
                undo_res = self.registry.undo_last(transcript=cleaned, dry_run=dry_run)
                if undo_res is None:
                    return OrchestratorResult(
                        transcript=cleaned,
                        route_tier="undo",
                        message="Nothing to undo yet (brightness, volume, and mute changes are undoable).",
                    )
                return OrchestratorResult(
                    transcript=cleaned,
                    route_tier="undo",
                    results=[undo_res],
                    message=undo_res.message,
                )
            return OrchestratorResult(
                transcript=cleaned,
                route_tier=f"preflight_{kind}",
                message=msg,
            )

        # Tier 1: Deterministic fast grammar + conservative typo repair (<1 ms on CPU)
        actions = self.grammar.parse(cleaned)
        route_tier = "tier1_grammar"
        needle_trace: Dict[str, Any] = {}
        llm_reply = ""

        # Tier 1.5: Cactus Needle 3 on-device router (CPU, hard timeout + confidence gate)
        if not actions and self.needle.enabled:
            if on_status:
                on_status("checking Cactus Needle (CPU)...")
            needle_actions, needle_trace = self.needle.route(cleaned)
            if needle_actions:
                actions = needle_actions
                route_tier = "tier1_5_cactus_needle"

        # Tier 2: Escalate to local Ollama LLM if both fast tiers declined
        if not actions:
            route_tier = "tier2_ollama"
            if on_status:
                on_status(f"asking local {self.config.llm.model} (timeout {self.config.llm.timeout_seconds:.0f}s)...")
            actions, llm_reply = self.planner.plan(
                cleaned, self.registry.openai_tool_schemas()
            )

        if not actions:
            suggestions = " | ".join(f"'{s}'" for s in suggest_examples(cleaned))
            base_msg = llm_reply or "Could not map that instruction to any safe tool."
            return OrchestratorResult(
                transcript=cleaned,
                route_tier=route_tier,
                results=[],
                message=f"{base_msg} Try: {suggestions} (or type 'help').",
                needle_trace=needle_trace,
            )

        results: List[ToolExecutionResult] = []
        messages: List[str] = []
        for action in actions:
            res = self.registry.invoke(
                action.tool_name,
                action.args,
                transcript=cleaned,
                route_tier=action.route_tier,
                dry_run=dry_run,
            )
            results.append(res)
            messages.append(res.message)
            if res.status in {"blocked", "cancelled"}:
                break

        return OrchestratorResult(
            transcript=cleaned,
            route_tier=route_tier,
            results=results,
            message=" | ".join(messages),
            needle_trace=needle_trace,
        )
