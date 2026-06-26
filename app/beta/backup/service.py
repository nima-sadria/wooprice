"""WooPrice Beta — BackupService.

Creates timestamped backup archives containing pg_dump, SQLite dump,
and BETA_STORAGE_PATH files. Supports restore from archive.

Implementation begins in B13.
"""


class BackupService:
    """Creates and restores backup archives.

    Implementation begins in B13.
    """

    def create(self, *, label: str | None = None, output_path: str | None = None) -> str:
        """Create a backup archive. Returns the archive path.

        Implementation begins in B13.
        """
        raise NotImplementedError("Implementation begins in B13.")

    def list_backups(self) -> list[dict]:
        """Return list of available backup archives with metadata.

        Implementation begins in B13.
        """
        raise NotImplementedError("Implementation begins in B13.")

    def restore(self, backup_id: str) -> None:
        """Restore from a backup archive by ID.

        Implementation begins in B13.
        """
        raise NotImplementedError("Implementation begins in B13.")
