"""WooPrice Beta — Audit Logger.

Writes structured audit events to BETA_STORAGE_PATH/logs/audit.log.
Every security-relevant event is recorded. Audit log is never purged.

Implementation begins in B10.
"""


class AuditEvent:
    """Structured audit event.

    Implementation begins in B10.
    """
    pass


class AuditLogger:
    """Writes structured JSON audit events to the audit log file.

    Implementation begins in B10.
    """

    def log(self, event: str, *, user_id: str | None = None, **fields: object) -> None:
        """Write a structured audit event.

        Implementation begins in B10.
        """
        raise NotImplementedError("Implementation begins in B10.")
