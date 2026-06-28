"""WooPrice Beta — FastAPI application entry point.

Deployment: uvicorn app.beta.app:app --host 0.0.0.0 --port 8085

Only the /api/health route is active in CP1.  All other routers are
registered in their respective B-phase implementations and wired here then.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.beta.api.health import router as health_router

_VERSION = "0.1.0-dev"

_ROOT_HTML = """\
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
    UI and authentication are not yet implemented (scheduled for B5 / B7).<br>
    This server is a Control Plane pre-release for integration testing only.
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

app.include_router(health_router, prefix="/api")


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root() -> HTMLResponse:
    return HTMLResponse(content=_ROOT_HTML.format(version=_VERSION))
