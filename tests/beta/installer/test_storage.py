"""Tests for storage directory setup."""

from pathlib import Path

import pytest

from installer.installer_core import (
    InstallerRollback,
    _STORAGE_SUBDIRS,
    setup_storage,
)


class TestSetupStorage:
    def test_creates_storage_subdirectories(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup)
        for subdir in _STORAGE_SUBDIRS:
            assert (storage / subdir).is_dir(), f"Missing: {subdir}"

    def test_creates_backup_path(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup)
        assert backup.is_dir()

    def test_creates_logs_subdir(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup)
        assert (storage / "logs").is_dir()

    def test_creates_config_subdir(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup)
        assert (storage / "config").is_dir()

    def test_creates_plugins_subdir(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup)
        assert (storage / "plugins").is_dir()

    def test_creates_uploads_subdir(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup)
        assert (storage / "uploads").is_dir()

    def test_creates_diagnostics_subdir(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup)
        assert (storage / "diagnostics").is_dir()

    def test_returns_list_of_created_dirs(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        created = setup_storage(storage, backup)
        assert isinstance(created, list)
        assert len(created) > 0

    def test_tracks_created_dirs_in_rollback(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        rollback = InstallerRollback()
        setup_storage(storage, backup, rollback=rollback)
        tracked = rollback.tracked_dirs
        assert len(tracked) > 0

    def test_does_not_track_preexisting_dirs(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        # Pre-create one subdir
        (storage / "logs").mkdir(parents=True)
        rollback = InstallerRollback()
        setup_storage(storage, backup, rollback=rollback)
        # logs was pre-existing, should not be in rollback
        assert (storage / "logs") not in rollback.tracked_dirs

    def test_idempotent_on_existing_dirs(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup)
        # Second call should not raise
        setup_storage(storage, backup)
        assert (storage / "logs").is_dir()


class TestSetupStorageDryRun:
    def test_dry_run_writes_nothing(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        setup_storage(storage, backup, dry_run=True)
        assert not storage.exists()
        assert not backup.exists()

    def test_dry_run_returns_expected_dirs(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        dirs = setup_storage(storage, backup, dry_run=True)
        assert isinstance(dirs, list)
        assert len(dirs) == len(_STORAGE_SUBDIRS) + 1  # subdirs + backup_path

    def test_dry_run_includes_all_subdirs(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        dirs = setup_storage(storage, backup, dry_run=True)
        dir_names = {d.name for d in dirs}
        for subdir in _STORAGE_SUBDIRS:
            assert subdir in dir_names, f"Dry-run missing: {subdir}"

    def test_dry_run_includes_backup_path(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        dirs = setup_storage(storage, backup, dry_run=True)
        assert backup in dirs

    def test_dry_run_does_not_track_in_rollback(self, tmp_path: Path):
        storage = tmp_path / "storage"
        backup = tmp_path / "backups"
        rollback = InstallerRollback()
        setup_storage(storage, backup, rollback=rollback, dry_run=True)
        assert rollback.tracked_dirs == []
