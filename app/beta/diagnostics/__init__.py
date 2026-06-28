"""WooPrice Beta — Diagnostics package (CP1.3).

DiagnosticRunner orchestrates health checks through CP1.2 safe abstractions.
"""

from .report import DiagnosticCategory, DiagnosticCheckResult, DiagnosticReport, RepairStep
from .repair import ProbableCauseInferrer, RepairPlaybook
from .runner import DiagnosticRunner, KNOWN_SERVICES

__all__ = [
    "DiagnosticCategory",
    "DiagnosticCheckResult",
    "DiagnosticReport",
    "RepairStep",
    "ProbableCauseInferrer",
    "RepairPlaybook",
    "DiagnosticRunner",
    "KNOWN_SERVICES",
]
