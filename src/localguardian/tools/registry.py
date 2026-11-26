"""Typed Tool Registry wrapping every OS/Window/Chrome tool behind SafetyPolicy + AuditLogger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Type

from pydantic import BaseModel, Field, ValidationError

from localguardian.config import LocalGuardianConfig
from localguardian.safety.audit import AuditLogger
from localguardian.safety.confirm import ConfirmationManager
from localguardian.safety.failsafe import FailsafeController, FailsafeTriggeredError
from localguardian.safety.policy import PolicyVerdict, RiskLevel, SafetyPolicy
from localguardian.tools.browser import ChromeController
from localguardian.tools.os_controls import OSControls
from localguardian.tools.window_tools import WindowController


# ---------------------------------------------------------------------------
# Strict Pydantic Argument Schemas
# ---------------------------------------------------------------------------

class EmptyArgs(BaseModel):
    pass


class SetBrightnessArgs(BaseModel):
    level: int = Field(..., ge=0, le=100, description="Target screen brightness percentage (0 to 100).")


class AdjustBrightnessArgs(BaseModel):
    delta: int = Field(..., ge=-100, le=100, description="Relative brightness change, e.g. +20 or -20.")


class SetVolumeArgs(BaseModel):
    level: int = Field(..., ge=0, le=100, description="Target master volume percentage (0 to 100).")


class AdjustVolumeArgs(BaseModel):
    delta: int = Field(..., ge=-100, le=100, description="Relative volume change, e.g. +15 or -15.")


class ToggleMuteArgs(BaseModel):
    mute: Optional[bool] = Field(default=None, description="True to mute, False to unmute, or null to toggle.")


class MediaControlArgs(BaseModel):
    action: Literal["play_pause", "next", "previous"] = Field(
        ..., description="Media playback action: play_pause, next, or previous."
    )


class OpenAppArgs(BaseModel):
    app_name: str = Field(..., description="Allowlisted app name: chrome, notepad, calculator, paint, edge, vscode.")


class ChromeOpenUrlArgs(BaseModel):
    url: str = Field(..., description="Safe http:// or https:// URL to open in Google Chrome.")


class ChromeSearchArgs(BaseModel):
    query: str = Field(..., min_length=1, max_length=500, description="Search query to type and search in Google Chrome.")


class FocusWindowArgs(BaseModel):
    window_name: str = Field(..., min_length=1, max_length=120, description="App or window title to bring to front.")


class SnapWindowArgs(BaseModel):
    window_name: str = Field(..., min_length=1, max_length=120, description="Open app or window title to snap.")
    position: Literal["left", "right", "maximize", "minimize"] = Field(
        ..., description="Target layout: left, right, maximize, or minimize."
    )


class TakeScreenshotArgs(BaseModel):
    filename: Optional[str] = Field(
        default=None,
        description="Optional simple PNG filename (saved strictly inside ~/LocalGuardian_Workspace/screenshots/).",
    )


class ActivateWorkspaceModeArgs(BaseModel):
    mode: Literal["coding", "study", "focus", "relax"] = Field(
        ..., description="Preset workspace mode: coding, study, focus, or relax."
    )


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Callable[[BaseModel], Dict[str, Any]]


class ToolExecutionResult(BaseModel):
    tool_name: str
    args: Dict[str, Any]
    verdict: PolicyVerdict
    executed: bool
    dry_run: bool
    status: str  # "ok" | "dry_run" | "blocked" | "cancelled" | "error"
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)


class ToolRegistry:
    """Single execution chokepoint: Schema -> Failsafe -> SafetyPolicy -> Confirm -> Execute -> Audit."""

    def __init__(
        self,
        config: LocalGuardianConfig,
        policy: SafetyPolicy,
        audit: AuditLogger,
        confirm: ConfirmationManager,
        failsafe: Optional[FailsafeController] = None,
        os_controls: Optional[OSControls] = None,
        chrome: Optional[ChromeController] = None,
        windows: Optional[WindowController] = None,
        keep_browser_open_on_oneshot: bool = False,
    ) -> None:
        self.config = config
        self.policy = policy
        self.audit = audit
        self.confirm = confirm
        self.failsafe = failsafe or FailsafeController(enable_corner_slam=False)
        self.os_controls = os_controls or OSControls(config)
        self.chrome = chrome or ChromeController(config)
        self.windows = windows or WindowController()
        self.keep_browser_open_on_oneshot = keep_browser_open_on_oneshot
        self._specs: Dict[str, ToolSpec] = {}
        self._undo_stack: List[tuple[str, Dict[str, Any], str]] = []
        self._register_builtin_tools()

    def _register_builtin_tools(self) -> None:
        specs = [
            ToolSpec(
                name="get_brightness",
                description="Read the current display brightness percentage.",
                args_model=EmptyArgs,
                handler=lambda _: self.os_controls.get_brightness(),
            ),
            ToolSpec(
                name="set_brightness",
                description="Set the Windows display brightness to an exact percentage (0-100).",
                args_model=SetBrightnessArgs,
                handler=lambda a: self.os_controls.set_brightness(a.level),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="adjust_brightness",
                description="Increase or decrease Windows display brightness by a relative percentage (e.g. +20 or -20).",
                args_model=AdjustBrightnessArgs,
                handler=lambda a: self.os_controls.adjust_brightness(a.delta),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="get_volume",
                description="Read the current Windows system audio volume and mute state.",
                args_model=EmptyArgs,
                handler=lambda _: self.os_controls.get_volume(),
            ),
            ToolSpec(
                name="set_volume",
                description="Set the Windows master audio volume to an exact percentage (0-100).",
                args_model=SetVolumeArgs,
                handler=lambda a: self.os_controls.set_volume(a.level),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="adjust_volume",
                description="Increase or decrease Windows master audio volume by a relative percentage (e.g. +15 or -15).",
                args_model=AdjustVolumeArgs,
                handler=lambda a: self.os_controls.adjust_volume(a.delta),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="toggle_mute",
                description="Mute, unmute, or toggle Windows system audio.",
                args_model=ToggleMuteArgs,
                handler=lambda a: self.os_controls.toggle_mute(a.mute),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="media_control",
                description="Control media playback across Spotify, Chrome, or media apps: play_pause, next, or previous.",
                args_model=MediaControlArgs,
                handler=lambda a: self.os_controls.media_control(a.action),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="open_app",
                description="Open an allowlisted desktop application (chrome, notepad, calculator, paint, edge, vscode).",
                args_model=OpenAppArgs,
                handler=lambda a: self.os_controls.open_app(a.app_name),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="chrome_open_url",
                description="Open a safe http/https website URL in Google Chrome (priority #1 browser).",
                args_model=ChromeOpenUrlArgs,
                handler=lambda a: self.chrome.open_url(
                    a.url, keep_open_after_exit=self.keep_browser_open_on_oneshot  # type: ignore[attr-defined]
                ),
            ),
            ToolSpec(
                name="chrome_search",
                description="Open Google Chrome (priority #1 browser), type a query, and search the web.",
                args_model=ChromeSearchArgs,
                handler=lambda a: self.chrome.search(
                    a.query, keep_open_after_exit=self.keep_browser_open_on_oneshot  # type: ignore[attr-defined]
                ),
            ),
            ToolSpec(
                name="chrome_get_page_info",
                description="Read the title, URL, and text snippet of the currently open LocalGuardian Chrome tab.",
                args_model=EmptyArgs,
                handler=lambda _: self.chrome.get_page_info(),
            ),
            ToolSpec(
                name="list_open_windows",
                description="List currently visible open desktop windows (read-only).",
                args_model=EmptyArgs,
                handler=lambda _: self.windows.list_open_windows(),
            ),
            ToolSpec(
                name="focus_window",
                description="Restore and focus an open desktop window by app or title (e.g., chrome, notepad, vscode).",
                args_model=FocusWindowArgs,
                handler=lambda a: self.windows.focus_window(a.window_name),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="snap_window",
                description="Snap an open window to the left half, right half, maximize, or minimize.",
                args_model=SnapWindowArgs,
                handler=lambda a: self.windows.snap_window(a.window_name, a.position),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="take_screenshot",
                description="Save a PNG screenshot strictly inside ~/LocalGuardian_Workspace/screenshots/.",
                args_model=TakeScreenshotArgs,
                handler=lambda a: self.os_controls.take_screenshot(a.filename),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="activate_workspace_mode",
                description="Apply a safe 1-command workspace preset (coding, study, focus, or relax).",
                args_model=ActivateWorkspaceModeArgs,
                handler=lambda a: self.os_controls.activate_workspace_mode(a.mode),  # type: ignore[attr-defined]
            ),
            ToolSpec(
                name="get_system_status",
                description="Read-only check of brightness, volume, battery, CPU, RAM, and GPU temperature/VRAM.",
                args_model=EmptyArgs,
                handler=lambda _: self.os_controls.get_system_status(),
            ),
        ]
        for spec in specs:
            self._specs[spec.name] = spec

    def list_tools(self) -> List[ToolSpec]:
        return list(self._specs.values())

    def openai_tool_schemas(self) -> List[Dict[str, Any]]:
        """Export OpenAI-compatible tool definitions for Ollama (Qwen3 / Gemma 4)."""
        schemas: List[Dict[str, Any]] = []
        for spec in self._specs.values():
            params = spec.args_model.model_json_schema()
            params.pop("title", None)
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": spec.description,
                        "parameters": params,
                    },
                }
            )
        return schemas

    def invoke(
        self,
        tool_name: str,
        raw_args: Dict[str, Any],
        *,
        transcript: str = "",
        route_tier: str = "direct",
        dry_run: Optional[bool] = None,
    ) -> ToolExecutionResult:
        """Validate, policy-check, confirm, execute (or dry-run), and audit a tool call."""
        effective_dry_run = self.config.safety.dry_run if dry_run is None else dry_run

        # 1. Failsafe check
        try:
            self.failsafe.check()
        except FailsafeTriggeredError as exc:
            verdict = PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="FAILSAFE_ABORT",
                reason=str(exc),
            )
            self.audit.record(
                transcript=transcript,
                route_tier=route_tier,
                tool_name=tool_name,
                args=raw_args,
                risk_level=verdict.risk.value,
                rule_id=verdict.rule_id,
                allowed=False,
                dry_run=effective_dry_run,
                status="blocked",
                message=verdict.reason,
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                args=raw_args,
                verdict=verdict,
                executed=False,
                dry_run=effective_dry_run,
                status="blocked",
                message=verdict.reason,
            )

        # 2. Hard Safety Policy evaluation (BEFORE looking up or running anything)
        verdict = self.policy.evaluate(tool_name, raw_args)
        if not verdict.allowed:
            self.audit.record(
                transcript=transcript,
                route_tier=route_tier,
                tool_name=tool_name,
                args=raw_args,
                risk_level=verdict.risk.value,
                rule_id=verdict.rule_id,
                allowed=False,
                dry_run=effective_dry_run,
                status="blocked",
                message=verdict.reason,
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                args=raw_args,
                verdict=verdict,
                executed=False,
                dry_run=effective_dry_run,
                status="blocked",
                message=f"[BLOCKED:{verdict.rule_id}] {verdict.reason}",
            )

        # 3. Tool lookup & strict Pydantic schema validation
        spec = self._specs.get(tool_name)
        if spec is None:
            verdict = PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="TOOL_NOT_REGISTERED",
                reason=f"Tool '{tool_name}' is not registered.",
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                args=raw_args,
                verdict=verdict,
                executed=False,
                dry_run=effective_dry_run,
                status="blocked",
                message=verdict.reason,
            )

        effective_args = dict(raw_args)
        if tool_name == "chrome_open_url" and "normalized_url" in verdict.details:
            effective_args["url"] = verdict.details["normalized_url"]
        if tool_name == "open_app" and "app_key" in verdict.details:
            effective_args["app_name"] = verdict.details["app_key"]

        try:
            validated = spec.args_model.model_validate(effective_args)
        except ValidationError as exc:
            msg = f"Invalid tool arguments for '{tool_name}': {exc.errors()[0]['msg']}"
            bad_verdict = PolicyVerdict(
                allowed=False,
                risk=RiskLevel.FORBIDDEN,
                rule_id="SCHEMA_VALIDATION_FAILED",
                reason=msg,
            )
            self.audit.record(
                transcript=transcript,
                route_tier=route_tier,
                tool_name=tool_name,
                args=raw_args,
                risk_level=bad_verdict.risk.value,
                rule_id=bad_verdict.rule_id,
                allowed=False,
                dry_run=effective_dry_run,
                status="blocked",
                message=msg,
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                args=raw_args,
                verdict=bad_verdict,
                executed=False,
                dry_run=effective_dry_run,
                status="blocked",
                message=msg,
            )

        clean_args = validated.model_dump()

        # 4. Dry-run short-circuit
        if effective_dry_run:
            msg = f"[DRY-RUN] Would execute {tool_name}({clean_args}) [risk={verdict.risk.value}]"
            self.audit.record(
                transcript=transcript,
                route_tier=route_tier,
                tool_name=tool_name,
                args=clean_args,
                risk_level=verdict.risk.value,
                rule_id=verdict.rule_id,
                allowed=True,
                dry_run=True,
                status="dry_run",
                message=msg,
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                args=clean_args,
                verdict=verdict,
                executed=False,
                dry_run=True,
                status="dry_run",
                message=msg,
            )

        # 5. User confirmation for MEDIUM / HIGH risk actions
        if verdict.requires_confirmation:
            approved = self.confirm.request_approval(tool_name, clean_args, verdict)
            if not approved:
                msg = f"Action '{tool_name}' cancelled by user confirmation gate."
                self.audit.record(
                    transcript=transcript,
                    route_tier=route_tier,
                    tool_name=tool_name,
                    args=clean_args,
                    risk_level=verdict.risk.value,
                    rule_id=verdict.rule_id,
                    allowed=False,
                    dry_run=False,
                    status="cancelled",
                    message=msg,
                )
                return ToolExecutionResult(
                    tool_name=tool_name,
                    args=clean_args,
                    verdict=verdict,
                    executed=False,
                    dry_run=False,
                    status="cancelled",
                    message=msg,
                )

        # 6. Execute typed tool
        try:
            data = spec.handler(validated)
            msg = str(data.get("message", f"Executed {tool_name} successfully."))
            if route_tier != "undo":
                self._record_undo(tool_name, data)
            self.audit.record(
                transcript=transcript,
                route_tier=route_tier,
                tool_name=tool_name,
                args=clean_args,
                risk_level=verdict.risk.value,
                rule_id=verdict.rule_id,
                allowed=True,
                dry_run=False,
                status="ok",
                message=msg,
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                args=clean_args,
                verdict=verdict,
                executed=True,
                dry_run=False,
                status="ok",
                message=msg,
                data=data,
            )
        except Exception as exc:
            msg = f"Execution error in '{tool_name}': {exc}"
            self.audit.record(
                transcript=transcript,
                route_tier=route_tier,
                tool_name=tool_name,
                args=clean_args,
                risk_level=verdict.risk.value,
                rule_id=verdict.rule_id,
                allowed=True,
                dry_run=False,
                status="error",
                message=msg,
            )
            return ToolExecutionResult(
                tool_name=tool_name,
                args=clean_args,
                verdict=verdict,
                executed=False,
                dry_run=False,
                status="error",
                message=msg,
            )

    def _record_undo(self, tool_name: str, data: Dict[str, Any]) -> None:
        """Save inverse operation for reversible OS actions (brightness, volume, mute)."""
        if tool_name in {"set_brightness", "adjust_brightness"} and isinstance(data.get("before"), int):
            self._undo_stack.append(
                ("set_brightness", {"level": int(data["before"])}, f"restored brightness to {data['before']}%")
            )
        elif tool_name in {"set_volume", "adjust_volume"} and isinstance(data.get("before"), int):
            self._undo_stack.append(
                ("set_volume", {"level": int(data["before"])}, f"restored volume to {data['before']}%")
            )
        elif tool_name == "toggle_mute" and isinstance(data.get("before_muted"), bool):
            state = "muted" if data["before_muted"] else "unmuted"
            self._undo_stack.append(
                ("toggle_mute", {"mute": bool(data["before_muted"])}, f"restored audio to {state}")
            )
        # Cap undo stack to last 20 actions
        if len(self._undo_stack) > 20:
            self._undo_stack = self._undo_stack[-20:]

    def undo_last(self, *, transcript: str = "undo", dry_run: Optional[bool] = None) -> Optional[ToolExecutionResult]:
        """Revert the most recent reversible OS action via the full safety-gated pipeline."""
        if not self._undo_stack:
            return None
        undo_tool, undo_args, label = self._undo_stack.pop()
        res = self.invoke(
            undo_tool,
            undo_args,
            transcript=transcript,
            route_tier="undo",
            dry_run=dry_run,
        )
        if res.status == "ok":
            res.message = f"Undo successful ({label})."
        return res

    def close(self) -> None:
        self.chrome.close()
