"""3-Tier Cascade Orchestrator:
    Tier 1   : Deterministic Fast Grammar (CPU, <1 ms)
    Tier 1.5 : Cactus Needle 3 on-device tool router (CPU, ~70-130 ms, confidence-gated)
    Tier 2   : Local Ollama LLM (qwen3:4b on RTX 4050 GPU, full multi-step reasoning)
    -> SafetyPolicy -> Confirmation -> Typed Tools -> SQLite Audit
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from localguardian.brain.fast_grammar import FastGrammarParser
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
    """Routes user instructions through the 3-tier local cognitive cascade."""

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

    def handle(
        self,
        user_text: str,
        *,
        dry_run: Optional[bool] = None,
    ) -> OrchestratorResult:
        cleaned = user_text.strip()
        if not cleaned:
            return OrchestratorResult(
                transcript="",
                route_tier="none",
                message="Empty instruction.",
            )

        # Tier 1: Deterministic fast grammar (<1 ms on CPU)
        actions = self.grammar.parse(cleaned)
        route_tier = "tier1_grammar"
        needle_trace: Dict[str, Any] = {}
        llm_reply = ""

        # Tier 1.5: Cactus Needle 3 on-device router (~70-130 ms on CPU, confidence-gated)
        if not actions and self.needle.enabled:
            needle_actions, needle_trace = self.needle.route(cleaned)
            if needle_actions:
                actions = needle_actions
                route_tier = "tier1_5_cactus_needle"

        # Tier 2: Escalate to local Ollama LLM if both fast tiers declined
        if not actions:
            route_tier = "tier2_ollama"
            actions, llm_reply = self.planner.plan(
                cleaned, self.registry.openai_tool_schemas()
            )

        if not actions:
            return OrchestratorResult(
                transcript=cleaned,
                route_tier=route_tier,
                results=[],
                message=llm_reply or "Could not map that instruction to any safe tool.",
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
            # Stop multi-step chain immediately if a safety block occurs
            if res.status in {"blocked", "cancelled"}:
                break

        return OrchestratorResult(
            transcript=cleaned,
            route_tier=route_tier,
            results=results,
            message=" | ".join(messages),
            needle_trace=needle_trace,
        )
