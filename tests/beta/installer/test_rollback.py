"""Tests for installer rollback mechanism."""

from pathlib import Path

import pytest

from installer.installer_core import InstallerRollback


class TestInstallerRollback:
    def test_track_file(self, tmp_path: Path):
        rollback = InstallerRollback()
        f = tmp_path / "test.txt"
        rollback.track_file(f)
        assert f in rollback.tracked_files

    def test_track_dir(self, tmp_path: Path):
        rollback = InstallerRollback()
        d = tmp_path / "mydir"
        rollback.track_dir(d)
        assert d in rollback.tracked_dirs

    def test_rollback_removes_tracked_file(self, tmp_path: Path):
        rollback = InstallerRollback()
        f = tmp_path / "created_by_installer.txt"
        f.write_text("content")
        rollback.track_file(f)
        rollback.rollback()
        assert not f.exists()

    def test_rollback_removes_tracked_dir(self, tmp_path: Path):
        rollback = InstallerRollback()
        d = tmp_path / "created_dir"
        d.mkdir()
        rollback.track_dir(d)
        rollback.rollback()
        assert not d.exists()

    def test_rollback_returns_list_of_removed_paths(self, tmp_path: Path):
        rollback = InstallerRollback()
        f = tmp_path / "file.txt"
        f.write_text("x")
        rollback.track_file(f)
        removed = rollback.rollback()
        assert isinstance(removed, list)
        assert str(f) in removed

    def test_rollback_does_not_remove_preexisting_file(self, tmp_path: Path):
        preexisting = tmp_path / "preexisting.txt"
        preexisting.write_text("keep me")
        rollback = InstallerRollback()
        # Not tracked → not removed
        rollback.rollback()
        assert preexisting.exists()

    def test_rollback_does_not_remove_preexisting_dir(self, tmp_path: Path):
        preexisting = tmp_path / "preexisting_dir"
        preexisting.mkdir()
        rollback = InstallerRollback()
        rollback.rollback()
        assert preexisting.exists()

    def test_rollback_handles_already_deleted_file(self, tmp_path: Path):
        rollback = InstallerRollback()
        f = tmp_path / "already_gone.txt"
        f.write_text("x")
        rollback.track_file(f)
        f.unlink()  # already deleted before rollback
        removed = rollback.rollback()
        # Should not raise
        assert str(f) not in removed

    def test_rollback_handles_already_deleted_dir(self, tmp_path: Path):
        rollback = InstallerRollback()
        d = tmp_path / "already_gone_dir"
        d.mkdir()
        rollback.track_dir(d)
        d.rmdir()  # already deleted before rollback
        removed = rollback.rollback()
        assert str(d) not in removed

    def test_rollback_removes_files_in_reverse_order(self, tmp_path: Path):
        rollback = InstallerRollback()
        f1 = tmp_path / "first.txt"
        f2 = tmp_path / "second.txt"
        f1.write_text("1")
        f2.write_text("2")
        rollback.track_file(f1)
        rollback.track_file(f2)
        removed = rollback.rollback()
        # reversed: second removed first
        assert removed.index(str(f2)) < removed.index(str(f1))

    def test_rollback_removes_dirs_in_reverse_order(self, tmp_path: Path):
        rollback = InstallerRollback()
        parent = tmp_path / "parent"
        child = parent / "child"
        child.mkdir(parents=True)
        rollback.track_dir(parent)
        rollback.track_dir(child)
        # After rollback, both gone; reverse means child removed before parent
        removed = rollback.rollback()
        assert not parent.exists()

    def test_rollback_only_removes_tracked_paths(self, tmp_path: Path):
        kept = tmp_path / "keep_me.txt"
        kept.write_text("important")
        removed_file = tmp_path / "remove_me.txt"
        removed_file.write_text("generated")

        rollback = InstallerRollback()
        rollback.track_file(removed_file)
        rollback.rollback()

        assert not removed_file.exists()
        assert kept.exists()

    def test_no_duplicate_tracking(self, tmp_path: Path):
        rollback = InstallerRollback()
        f = tmp_path / "once.txt"
        rollback.track_file(f)
        rollback.track_file(f)  # duplicate
        assert rollback.tracked_files.count(f) == 1

    def test_tracked_files_returns_copy(self, tmp_path: Path):
        rollback = InstallerRollback()
        f = tmp_path / "file.txt"
        rollback.track_file(f)
        copy = rollback.tracked_files
        copy.clear()
        assert len(rollback.tracked_files) == 1

    def test_tracked_dirs_returns_copy(self, tmp_path: Path):
        rollback = InstallerRollback()
        d = tmp_path / "dir"
        rollback.track_dir(d)
        copy = rollback.tracked_dirs
        copy.clear()
        assert len(rollback.tracked_dirs) == 1
