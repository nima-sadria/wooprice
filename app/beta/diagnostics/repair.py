"""CP1.3 — Repair playbook: probable cause inference and repair step generation."""

from __future__ import annotations

from app.beta.control_plane.failure import FailureClass

from .report import RepairStep


_PLAYBOOKS: dict[str, list[dict]] = {
    "dns_failure": [
        {
            "description": "Verify the service URL is correctly configured",
            "command": "wooprice configure show",
        },
        {
            "description": "Correct the URL if wrong",
            "command": "wooprice configure set BETA_NEXTCLOUD_URL https://correct-host.example.com",
        },
        {
            "description": "Test DNS from the server",
            "command": "nslookup <hostname>",
            "detail": "If DNS fails here, the hostname does not resolve from this server's network.",
        },
        {
            "description": "Retest after changes",
            "command": "wooprice integrations test <service>",
        },
    ],
    "tls_failure": [
        {
            "description": "Check certificate expiry date",
            "detail": "Run: echo | openssl s_client -connect <host>:443 2>/dev/null | openssl x509 -noout -dates",
        },
        {
            "description": "Verify the certificate is issued for the correct hostname",
        },
        {
            "description": "If using a self-signed certificate, add it to the trusted store",
        },
        {
            "description": "Retest after resolving the certificate issue",
            "command": "wooprice integrations test <service>",
        },
    ],
    "timeout": [
        {
            "description": "Check service availability from the server",
            "command": "curl -v --max-time 10 <url>",
        },
        {
            "description": "Check for firewall rules that may be silently dropping packets",
        },
        {
            "description": "Consider increasing the connection timeout",
            "command": "wooprice configure set BETA_NEXTCLOUD_URL <url>",
        },
        {
            "description": "Retest after resolving the network issue",
            "command": "wooprice integrations test <service>",
        },
    ],
    "unauthorized": [
        {
            "description": "Verify credentials in configuration (values are redacted in output)",
            "command": "wooprice configure show",
            "detail": "Check the actual .env file to confirm the credential values are correct.",
        },
        {
            "description": "Confirm the account is active and not locked on the remote service",
        },
        {
            "description": "Retest after correcting credentials",
            "command": "wooprice integrations test <service>",
        },
    ],
    "forbidden": [
        {
            "description": "Verify the account has the required permissions on the remote service",
        },
        {
            "description": "Check that API access is enabled for this account",
        },
        {
            "description": "Retest after permission changes",
            "command": "wooprice integrations test <service>",
        },
    ],
    "unreachable": [
        {
            "description": "Verify the service is running",
            "detail": "Check the remote service dashboard or server status page.",
        },
        {
            "description": "Verify network routing from this server to the service host",
        },
        {
            "description": "Check firewall rules for the configured port",
        },
        {
            "description": "Retest after resolving the network issue",
            "command": "wooprice integrations test <service>",
        },
    ],
    "tcp_failure": [
        {
            "description": "Verify the service is listening on the configured port",
        },
        {
            "description": "Check firewall rules for the configured port",
        },
        {
            "description": "Retest after resolving the port/firewall issue",
            "command": "wooprice integrations test <service>",
        },
    ],
    "invalid_response": [
        {
            "description": "Verify the service URL and path are correct",
            "command": "wooprice configure show",
        },
        {
            "description": "Test the URL manually",
            "command": "curl -v <url>",
        },
        {
            "description": "The API endpoint may have changed — check service documentation",
        },
        {
            "description": "Retest after correction",
            "command": "wooprice integrations test <service>",
        },
    ],
    "configuration_error": [
        {
            "description": "Validate the full configuration",
            "command": "wooprice configure verify",
        },
        {
            "description": "Correct missing or invalid fields",
            "command": "wooprice configure set <FIELD> <value>",
        },
        {
            "description": "Retest after correction",
            "command": "wooprice diagnostics run",
        },
    ],
    "permission_error": [
        {
            "description": "Check file permissions on the storage path",
            "command": "ls -la $BETA_STORAGE_PATH",
        },
        {
            "description": "Correct ownership for the application user",
            "command": "chown -R <app_user>: $BETA_STORAGE_PATH",
        },
    ],
    "storage_error": [
        {
            "description": "Check storage path exists and is mounted",
            "command": "ls -la $BETA_STORAGE_PATH",
        },
        {
            "description": "Check available disk space",
            "command": "df -h",
        },
        {
            "description": "Create the storage path if missing",
            "command": "mkdir -p $BETA_STORAGE_PATH",
        },
    ],
    "database_error": [
        {
            "description": "Check database container is running",
            "command": "docker compose ps db",
        },
        {
            "description": "Check database container logs",
            "command": "docker compose logs db",
        },
        {
            "description": "Verify BETA_DATABASE_URL is correct",
            "command": "wooprice configure show",
        },
    ],
    "docker_error": [
        {
            "description": "Check container status",
            "command": "docker compose ps",
        },
        {
            "description": "Check container logs for errors",
            "command": "docker compose logs",
        },
    ],
    "unknown_error": [
        {
            "description": "Check application logs for error details",
            "command": "wooprice logs",
        },
        {
            "description": "Run full diagnostics for more information",
            "command": "wooprice diagnostics run",
        },
    ],
}


class ProbableCauseInferrer:
    """Infers a human-readable probable cause from a FailureClass."""

    _CAUSES: dict[str, str] = {
        "none": "No failure — the service is operating normally.",
        "dns_failure": (
            "The hostname does not resolve. Either the configured URL is incorrect "
            "or DNS is not working for this hostname from this server."
        ),
        "tcp_failure": (
            "DNS resolved but the TCP connection failed. "
            "The service may not be listening on the expected port, "
            "or a firewall is blocking the connection."
        ),
        "tls_failure": (
            "The TLS certificate is invalid, expired, or the TLS handshake failed. "
            "The server certificate may not match the hostname."
        ),
        "timeout": (
            "The service did not respond within the configured timeout. "
            "The service may be overloaded, or a firewall may be silently dropping packets."
        ),
        "unauthorized": (
            "The service rejected the credentials. "
            "The username, password, or API key may be incorrect or the account may be locked."
        ),
        "forbidden": (
            "Credentials are valid but access was denied. "
            "The account may lack required permissions or API access on the remote service."
        ),
        "unreachable": (
            "The service is not accepting connections. "
            "The service may be down or a firewall may be blocking the connection."
        ),
        "invalid_response": (
            "The service responded with unexpected content. "
            "The API path may have changed, or the service may be returning an error page."
        ),
        "configuration_error": (
            "A required configuration value is missing, malformed, or invalid."
        ),
        "permission_error": (
            "The application cannot read or write to a required path."
        ),
        "storage_error": (
            "The storage path is missing, not mounted, or has insufficient disk space."
        ),
        "database_error": (
            "The PostgreSQL database is not reachable or the credentials were rejected."
        ),
        "docker_error": (
            "A Docker container or the Docker runtime is not operating normally."
        ),
        "plugin_error": "A plugin has failed or been quarantined.",
        "unknown_error": "An unexpected error occurred. Check application logs for details.",
    }

    def infer(self, failure_class: FailureClass) -> str:
        return self._CAUSES.get(failure_class.value, "Unknown failure condition.")


class RepairPlaybook:
    """Returns ordered RepairSteps for a given FailureClass."""

    def steps_for(self, failure_class: FailureClass) -> list[RepairStep]:
        raw = _PLAYBOOKS.get(failure_class.value, [])
        return [
            RepairStep(
                step_number=i + 1,
                description=entry["description"],
                command=entry.get("command"),
                detail=entry.get("detail"),
            )
            for i, entry in enumerate(raw)
        ]
