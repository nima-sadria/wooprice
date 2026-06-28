"""Tests for failure classifier — exception → FailureClass mapping."""

from __future__ import annotations

import socket
import ssl

import pytest

from app.beta.connections.adapters import (
    AccessForbiddenError,
    AuthenticationError,
    ConnectionTimeoutError,
    ConnectionUnreachableError,
    DatabaseAdapterError,
    DNSResolutionError,
    DockerAdapterError,
    InvalidResponseError,
    StorageAdapterError,
    TCPConnectionError,
    TLSHandshakeError,
)
from app.beta.connections.classifier import (
    classify_exception,
    classify_http_response,
    is_retryable,
)
from app.beta.control_plane.failure import FailureClass


# ---------------------------------------------------------------------------
# classify_exception — custom exception hierarchy
# ---------------------------------------------------------------------------


def test_classify_dns_resolution_error():
    assert classify_exception(DNSResolutionError("nxdomain")) == FailureClass.DNS_FAILURE


def test_classify_tls_handshake_error():
    assert classify_exception(TLSHandshakeError("cert verify failed")) == FailureClass.TLS_FAILURE


def test_classify_connection_timeout_error():
    assert classify_exception(ConnectionTimeoutError("timed out")) == FailureClass.TIMEOUT


def test_classify_tcp_connection_error():
    assert classify_exception(TCPConnectionError("refused")) == FailureClass.UNREACHABLE


def test_classify_connection_unreachable_error():
    assert classify_exception(ConnectionUnreachableError("no route")) == FailureClass.UNREACHABLE


def test_classify_authentication_error():
    assert classify_exception(AuthenticationError("401")) == FailureClass.UNAUTHORIZED


def test_classify_access_forbidden_error():
    assert classify_exception(AccessForbiddenError("403")) == FailureClass.FORBIDDEN


def test_classify_invalid_response_error():
    assert classify_exception(InvalidResponseError("unexpected body")) == FailureClass.INVALID_RESPONSE


def test_classify_storage_adapter_error():
    assert classify_exception(StorageAdapterError("disk full")) == FailureClass.STORAGE_ERROR


def test_classify_database_adapter_error():
    assert classify_exception(DatabaseAdapterError("pg down")) == FailureClass.DATABASE_ERROR


def test_classify_docker_adapter_error():
    assert classify_exception(DockerAdapterError("daemon not running")) == FailureClass.DOCKER_ERROR


# ---------------------------------------------------------------------------
# classify_exception — standard Python exceptions
# ---------------------------------------------------------------------------


def test_classify_socket_gaierror():
    exc = socket.gaierror(8, "Name or service not known")
    assert classify_exception(exc) == FailureClass.DNS_FAILURE


def test_classify_ssl_error():
    exc = ssl.SSLError("CERTIFICATE_VERIFY_FAILED")
    assert classify_exception(exc) == FailureClass.TLS_FAILURE


def test_classify_timeout_error():
    assert classify_exception(TimeoutError("timed out")) == FailureClass.TIMEOUT


def test_classify_socket_timeout():
    assert classify_exception(socket.timeout("timed out")) == FailureClass.TIMEOUT


def test_classify_connection_refused_error():
    assert classify_exception(ConnectionRefusedError("refused")) == FailureClass.UNREACHABLE


def test_classify_unknown_exception():
    assert classify_exception(RuntimeError("unknown")) == FailureClass.UNKNOWN_ERROR


def test_classify_value_error():
    assert classify_exception(ValueError("unexpected")) == FailureClass.UNKNOWN_ERROR


# ---------------------------------------------------------------------------
# classify_http_response
# ---------------------------------------------------------------------------


def test_classify_http_200_is_none():
    assert classify_http_response(200) == FailureClass.NONE


def test_classify_http_201_is_none():
    assert classify_http_response(201) == FailureClass.NONE


def test_classify_http_204_is_none():
    assert classify_http_response(204) == FailureClass.NONE


def test_classify_http_401_is_unauthorized():
    assert classify_http_response(401) == FailureClass.UNAUTHORIZED


def test_classify_http_403_is_forbidden():
    assert classify_http_response(403) == FailureClass.FORBIDDEN


def test_classify_http_404_is_invalid_response():
    assert classify_http_response(404) == FailureClass.INVALID_RESPONSE


def test_classify_http_500_is_invalid_response():
    assert classify_http_response(500) == FailureClass.INVALID_RESPONSE


def test_classify_http_503_is_invalid_response():
    assert classify_http_response(503) == FailureClass.INVALID_RESPONSE


# ---------------------------------------------------------------------------
# is_retryable
# ---------------------------------------------------------------------------


def test_timeout_is_retryable():
    assert is_retryable(FailureClass.TIMEOUT) is True


def test_unreachable_is_retryable():
    assert is_retryable(FailureClass.UNREACHABLE) is True


def test_dns_failure_not_retryable():
    assert is_retryable(FailureClass.DNS_FAILURE) is False


def test_tls_failure_not_retryable():
    assert is_retryable(FailureClass.TLS_FAILURE) is False


def test_unauthorized_not_retryable():
    assert is_retryable(FailureClass.UNAUTHORIZED) is False


def test_forbidden_not_retryable():
    assert is_retryable(FailureClass.FORBIDDEN) is False


def test_invalid_response_not_retryable():
    assert is_retryable(FailureClass.INVALID_RESPONSE) is False


def test_none_not_retryable():
    assert is_retryable(FailureClass.NONE) is False
