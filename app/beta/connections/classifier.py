"""CP1.2 — Exception-to-FailureClass classifier.

All exception classification within CP1 routes through this module.
No other module may independently classify network exceptions (per spec).
"""

from __future__ import annotations

import socket
import ssl

from app.beta.control_plane.failure import FailureClass

from .adapters import (
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

# Retryable failure classes (from spec §5.1)
RETRYABLE_FAILURE_CLASSES: frozenset[FailureClass] = frozenset(
    {
        FailureClass.TIMEOUT,
        FailureClass.UNREACHABLE,
    }
)


def classify_exception(exc: Exception) -> FailureClass:
    """Map an exception to the canonical FailureClass.

    Handles both the custom adapter exception hierarchy and standard Python
    network exceptions that a real adapter implementation might surface.
    """
    # Custom adapter hierarchy (used by FakeNetworkAdapter in tests and any
    # real adapter that wraps its exceptions explicitly)
    if isinstance(exc, DNSResolutionError):
        return FailureClass.DNS_FAILURE
    if isinstance(exc, TLSHandshakeError):
        return FailureClass.TLS_FAILURE
    if isinstance(exc, ConnectionTimeoutError):
        return FailureClass.TIMEOUT
    if isinstance(exc, (TCPConnectionError, ConnectionUnreachableError)):
        return FailureClass.UNREACHABLE
    if isinstance(exc, AuthenticationError):
        return FailureClass.UNAUTHORIZED
    if isinstance(exc, AccessForbiddenError):
        return FailureClass.FORBIDDEN
    if isinstance(exc, InvalidResponseError):
        return FailureClass.INVALID_RESPONSE
    if isinstance(exc, StorageAdapterError):
        return FailureClass.STORAGE_ERROR
    if isinstance(exc, DatabaseAdapterError):
        return FailureClass.DATABASE_ERROR
    if isinstance(exc, DockerAdapterError):
        return FailureClass.DOCKER_ERROR

    # Standard Python network exceptions (surfaced by a real adapter that
    # wraps socket/ssl/httpx calls without re-raising custom types)
    if isinstance(exc, socket.gaierror):
        return FailureClass.DNS_FAILURE
    if isinstance(exc, ssl.SSLError):
        return FailureClass.TLS_FAILURE
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return FailureClass.TIMEOUT
    if isinstance(exc, ConnectionRefusedError):
        return FailureClass.UNREACHABLE
    if isinstance(exc, OSError):
        return FailureClass.UNREACHABLE

    return FailureClass.UNKNOWN_ERROR


def classify_http_response(status_code: int) -> FailureClass:
    """Map an HTTP status code to a FailureClass.

    Returns FailureClass.NONE for 2xx responses (success).
    """
    if 200 <= status_code < 300:
        return FailureClass.NONE
    if status_code == 401:
        return FailureClass.UNAUTHORIZED
    if status_code == 403:
        return FailureClass.FORBIDDEN
    if status_code >= 400:
        return FailureClass.INVALID_RESPONSE
    return FailureClass.UNKNOWN_ERROR


def is_retryable(failure_class: FailureClass) -> bool:
    """Return True if a failure class warrants a retry attempt."""
    return failure_class in RETRYABLE_FAILURE_CLASSES
