"""Tests for app.beta.control_plane.failure — FailureClass and Severity."""

import json

import pytest

from app.beta.control_plane.failure import FailureClass, FailureClassMeta, Severity

# All 16 FailureClass values
ALL_FAILURE_CLASSES = [
    FailureClass.NONE,
    FailureClass.DNS_FAILURE,
    FailureClass.TCP_FAILURE,
    FailureClass.TLS_FAILURE,
    FailureClass.TIMEOUT,
    FailureClass.UNAUTHORIZED,
    FailureClass.FORBIDDEN,
    FailureClass.UNREACHABLE,
    FailureClass.INVALID_RESPONSE,
    FailureClass.CONFIGURATION_ERROR,
    FailureClass.PERMISSION_ERROR,
    FailureClass.STORAGE_ERROR,
    FailureClass.DATABASE_ERROR,
    FailureClass.DOCKER_ERROR,
    FailureClass.PLUGIN_ERROR,
    FailureClass.UNKNOWN_ERROR,
]


class TestFailureClassCoverage:
    def test_all_16_values_defined(self):
        assert len(ALL_FAILURE_CLASSES) == 16

    def test_all_members_match_enum(self):
        enum_members = set(FailureClass)
        assert set(ALL_FAILURE_CLASSES) == enum_members

    @pytest.mark.parametrize("fc", ALL_FAILURE_CLASSES)
    def test_each_has_meta(self, fc: FailureClass):
        meta = fc.meta
        assert isinstance(meta, FailureClassMeta)

    @pytest.mark.parametrize("fc", ALL_FAILURE_CLASSES)
    def test_each_has_nonempty_code(self, fc: FailureClass):
        assert fc.meta.code == fc.value
        assert len(fc.meta.code) > 0

    @pytest.mark.parametrize("fc", ALL_FAILURE_CLASSES)
    def test_each_has_nonempty_label(self, fc: FailureClass):
        assert len(fc.label) > 0

    @pytest.mark.parametrize("fc", ALL_FAILURE_CLASSES)
    def test_each_has_severity_default(self, fc: FailureClass):
        assert isinstance(fc.severity_default, Severity)

    @pytest.mark.parametrize("fc", ALL_FAILURE_CLASSES)
    def test_each_has_nonempty_user_message(self, fc: FailureClass):
        assert len(fc.user_message) > 0

    @pytest.mark.parametrize("fc", ALL_FAILURE_CLASSES)
    def test_each_has_nonempty_operator_hint(self, fc: FailureClass):
        assert len(fc.operator_hint) > 0

    @pytest.mark.parametrize("fc", ALL_FAILURE_CLASSES)
    def test_retryable_is_bool(self, fc: FailureClass):
        assert isinstance(fc.retryable, bool)

    @pytest.mark.parametrize("fc", ALL_FAILURE_CLASSES)
    def test_security_sensitive_is_bool(self, fc: FailureClass):
        assert isinstance(fc.security_sensitive, bool)


class TestFailureClassRetryable:
    def test_none_is_not_retryable(self):
        assert FailureClass.NONE.retryable is False

    def test_dns_failure_is_not_retryable(self):
        # DNS failures need config change, not retry
        assert FailureClass.DNS_FAILURE.retryable is False

    def test_tcp_failure_is_retryable(self):
        assert FailureClass.TCP_FAILURE.retryable is True

    def test_tls_failure_is_not_retryable(self):
        # TLS cert problems need manual fix
        assert FailureClass.TLS_FAILURE.retryable is False

    def test_timeout_is_retryable(self):
        assert FailureClass.TIMEOUT.retryable is True

    def test_unauthorized_is_not_retryable(self):
        # Wrong credentials need config change, not retry
        assert FailureClass.UNAUTHORIZED.retryable is False

    def test_forbidden_is_not_retryable(self):
        assert FailureClass.FORBIDDEN.retryable is False

    def test_unreachable_is_retryable(self):
        assert FailureClass.UNREACHABLE.retryable is True

    def test_invalid_response_is_not_retryable(self):
        assert FailureClass.INVALID_RESPONSE.retryable is False

    def test_configuration_error_is_not_retryable(self):
        assert FailureClass.CONFIGURATION_ERROR.retryable is False

    def test_database_error_is_retryable(self):
        assert FailureClass.DATABASE_ERROR.retryable is True

    def test_docker_error_is_retryable(self):
        assert FailureClass.DOCKER_ERROR.retryable is True


class TestFailureClassSecuritySensitive:
    def test_none_is_not_security_sensitive(self):
        assert FailureClass.NONE.security_sensitive is False

    def test_dns_failure_is_not_security_sensitive(self):
        assert FailureClass.DNS_FAILURE.security_sensitive is False

    def test_unauthorized_is_security_sensitive(self):
        assert FailureClass.UNAUTHORIZED.security_sensitive is True

    def test_forbidden_is_security_sensitive(self):
        assert FailureClass.FORBIDDEN.security_sensitive is True

    def test_configuration_error_is_not_security_sensitive(self):
        # Config errors expose structure, not credentials
        assert FailureClass.CONFIGURATION_ERROR.security_sensitive is False

    def test_tls_failure_is_not_security_sensitive(self):
        assert FailureClass.TLS_FAILURE.security_sensitive is False

    def test_timeout_is_not_security_sensitive(self):
        assert FailureClass.TIMEOUT.security_sensitive is False


class TestFailureClassSeverity:
    def test_none_is_info(self):
        assert FailureClass.NONE.severity_default == Severity.INFO

    def test_dns_failure_is_error(self):
        assert FailureClass.DNS_FAILURE.severity_default == Severity.ERROR

    def test_tls_failure_is_error(self):
        assert FailureClass.TLS_FAILURE.severity_default == Severity.ERROR

    def test_timeout_is_warning(self):
        # Timeout may be transient — starts as WARNING
        assert FailureClass.TIMEOUT.severity_default == Severity.WARNING

    def test_unauthorized_is_error(self):
        assert FailureClass.UNAUTHORIZED.severity_default == Severity.ERROR

    def test_configuration_error_is_critical(self):
        assert FailureClass.CONFIGURATION_ERROR.severity_default == Severity.CRITICAL

    def test_storage_error_is_critical(self):
        assert FailureClass.STORAGE_ERROR.severity_default == Severity.CRITICAL

    def test_database_error_is_critical(self):
        assert FailureClass.DATABASE_ERROR.severity_default == Severity.CRITICAL

    def test_plugin_error_is_warning(self):
        # Plugin failure is recoverable; does not block core features
        assert FailureClass.PLUGIN_ERROR.severity_default == Severity.WARNING


class TestFailureClassAsString:
    def test_value_is_machine_code(self):
        assert FailureClass.DNS_FAILURE.value == "dns_failure"
        assert FailureClass.TLS_FAILURE.value == "tls_failure"
        assert FailureClass.UNAUTHORIZED.value == "unauthorized"
        assert FailureClass.NONE.value == "none"

    def test_is_json_serialisable(self):
        payload = {"failure_class": FailureClass.DNS_FAILURE.value}
        serialised = json.dumps(payload)
        assert "dns_failure" in serialised

    def test_roundtrip_from_value(self):
        for fc in FailureClass:
            assert FailureClass(fc.value) is fc


class TestSeverityOrdering:
    def test_info_less_than_warning(self):
        assert Severity.INFO < Severity.WARNING

    def test_warning_less_than_degraded(self):
        assert Severity.WARNING < Severity.DEGRADED

    def test_degraded_less_than_error(self):
        assert Severity.DEGRADED < Severity.ERROR

    def test_error_less_than_critical(self):
        assert Severity.ERROR < Severity.CRITICAL

    def test_info_less_than_critical(self):
        assert Severity.INFO < Severity.CRITICAL

    def test_critical_greater_than_all(self):
        for s in Severity:
            if s != Severity.CRITICAL:
                assert Severity.CRITICAL > s

    def test_info_less_than_or_equal_info(self):
        assert Severity.INFO <= Severity.INFO

    def test_critical_greater_than_or_equal_critical(self):
        assert Severity.CRITICAL >= Severity.CRITICAL

    def test_not_less_than_self(self):
        for s in Severity:
            assert not (s < s)

    def test_total_order_consistent(self):
        ordered = [Severity.INFO, Severity.WARNING, Severity.DEGRADED, Severity.ERROR, Severity.CRITICAL]
        for i in range(len(ordered) - 1):
            assert ordered[i] < ordered[i + 1]
            assert ordered[i + 1] > ordered[i]


class TestSeverityHighest:
    def test_empty_returns_info(self):
        assert Severity.highest([]) == Severity.INFO

    def test_single_returns_itself(self):
        assert Severity.highest([Severity.ERROR]) == Severity.ERROR

    def test_returns_highest_of_mixed(self):
        result = Severity.highest([Severity.INFO, Severity.CRITICAL, Severity.WARNING])
        assert result == Severity.CRITICAL

    def test_all_same_returns_that_level(self):
        assert Severity.highest([Severity.DEGRADED, Severity.DEGRADED]) == Severity.DEGRADED

    def test_generator_input(self):
        gen = (s for s in [Severity.WARNING, Severity.ERROR])
        assert Severity.highest(gen) == Severity.ERROR

    def test_severity_value_is_string(self):
        assert Severity.ERROR.value == "error"
        assert Severity.CRITICAL.value == "critical"

    def test_severity_is_json_serialisable(self):
        payload = {"severity": Severity.CRITICAL.value}
        assert json.dumps(payload) == '{"severity": "critical"}'
