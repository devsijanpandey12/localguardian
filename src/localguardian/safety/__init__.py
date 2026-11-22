"""Hard-coded safety policy, confirmation, failsafe, and audit logging."""

from localguardian.safety.audit import AuditEntry, AuditLogger
from localguardian.safety.confirm import ConfirmationChannel, ConfirmationManager
from localguardian.safety.failsafe import FailsafeController, FailsafeTriggeredError
from localguardian.safety.policy import (
    PolicyVerdict,
    RiskLevel,
    SafetyPolicy,
    is_running_as_admin,
)

__all__ = [
    "AuditEntry",
    "AuditLogger",
    "ConfirmationChannel",
    "ConfirmationManager",
    "FailsafeController",
    "FailsafeTriggeredError",
    "PolicyVerdict",
    "RiskLevel",
    "SafetyPolicy",
    "is_running_as_admin",
]
