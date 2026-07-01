"""WooPrice Beta /api/v2/diagnostics router.

Integration diagnostics are routed through Integration Platform contracts.
This endpoint reports connector configuration/capability/status checks and
does not call WooCommerce, Nextcloud, or any external service directly.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.beta.database import get_db
from app.beta.integrations.registry import registry
from app.beta.integrations.service import IntegrationService

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
async def run_diagnostics(
    body: DiagnosticRunRequest,
    db: Session = Depends(get_db),
) -> DiagnosticRunResponse:
    started = datetime.now(timezone.utc)
    service = IntegrationService(db)
    definitions = registry.list_definitions()
    if body.target != "all":
        definitions = [d for d in definitions if d.connector.identity.type == body.target]

    checks: list[DiagnosticCheckShape] = []
    instances = {i.connector.identity.type: i for i in service.list_instances()}
    for definition in definitions:
        instance = instances.get(definition.connector.identity.type)
        for check in definition.diagnostics_contract.checks:
            status_value = "pass" if instance and instance.connector.identity.enabled else "skip"
            checks.append(
                DiagnosticCheckShape(
                    check_name=check.name,
                    category=check.category,
                    target=definition.connector.identity.type,
                    status=status_value,
                    failure_class="none",
                    severity="info",
                    message=(
                        "Connector instance is present; live probe is delegated to Integration Platform health."
                        if status_value == "pass"
                        else "Connector instance is not active; live external probe was not attempted."
                    ),
                    repair_hint="Configure and enable the connector instance." if status_value == "skip" else "",
                    duration_ms=0.0,
                    checked_at=started.isoformat(),
                    details={"external_call_performed": False},
                    skipped_because=None if status_value == "pass" else "connector_not_active",
                )
            )

    completed = datetime.now(timezone.utc)
    overall_status = "ok" if checks and all(c.status == "pass" for c in checks) else "skip"
    return DiagnosticRunResponse(
        target=body.target,
        started_at=started.isoformat(),
        completed_at=completed.isoformat(),
        duration_ms=(completed - started).total_seconds() * 1000,
        overall_status=overall_status,
        overall_failure_class="none",
        overall_severity="info",
        summary="Integration diagnostics completed without direct external connector calls.",
        checks=checks,
        repair_steps=[],
    )


@router.get("/history")
async def diagnostic_history(limit: int = 10) -> dict:
    return {"runs": [], "limit": limit}
