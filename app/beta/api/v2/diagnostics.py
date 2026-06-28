"""WooPrice Beta — /api/v2/diagnostics router (CP1.3 contract stubs).

Contract shape defined in CP1.3.  Live implementation begins in B6
when the Docker stack and background polling are available.

Authentication note: POST /api/v2/diagnostics/run requires admin permission.
Auth middleware is implemented in B7 — stubs are unauthenticated in CP1.
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional

router = APIRouter(prefix="/diagnostics", tags=["diagnostics"])


class DiagnosticRunRequest(BaseModel):
    target: str = "all"


class DiagnosticCheckShape(BaseModel):
    check_name: str
    category: str
    target: str
    status: str
    failure_class: str
    severity: str
    message: str
    repair_hint: str
    duration_ms: float
    checked_at: str
    details: dict
    skipped_because: Optional[str]


class RepairStepShape(BaseModel):
    step_number: int
    description: str
    command: Optional[str]
    detail: Optional[str]


class DiagnosticRunResponse(BaseModel):
    target: str
    started_at: str
    completed_at: str
    duration_ms: float
    overall_status: str
    overall_failure_class: str
    overall_severity: str
    summary: str
    checks: list[DiagnosticCheckShape]
    repair_steps: list[RepairStepShape]


@router.post("/run", response_model=DiagnosticRunResponse)
async def run_diagnostics(body: DiagnosticRunRequest) -> DiagnosticRunResponse:
    """Trigger an on-demand diagnostic run.

    Admin permission required (enforced in B7).
    Live implementation in B6.
    """
    raise NotImplementedError("Diagnostic run endpoint implemented in B6.")


@router.get("/history")
async def diagnostic_history(limit: int = 10) -> dict:
    """Return recent diagnostic run history.

    Persistence layer implemented in B6.
    """
    return {"runs": [], "note": "Diagnostic history available in B6."}
