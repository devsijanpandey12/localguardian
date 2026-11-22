"""User confirmation channel for MEDIUM and HIGH risk actions."""

from __future__ import annotations

import json
from enum import Enum
from typing import Any, Dict

from localguardian.safety.policy import PolicyVerdict


class ConfirmationChannel(str, Enum):
    DIALOG = "dialog"  # Desktop Tkinter Yes/No modal
    CLI = "cli"        # Terminal y/N prompt
    DENY = "deny"      # Fail-closed automatic denial (tests/headless)
    ALLOW = "allow"    # Explicit test-only approval mock


class ConfirmationManager:
    def __init__(self, channel: ConfirmationChannel = ConfirmationChannel.DIALOG) -> None:
        self.channel = channel

    def request_approval(
        self, tool_name: str, args: Dict[str, Any], verdict: PolicyVerdict
    ) -> bool:
        if not verdict.requires_confirmation:
            return True

        if self.channel == ConfirmationChannel.DENY:
            return False
        if self.channel == ConfirmationChannel.ALLOW:
            return True

        summary = (
            f"LocalGuardian Safety Confirmation ({verdict.risk.value} RISK)\n\n"
            f"Action: {tool_name}\n"
            f"Arguments: {json.dumps(args, ensure_ascii=False)}\n"
            f"Policy Rule: {verdict.rule_id}\n"
            f"Reason: {verdict.reason}\n\n"
            "Do you approve running this action?"
        )

        if self.channel == ConfirmationChannel.DIALOG:
            try:
                import tkinter as tk
                from tkinter import messagebox

                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                approved = bool(messagebox.askyesno("LocalGuardian — Confirm Action", summary))
                root.destroy()
                return approved
            except Exception:
                # Fall back cleanly to CLI prompt if GUI display is unavailable
                pass

        try:
            answer = input(f"\n{summary}\nApprove? [y/N]: ").strip().lower()
            return answer in {"y", "yes"}
        except EOFError:
            return False
