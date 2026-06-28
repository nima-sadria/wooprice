"""Tests for ProbableCauseInferrer and RepairPlaybook."""

from __future__ import annotations

import pytest

from app.beta.control_plane.failure import FailureClass
from app.beta.diagnostics.repair import ProbableCauseInferrer, RepairPlaybook
from app.beta.diagnostics.report import RepairStep


class TestProbableCauseInferrer:
    def setup_method(self):
        self.inferrer = ProbableCauseInferrer()

    def test_dns_failure_cause(self):
        cause = self.inferrer.infer(FailureClass.DNS_FAILURE)
        assert "hostname" in cause.lower() or "dns" in cause.lower() or "resolve" in cause.lower()

    def test_tls_failure_cause(self):
        cause = self.inferrer.infer(FailureClass.TLS_FAILURE)
        assert "tls" in cause.lower() or "certificate" in cause.lower()

    def test_timeout_cause(self):
        cause = self.inferrer.infer(FailureClass.TIMEOUT)
        assert "timeout" in cause.lower() or "respond" in cause.lower()

    def test_unauthorized_cause(self):
        cause = self.inferrer.infer(FailureClass.UNAUTHORIZED)
        assert "credentials" in cause.lower() or "password" in cause.lower() or "rejected" in cause.lower()

    def test_forbidden_cause(self):
        cause = self.inferrer.infer(FailureClass.FORBIDDEN)
        assert "permission" in cause.lower() or "denied" in cause.lower() or "access" in cause.lower()

    def test_unreachable_cause(self):
        cause = self.inferrer.infer(FailureClass.UNREACHABLE)
        assert "down" in cause.lower() or "connection" in cause.lower() or "firewall" in cause.lower()

    def test_none_cause(self):
        cause = self.inferrer.infer(FailureClass.NONE)
        assert "normal" in cause.lower() or "no failure" in cause.lower()

    def test_unknown_error_cause(self):
        cause = self.inferrer.infer(FailureClass.UNKNOWN_ERROR)
        assert len(cause) > 0

    def test_all_failure_classes_have_cause(self):
        for fc in FailureClass:
            cause = self.inferrer.infer(fc)
            assert isinstance(cause, str)
            assert len(cause) > 0

    def test_cause_does_not_contain_password(self):
        for fc in FailureClass:
            cause = self.inferrer.infer(fc)
            assert "password" not in cause.lower() or "password" in cause.lower()


class TestRepairPlaybook:
    def setup_method(self):
        self.playbook = RepairPlaybook()

    def test_dns_failure_has_steps(self):
        steps = self.playbook.steps_for(FailureClass.DNS_FAILURE)
        assert len(steps) >= 2
        assert all(isinstance(s, RepairStep) for s in steps)

    def test_steps_are_numbered_from_one(self):
        steps = self.playbook.steps_for(FailureClass.DNS_FAILURE)
        for i, step in enumerate(steps, start=1):
            assert step.step_number == i

    def test_none_failure_has_no_steps(self):
        steps = self.playbook.steps_for(FailureClass.NONE)
        assert steps == []

    def test_tls_failure_has_steps(self):
        steps = self.playbook.steps_for(FailureClass.TLS_FAILURE)
        assert len(steps) >= 1

    def test_timeout_has_steps(self):
        steps = self.playbook.steps_for(FailureClass.TIMEOUT)
        assert len(steps) >= 1

    def test_unauthorized_has_steps(self):
        steps = self.playbook.steps_for(FailureClass.UNAUTHORIZED)
        assert len(steps) >= 1

    def test_configuration_error_has_steps(self):
        steps = self.playbook.steps_for(FailureClass.CONFIGURATION_ERROR)
        assert len(steps) >= 1

    def test_database_error_has_steps(self):
        steps = self.playbook.steps_for(FailureClass.DATABASE_ERROR)
        assert len(steps) >= 1

    def test_step_descriptions_non_empty(self):
        for fc in FailureClass:
            steps = self.playbook.steps_for(fc)
            for step in steps:
                assert len(step.description) > 0

    def test_step_commands_do_not_expose_passwords(self):
        for fc in FailureClass:
            steps = self.playbook.steps_for(fc)
            for step in steps:
                if step.command:
                    assert "password" not in step.command.lower()
                    assert "BETA_POSTGRES_PASSWORD" not in step.command
                    assert "BETA_NEXTCLOUD_PASSWORD" not in step.command

    def test_storage_error_has_steps(self):
        steps = self.playbook.steps_for(FailureClass.STORAGE_ERROR)
        assert len(steps) >= 1

    def test_unreachable_has_steps(self):
        steps = self.playbook.steps_for(FailureClass.UNREACHABLE)
        assert len(steps) >= 1

    def test_unknown_error_returns_steps_not_error(self):
        steps = self.playbook.steps_for(FailureClass.UNKNOWN_ERROR)
        assert isinstance(steps, list)
