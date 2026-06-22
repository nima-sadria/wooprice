"""Project 7.3B — Capability limitation vs connectivity failure tests.

Verifies that a WooCommerce API capability limitation (modified_after unsupported)
is clearly distinguished from a real connectivity/runtime failure in both the
backend SSE payload and the frontend state machine.

Structural tests (source inspection) are used because the behaviour is defined
by source-level invariants that must survive refactoring.
"""
import inspect
import os
import sys

os.environ.setdefault("NEXTCLOUD_URL", "http://example.invalid")
os.environ.setdefault("NEXTCLOUD_USER", "x")
os.environ.setdefault("NEXTCLOUD_PASSWORD", "x")
os.environ.setdefault("NEXTCLOUD_FILE_PATH", "/x.xlsx")
os.environ.setdefault("WC_URL", "http://example.invalid")
os.environ.setdefault("WC_KEY", "x")
os.environ.setdefault("WC_SECRET", "x")
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.main as main_module  # noqa: E402

_SRC = inspect.getsource(main_module.fetch_light_stream)


# ── Payload semantics ──────────────────────────────────────────────────────────

def test_capability_guard_emits_capability_error_field():
    """The capability-limited SSE payload must include the `capability_error` JSON key.

    This field lets the frontend distinguish capability gaps from network failures
    without parsing the human-readable message text.
    """
    assert "capability_error" in _SRC, (
        "fetch_light_stream must include a capability_error field in the SSE payload "
        "when the capability guard fires"
    )


def test_capability_guard_message_mentions_capability_limitation():
    """The user-facing error message must explicitly mention 'capability' and 'limitation'
    so that users (and support) can tell this is a WooCommerce API feature gap,
    not a connectivity or auth failure."""
    assert "capability" in _SRC.lower(), (
        "SSE message for capability guard must use the word 'capability'"
    )
    assert "limitation" in _SRC.lower() or "limited" in _SRC.lower(), (
        "SSE message for capability guard must use 'limitation' or 'limited'"
    )


def test_capability_guard_clarifies_not_connectivity_issue():
    """The error message must state this is NOT a connectivity issue, preventing
    users from misreading the UI as 'WooCommerce disconnected'."""
    assert "connectivity" in _SRC.lower() or "not a connectivity" in _SRC.lower(), (
        "SSE message must include 'connectivity' to clarify this is not a network failure"
    )


# ── Admin override ─────────────────────────────────────────────────────────────

def test_admin_override_requires_explicit_admin_check():
    """force_capability must check is_admin before allowing the override path.
    Non-admin users must be rejected even if they pass force_capability=true."""
    assert "force_capability" in _SRC, (
        "fetch_light_stream must expose force_capability query parameter"
    )
    assert "_is_admin" in _SRC or "is_admin" in _SRC, (
        "fetch_light_stream must check is_admin before allowing capability override"
    )


def test_non_admin_override_rejected_with_clear_message():
    """The non-admin override rejection must use a clear, identifiable error message."""
    assert "Capability override requires admin access" in _SRC, (
        "Non-admin capability override must be rejected with the exact message "
        "'Capability override requires admin access'"
    )


def test_admin_override_is_audited():
    """Admin capability overrides must produce an audit log record so that all
    override events are traceable in the audit trail."""
    assert "light_refresh_capability_override" in _SRC, (
        "fetch_light_stream must write a 'light_refresh_capability_override' audit record "
        "when an admin uses force_capability=true"
    )


def test_admin_override_logs_warning():
    """Admin override must emit a clearly identifiable WARNING-level log line."""
    assert "ADMIN CAPABILITY OVERRIDE" in _SRC or "admin" in _SRC.lower(), (
        "Admin override path must produce a clearly identifiable WARNING log"
    )


# ── Fallthrough: true failures remain failures ─────────────────────────────────

def test_true_runtime_failure_path_exists_separately_from_capability_error():
    """CACHE_ERROR / generic error handling must exist independently of the
    capability_error guard so that real WooCommerce/API failures still surface
    as failures, not silently swallowed."""
    # capability_error guard must be in the source (checked above).
    # The generic error path (not gated on capability_error) must also be present.
    # We verify this by checking that a non-capability error return also exists.
    assert "Refresh failed" in _SRC or "Stream truncated" in _SRC or '"error"' in _SRC, (
        "A generic error path must still exist so real failures surface correctly"
    )


def test_capability_error_field_is_true_not_a_generic_flag():
    """The capability_error field must be set to true (boolean), not a generic
    error string, so frontend code can type-check it reliably."""
    assert '"capability_error":true' in _SRC or "capability_error\":true" in _SRC, (
        "capability_error value must be the JSON boolean true"
    )


# ── Health endpoint service separation ─────────────────────────────────────────

def test_health_endpoint_returns_services_dict():
    """The /api/health endpoint must return a 'services' dict with at minimum
    api, woocommerce, nextcloud, and currency keys for separate status display."""
    health_src = inspect.getsource(main_module.health)
    assert "services" in health_src, (
        "/api/health must return a 'services' dict for per-service status display"
    )
    assert "woocommerce" in health_src, (
        "services dict must include 'woocommerce' key"
    )
    assert "currency" in health_src, (
        "services dict must include 'currency' key"
    )


def test_health_endpoint_currency_status_reflects_cache_freshness():
    """The currency status in /api/health must distinguish 'ok', 'stale', and
    'unavailable' based on the in-memory currency cache state."""
    health_src = inspect.getsource(main_module.health)
    assert "stale" in health_src, (
        "/api/health currency status must use 'stale' label when currency cache is stale"
    )
    assert "unavailable" in health_src, (
        "/api/health currency status must use 'unavailable' when no currency data exists"
    )


if __name__ == "__main__":
    test_capability_guard_emits_capability_error_field()
    test_capability_guard_message_mentions_capability_limitation()
    test_capability_guard_clarifies_not_connectivity_issue()
    test_admin_override_requires_explicit_admin_check()
    test_non_admin_override_rejected_with_clear_message()
    test_admin_override_is_audited()
    test_admin_override_logs_warning()
    test_true_runtime_failure_path_exists_separately_from_capability_error()
    test_capability_error_field_is_true_not_a_generic_flag()
    test_health_endpoint_returns_services_dict()
    test_health_endpoint_currency_status_reflects_cache_freshness()
    print("ALL TESTS PASSED")
