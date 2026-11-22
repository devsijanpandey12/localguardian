"""Cascade Orchestrator: Fast Grammar (Tier 1) -> Local Ollama LLM (Tier 2) -> Safety -> Tools."""

from __future__ import annotations

from typing import List, Optional

from pydantic import BaseModel, Field

from localguardian.brain.fast_grammar import FastGrammarParser
from localguardian.brain.llm_planner import LocalLLMPlanner
from localguardian.config import LocalGuardianConfig
from localguardian.tools.registry import ToolExecutionResult, ToolRegistry


class OrchestratorResult(BaseModel):
    transcript: str
    route_tier: str
    results: List[ToolExecutionResult] = Field(default_factory=list)
    message: str


class LocalGuardianOrchestrator:
    """Routes user instructions through the local cognitive cascade."""

    def __init__(
        self,
        config: LocalGuardianConfig,
        registry: ToolRegistry,
        grammar: Optional[FastGrammarParser] = None,
        planner: Optional[LocalLLMPlanner] = None,
    ) -> None:
        self.config = config
        self.registry = registry
        self.grammar = grammar or FastGrammarParser()
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
        llm_reply = ""

        # Tier 2: Escalate to local Ollama LLM if fast grammar didn't match
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
        )
