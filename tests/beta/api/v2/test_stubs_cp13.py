"""Tests for CP1.3 REST API contract stubs — shape and importability."""

from __future__ import annotations

import pytest
from fastapi import APIRouter


class TestDiagnosticsStub:
    def test_router_importable(self):
        from app.beta.api.v2.diagnostics import router
        assert isinstance(router, APIRouter)

    def test_router_has_run_route(self):
        from app.beta.api.v2.diagnostics import router
        paths = [r.path for r in router.routes]
        assert any("run" in p for p in paths)

    def test_router_has_history_route(self):
        from app.beta.api.v2.diagnostics import router
        paths = [r.path for r in router.routes]
        assert any("history" in p for p in paths)

    def test_run_request_model_importable(self):
        from app.beta.api.v2.diagnostics import DiagnosticRunRequest
        req = DiagnosticRunRequest()
        assert req.target == "all"

    def test_run_request_custom_target(self):
        from app.beta.api.v2.diagnostics import DiagnosticRunRequest
        req = DiagnosticRunRequest(target="nextcloud")
        assert req.target == "nextcloud"

    def test_repair_step_shape_importable(self):
        from app.beta.api.v2.diagnostics import RepairStepShape
        step = RepairStepShape(
            step_number=1,
            description="Do this",
            command=None,
            detail=None,
        )
        assert step.step_number == 1

    def test_response_model_importable(self):
        from app.beta.api.v2.diagnostics import DiagnosticRunResponse
        assert DiagnosticRunResponse is not None


class TestHealthV2Stub:
    def test_router_importable(self):
        from app.beta.api.v2.health import router
        assert isinstance(router, APIRouter)

    def test_router_has_get_route(self):
        from app.beta.api.v2.health import router
        methods_paths = [(r.methods, r.path) for r in router.routes]
        assert any("GET" in (m or set()) for m, p in methods_paths)

    def test_router_has_check_route(self):
        from app.beta.api.v2.health import router
        paths = [r.path for r in router.routes]
        assert any("check" in p for p in paths)

    def test_on_demand_request_model(self):
        from app.beta.api.v2.health import OnDemandCheckRequest
        req = OnDemandCheckRequest(target="nextcloud")
        assert req.target == "nextcloud"

    def test_control_plane_status_shape(self):
        from app.beta.api.v2.health import ControlPlaneStatusShape
        assert ControlPlaneStatusShape is not None


class TestConfigV2Stub:
    def test_router_importable(self):
        from app.beta.api.v2.config import router
        assert isinstance(router, APIRouter)

    def test_router_has_list_route(self):
        from app.beta.api.v2.config import router
        methods_paths = [(r.methods, r.path) for r in router.routes]
        assert any("GET" in (m or set()) for m, p in methods_paths)

    def test_router_has_field_get_route(self):
        from app.beta.api.v2.config import router
        paths = [r.path for r in router.routes]
        assert any("{field_name}" in p for p in paths)

    def test_router_has_field_put_route(self):
        from app.beta.api.v2.config import router
        methods_paths = [(r.methods, r.path) for r in router.routes]
        assert any("PUT" in (m or set()) for m, p in methods_paths)

    def test_set_request_model_importable(self):
        from app.beta.api.v2.config import ConfigSetRequest
        req = ConfigSetRequest(value="DEBUG")
        assert req.value == "DEBUG"

    def test_record_shape_importable(self):
        from app.beta.api.v2.config import ConfigRecordShape
        assert ConfigRecordShape is not None
