"""WooPrice Beta — FastAPI application entry point.

Deployment: uvicorn app.beta.app:app --host 0.0.0.0 --port 8085

Only the /api/health route is active in CP1.  All other routers are
registered in their respective B-phase implementations and wired here then.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.beta.api.health import router as health_router

app = FastAPI(
    title="WooPrice Beta",
    version="0.1.0-dev",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(health_router, prefix="/api")
