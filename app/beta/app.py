"""WooPrice Beta — FastAPI application entry point (BU2).

Deployment: uvicorn app.beta.app:app --host 0.0.0.0 --port 8085

Active routes after BU2:
  GET  /api/health         — public health probe
  POST /api/auth/login     — issue JWT access + refresh tokens
  POST /api/auth/logout    — revoke refresh token (requires access token)
  POST /api/auth/refresh   — rotate refresh token
  GET  /api/auth/me        — current user profile (requires access token)
  GET  /                   — landing page (always; version/health info)
  *    /{any}              — SPA fallback: serves frontend/dist/index.html
                             (or the minimal landing page if not yet built)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.beta.api.health import router as health_router
from app.beta.api.v2.config import router as config_v2_router
from app.beta.api.v2.diagnostics import router as diagnostics_v2_router
from app.beta.api.v2.integrations import router as integrations_v2_router
from app.beta.api.v2.products import router as products_v2_router
from app.beta.api.v2.sources import router as sources_v2_router
from app.beta.api.v2.workspace import router as workspace_v2_router
from app.beta.auth.router import router as auth_router

_VERSION = "0.1.0-dev"

_FRONTEND_DIST = Path(__file__).parent.parent.parent / "frontend" / "dist"

_LANDING_HTML = """\
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>WooPrice Beta</title>
  <style>
    body {{ font-family: monospace; max-width: 600px; margin: 60px auto; padding: 0 20px; color: #222; }}
    h1 {{ font-size: 1.4rem; margin-bottom: 0.2em; }}
    table {{ border-collapse: collapse; margin-top: 1em; width: 100%; }}
    td {{ padding: 6px 12px; border: 1px solid #ddd; }}
    td:first-child {{ font-weight: bold; white-space: nowrap; }}
    .note {{ margin-top: 1.5em; padding: 10px 14px; background: #fff8e1; border-left: 3px solid #f0a500; font-size: 0.9rem; }}
    a {{ color: #1a6ebd; }}
  </style>
</head>
<body>
  <h1>WooPrice Beta</h1>
  <table>
    <tr><td>environment</td><td>beta</td></tr>
    <tr><td>version</td><td>{version}</td></tr>
    <tr><td>health endpoint</td><td><a href="/api/health">/api/health</a></td></tr>
    <tr><td>status</td><td>running</td></tr>
  </table>
  <div class="note">
    Frontend not yet built. Run <code>npm run build</code> inside <code>frontend/</code>
    then restart the server to activate the full UI.
  </div>
</body>
</html>
"""

app = FastAPI(
    title="WooPrice Beta",
    version=_VERSION,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

# API routers — registered before the SPA catch-all so they take priority
app.include_router(health_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(integrations_v2_router, prefix="/api/v2")
app.include_router(products_v2_router, prefix="/api/v2")
app.include_router(sources_v2_router, prefix="/api/v2")
app.include_router(workspace_v2_router, prefix="/api/v2")
app.include_router(diagnostics_v2_router, prefix="/api/v2")
app.include_router(config_v2_router, prefix="/api/v2")

# Static assets (hashed filenames produced by Vite; only mounted if built)
_assets_dir = _FRONTEND_DIST / "assets"
if _assets_dir.exists():
    app.mount("/assets", StaticFiles(directory=str(_assets_dir)), name="assets")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root() -> HTMLResponse:
    """Landing page — always served at root; shows version, environment, health endpoint."""
    return HTMLResponse(content=_LANDING_HTML.format(version=_VERSION))


@app.get("/{full_path:path}", response_class=HTMLResponse, response_model=None, include_in_schema=False)
async def spa(full_path: str) -> HTMLResponse | FileResponse:
    """Serve the React SPA for all non-API routes, or the landing page if not built."""
    index = _FRONTEND_DIST / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return HTMLResponse(content=_LANDING_HTML.format(version=_VERSION))
