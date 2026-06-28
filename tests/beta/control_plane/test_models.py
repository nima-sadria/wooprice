"""Tests for app.beta.control_plane.models — IntegrationState."""

import json
from datetime import datetime, timezone

import pytest

from app.beta.control_plane.failure import FailureClass, Severity
from app.beta.control_plane.models import IntegrationState, IntegrationType

FIXED_TS = datetime(2026, 6, 28, 12, 0, 0, tzinfo=timezone.utc)
FIXED_TS_ISO = "2026-06-28T12:00:00+00:00"

_SECRET_PATTERNS = [
    "password", "secret", "token", "key", "credential",
    "nc_pass", "cs_test", "ck_test", "jwt",
]


class TestIntegrationStateCreateOk:
    def test_returns_operational_state(self):
        state = IntegrationState.create_ok("nextcloud", IntegrationType.NEXTCLOUD)
        assert state.is_operational() is True
        assert state.is_failing() is False

    def test_fields_populated(self):
        state = IntegrationState.create_ok(
            "nextcloud", IntegrationType.NEXTCLOUD, checked_at=FIXED_TS
        )
        assert state.name == "nextcloud"
        assert state.integration_type == IntegrationType.NEXTCLOUD
        assert state.enabled is True
        assert state.configured is True
        assert state.reachable is True
        assert state.authenticated is True
        assert state.failure_class == FailureClass.NONE
        assert state.severity == Severity.INFO
        assert state.last_success_at == FIXED_TS
        assert state.last_checked_at == FIXED_TS

    def test_message_contains_no_secrets(self):
        state = IntegrationState.create_ok("nextcloud", IntegrationType.NEXTCLOUD)
        low = state.message.lower()
        for pat in _SECRET_PATTERNS:
            assert pat not in low, f"Secret pattern '{pat}' found in message"

    def test_repair_hint_empty_when_ok(self):
        state = IntegrationState.create_ok("nextcloud", IntegrationType.NEXTCLOUD)
        assert state.repair_hint == ""


class TestIntegrationStateCreateFailing:
    def test_dns_failure_marks_not_reachable(self):
        state = IntegrationState.create_failing(
            "nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE
        )
        assert state.is_failing() is True
        assert state.is_operational() is False
        assert state.reachable is False
        assert state.failure_class == FailureClass.DNS_FAILURE
        assert state.severity == Severity.ERROR

    def test_tls_failure_reachable_is_none(self):
        state = IntegrationState.create_failing(
            "nextcloud", IntegrationType.NEXTCLOUD, FailureClass.TLS_FAILURE
        )
        assert state.is_failing() is True
        # TLS: TCP connected but handshake failed — reachability is ambiguous
        assert state.reachable is None
        assert state.failure_class == FailureClass.TLS_FAILURE

    def test_unauthorized_marks_reachable_true(self):
        state = IntegrationState.create_failing(
            "nextcloud", IntegrationType.NEXTCLOUD, FailureClass.UNAUTHORIZED
        )
        assert state.is_failing() is True
        assert state.reachable is True  # network reached; auth failed
        assert state.failure_class == FailureClass.UNAUTHORIZED
        assert state.severity == Severity.ERROR

    def test_timeout_marks_not_reachable(self):
        state = IntegrationState.create_failing(
            "nextcloud", IntegrationType.NEXTCLOUD, FailureClass.TIMEOUT
        )
        assert state.reachable is False

    def test_custom_message_overrides_default(self):
        state = IntegrationState.create_failing(
            "woocommerce",
            IntegrationType.WOOCOMMERCE,
            FailureClass.DNS_FAILURE,
            message="Custom operator message",
        )
        assert state.message == "Custom operator message"

    def test_default_message_from_failure_class(self):
        state = IntegrationState.create_failing(
            "woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.DNS_FAILURE
        )
        assert state.message == FailureClass.DNS_FAILURE.user_message

    def test_repair_hint_from_failure_class(self):
        state = IntegrationState.create_failing(
            "woocommerce", IntegrationType.WOOCOMMERCE, FailureClass.DNS_FAILURE
        )
        assert state.repair_hint == FailureClass.DNS_FAILURE.operator_hint

    def test_last_success_at_preserved(self):
        state = IntegrationState.create_failing(
            "nextcloud",
            IntegrationType.NEXTCLOUD,
            FailureClass.TIMEOUT,
            last_success_at=FIXED_TS,
        )
        assert state.last_success_at == FIXED_TS

    def test_last_success_at_none_by_default(self):
        state = IntegrationState.create_failing(
            "nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE
        )
        assert state.last_success_at is None


class TestIntegrationStateOperationalLogic:
    def test_disabled_integration_is_not_failing(self):
        state = IntegrationState(
            name="nextcloud",
            integration_type=IntegrationType.NEXTCLOUD,
            enabled=False,
            configured=True,
            reachable=False,
            authenticated=None,
            last_success_at=None,
            last_checked_at=FIXED_TS,
            failure_class=FailureClass.DNS_FAILURE,
            severity=Severity.ERROR,
            message="unreachable",
            repair_hint="check dns",
        )
        assert state.is_failing() is False

    def test_unchecked_integration_is_not_failing(self):
        """None values (not yet checked) must not trigger failing state."""
        state = IntegrationState(
            name="nextcloud",
            integration_type=IntegrationType.NEXTCLOUD,
            enabled=True,
            configured=True,
            reachable=None,
            authenticated=None,
            last_success_at=None,
            last_checked_at=None,
            failure_class=FailureClass.NONE,
            severity=Severity.INFO,
            message="Not yet checked.",
            repair_hint="",
        )
        assert state.is_failing() is False
        assert state.is_operational() is False  # not checked = not confirmed operational

    def test_misconfigured_integration_is_failing(self):
        state = IntegrationState(
            name="nextcloud",
            integration_type=IntegrationType.NEXTCLOUD,
            enabled=True,
            configured=False,
            reachable=None,
            authenticated=None,
            last_success_at=None,
            last_checked_at=FIXED_TS,
            failure_class=FailureClass.CONFIGURATION_ERROR,
            severity=Severity.CRITICAL,
            message="Missing URL.",
            repair_hint="set BETA_NEXTCLOUD_URL",
        )
        assert state.is_failing() is True

    def test_auth_false_makes_failing(self):
        state = IntegrationState(
            name="nextcloud",
            integration_type=IntegrationType.NEXTCLOUD,
            enabled=True,
            configured=True,
            reachable=True,
            authenticated=False,
            last_success_at=None,
            last_checked_at=FIXED_TS,
            failure_class=FailureClass.UNAUTHORIZED,
            severity=Severity.ERROR,
            message="Credentials rejected.",
            repair_hint="check password",
        )
        assert state.is_failing() is True
        assert state.is_operational() is False


class TestIntegrationStateSerialization:
    def test_to_dict_roundtrip(self):
        state = IntegrationState.create_ok("nextcloud", IntegrationType.NEXTCLOUD, FIXED_TS)
        restored = IntegrationState.from_dict(state.to_dict())
        assert restored.name == state.name
        assert restored.integration_type == state.integration_type
        assert restored.enabled == state.enabled
        assert restored.configured == state.configured
        assert restored.reachable == state.reachable
        assert restored.authenticated == state.authenticated
        assert restored.failure_class == state.failure_class
        assert restored.severity == state.severity
        assert restored.message == state.message
        assert restored.repair_hint == state.repair_hint

    def test_to_dict_for_failing_state(self):
        state = IntegrationState.create_failing(
            "nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE,
            checked_at=FIXED_TS,
        )
        restored = IntegrationState.from_dict(state.to_dict())
        assert restored.failure_class == FailureClass.DNS_FAILURE
        assert restored.is_failing() is True

    def test_to_dict_is_json_serialisable(self):
        state = IntegrationState.create_ok("nextcloud", IntegrationType.NEXTCLOUD, FIXED_TS)
        json.dumps(state.to_dict())  # must not raise

    def test_to_dict_enum_values_are_strings(self):
        state = IntegrationState.create_ok("nextcloud", IntegrationType.NEXTCLOUD)
        d = state.to_dict()
        assert isinstance(d["integration_type"], str)
        assert isinstance(d["failure_class"], str)
        assert isinstance(d["severity"], str)

    def test_to_dict_no_secrets(self):
        state = IntegrationState.create_ok("nextcloud", IntegrationType.NEXTCLOUD)
        serialised = json.dumps(state.to_dict()).lower()
        for pat in _SECRET_PATTERNS:
            assert pat not in serialised, f"Secret pattern '{pat}' found in serialised output"

    def test_from_dict_with_none_timestamps(self):
        state = IntegrationState.create_failing(
            "nextcloud", IntegrationType.NEXTCLOUD, FailureClass.DNS_FAILURE
        )
        d = state.to_dict()
        assert d["last_success_at"] is None
        restored = IntegrationState.from_dict(d)
        assert restored.last_success_at is None
